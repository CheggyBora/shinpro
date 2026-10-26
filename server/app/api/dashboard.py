"""
Данные дашборда: выручка, услуги, мастера, наряды, смены.

Смотрят двое: владелец и админ. Мастера сюда не заходят — свою
зарплату они видят в программе цеха.

Кто что видит, решают права, а не экран: админ без права на зарплаты
получит отказ и на запрос напрямую, а не только пустое место в меню.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (StaffUser, PERM_REVENUE, PERM_ORDERS,
                        PERM_SALARY_ALL, PERM_SALARY_PAY, PERM_BOOKING,
                        QueueSnapshot)
from app.security import current_staff, require
from app.services.dashboard_service import DashboardService
from app.services import tenancy, shop_settings

router = APIRouter(prefix='/dashboard', tags=['Дашборд: цифры'])


def _period(day_from: Optional[date], day_to: Optional[date]):
    """
    Период. По умолчанию — последние 30 дней, как в программе цеха.

    Перевёрнутые даты не ругаем, а меняем местами: человек ошибся в
    двух полях, а не совершил преступление.
    """
    today = date.today()
    day_to = day_to or today
    day_from = day_from or (day_to - timedelta(days=29))

    if day_from > day_to:
        day_from, day_to = day_to, day_from

    return day_from, day_to


# Переключатель «Шиномонтаж | Мойка» (docs/wash_dashboard.md): tire или
# wash. Пусто или непонятное — оба направления сразу, как до мойки
Direction = Query(None, description='tire — шиномонтаж, wash — мойка, '
                                    'пусто — всё вместе')


def _service(db, staff, shop=None, direction=None):
    """
    Считалка, настроенная на точки этого аккаунта.

    shop — выбранная точка: её имя или номер. Пусто — считаем по всем
    точкам аккаунта сразу: для владельца сети это и есть главная цифра.
    direction — шиномонтаж или мойка; пусто — всё вместе.

    Чужую точку подставить нельзя: список берётся из аккаунта, к
    которому относится сам сотрудник.
    """
    shops = tenancy.shops_of(db, staff.account_id)
    ids = [row.id for row in shops]

    if shop:
        chosen = [row.id for row in shops
                  if str(row.id) == str(shop) or row.slug == str(shop)]
        if not chosen:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail='Такой точки нет')
        ids = chosen

    return DashboardService(db, staff.account_id, ids, direction)


@router.get('/shops', summary='Точки аккаунта — для выбора на дашборде')
def shops(staff: StaffUser = Depends(current_staff),
          db: Session = Depends(get_db)):
    # stock_enabled и wash_enabled — какие разделы показывать у точки:
    # «Склад» виден, когда у выбранной точки склад включён
    return [{'id': row.id, 'slug': row.slug, 'name': row.name,
             'address': row.address, 'last_sync_at': row.last_sync_at,
             'stock_enabled': shop_settings.stock_on(db, row),
             'wash_enabled': shop_settings.wash_on(db, row)}
            for row in tenancy.shops_of(db, staff.account_id)]


@router.get('/summary', summary='Сводка за период')
def summary(day_from: Optional[date] = Query(None, alias='from'),
            day_to: Optional[date] = Query(None, alias='to'),
           shop: Optional[str] = Query(
               None, description='Точка. Пусто — все точки сети'),
            direction: Optional[str] = Direction,
            staff: StaffUser = Depends(require(PERM_REVENUE)),
            db: Session = Depends(get_db)):
    day_from, day_to = _period(day_from, day_to)
    return _service(db, staff, shop, direction).summary(day_from, day_to)


@router.get('/sales', summary='Продажи: основное и допродажи')
def sales(day_from: Optional[date] = Query(None, alias='from'),
          day_to: Optional[date] = Query(None, alias='to'),
          shop: Optional[str] = None,
          direction: Optional[str] = Direction,
          staff: StaffUser = Depends(require(PERM_REVENUE)),
          db: Session = Depends(get_db)):
    """
    Что продано основным, что допродажей и какая доля у допов.

    Доля допродаж — показатель приёмки: машин за день приезжает примерно
    одинаково, а разница между хорошим месяцем и плохим обычно сидит
    в том, предложили человеку что-то сверх или просто перекинули колёса.
    """
    day_from, day_to = _period(day_from, day_to)
    return _service(db, staff, shop, direction).sales(day_from, day_to)


@router.get('/services', summary='Выручка по услугам')
def services(day_from: Optional[date] = Query(None, alias='from'),
             day_to: Optional[date] = Query(None, alias='to'),
           shop: Optional[str] = Query(
               None, description='Точка. Пусто — все точки сети'),
             direction: Optional[str] = Direction,
             staff: StaffUser = Depends(require(PERM_REVENUE)),
             db: Session = Depends(get_db)):
    day_from, day_to = _period(day_from, day_to)
    return _service(db, staff, shop, direction).services(day_from, day_to)


@router.get('/masters', summary='Мастера и начисления')
def masters(day_from: Optional[date] = Query(None, alias='from'),
            day_to: Optional[date] = Query(None, alias='to'),
           shop: Optional[str] = Query(
               None, description='Точка. Пусто — все точки сети'),
            direction: Optional[str] = Direction,
            staff: StaffUser = Depends(require(PERM_SALARY_ALL)),
            db: Session = Depends(get_db)):
    day_from, day_to = _period(day_from, day_to)
    return _service(db, staff, shop, direction).masters(day_from, day_to)


@router.get('/orders', summary='Наряды за период')
def orders(day_from: Optional[date] = Query(None, alias='from'),
           day_to: Optional[date] = Query(None, alias='to'),
           shop: Optional[str] = Query(
               None, description='Точка. Пусто — все точки сети'),
           employee_local_id: Optional[int] = None,
           payment_method: Optional[str] = None,
           direction: Optional[str] = Direction,
           limit: int = Query(500, le=2000),
           staff: StaffUser = Depends(current_staff),
           db: Session = Depends(get_db)):
    """
    Наряды за период. Можно сузить до одного мастера.

    Сужение — для разбора: владелец открыл мастера и смотрит, из чего
    сложилась его выработка.
    """
    if not staff.can(PERM_ORDERS):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к этому разделу')

    day_from, day_to = _period(day_from, day_to)
    return _service(db, staff, shop, direction).orders(
        day_from, day_to, employee_local_id, payment_method, limit)


@router.get('/orders/{local_id}', summary='Наряд целиком')
def order_card(local_id: int, shop: Optional[str] = None,
               staff: StaffUser = Depends(current_staff),
               db: Session = Depends(get_db)):
    if not staff.can(PERM_ORDERS):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к этому разделу')

    card = _service(db, staff, shop).order_card(local_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Наряд не найден')

    return card


@router.get('/photo/{photo_id}', include_in_schema=False)
def cover_photo(photo_id: int, until: str = '', key: str = '',
                db: Session = Depends(get_db)):
    """
    Обложка наряда по подписанной ссылке из списка или карточки наряда
    (cover_url). Ссылку выдаёт только вошедшему сотруднику с доступом
    к нарядам, и живёт она полдня.
    """
    import os

    from fastapi.responses import FileResponse

    from app.models import OrderPhoto
    from app.security import staff_photo_allowed
    from app.services import photos as photo_service

    if not staff_photo_allowed(photo_id, until, key):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail='Нельзя')

    row = db.query(OrderPhoto).filter(OrderPhoto.id == photo_id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Фото не найдено')

    path = photo_service.full_path(row)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Файл не найден')

    return FileResponse(path, media_type='image/jpeg',
                        headers={'Cache-Control': 'private, max-age=3600'})


@router.get('/shifts', summary='Смены за период')
def shifts(day_from: Optional[date] = Query(None, alias='from'),
           day_to: Optional[date] = Query(None, alias='to'),
           shop: Optional[str] = Query(
               None, description='Точка. Пусто — все точки сети'),
           direction: Optional[str] = Direction,
           staff: StaffUser = Depends(current_staff),
           db: Session = Depends(get_db)):
    """
    Смены за период. С направлением «начислено» — только его часть:
    смена у шиномонтажа и мойки общая, а зарплата у каждого своя.
    """
    if not staff.can(PERM_SALARY_ALL):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к этому разделу')

    day_from, day_to = _period(day_from, day_to)
    return _service(db, staff, shop, direction).shifts(day_from, day_to)


@router.get('/shifts/current', summary='Текущая смена')
def current_shift(shop: Optional[str] = None,
                  staff: StaffUser = Depends(current_staff),
                  db: Session = Depends(get_db)):
    """
    Открытая сейчас смена и загрузка цеха.

    Слепок очереди приходит из цеха раз в десять минут. Отдаём вместе с
    его временем: если цех давно не выходил на связь, дашборд покажет
    «данные от 10:42», а не соврёт свежими цифрами.

    Направления здесь нет: смена и очередь у шиномонтажа и мойки общие,
    а денег этот ответ не несёт.
    """
    service = _service(db, staff, shop)
    shift = service.current_shift()

    ids = service.shop_ids
    snapshots = db.query(QueueSnapshot)
    if ids:
        snapshots = snapshots.filter(QueueSnapshot.shop_id.in_(ids))
    last = snapshots.order_by(QueueSnapshot.taken_at.desc()).first()

    return {
        'shift': {
            'local_id': shift.local_id,
            'started_at': shift.started_at,
            'open_posts': shift.open_posts,
        } if shift else None,
        'queue': {
            'taken_at': last.taken_at,
            'cars_in_work': last.cars_in_work,
            'cars_waiting': last.cars_waiting,
            'open_posts': last.open_posts,
            'free_in_minutes': last.free_in_minutes,
            'shift_is_open': last.shift_is_open,
        } if last else None,
    }


@router.get('/shifts/{shift_local_id}/salary', summary='Начисления за смену')
def shift_salary(shift_local_id: int, shop: Optional[str] = None,
                 direction: Optional[str] = Direction,
                 staff: StaffUser = Depends(current_staff),
                 db: Session = Depends(get_db)):
    """
    Кнопка «Начисления за смену».

    Тот же расчёт, что и в программе цеха: по каждому сотруднику итог
    и строки нарядов, из которых он сложился.
    """
    if not staff.can(PERM_SALARY_ALL):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к зарплатам')

    return _service(db, staff, shop, direction).shift_salary(shift_local_id)


# ----------------------------------------------------------------------
# Зарплата: остатки и выдача
# ----------------------------------------------------------------------

class PayoutIn(BaseModel):
    # Точка, где работает сотрудник. Нужна, когда их несколько:
    # «мастер №1» без точки — это не человек, а совпадение номеров
    shop_id: Optional[int] = None
    employee_local_id: int
    amount: float
    comment: Optional[str] = None


@router.get('/salary', summary='Остатки по зарплате')
def salary(shop: Optional[str] = None,
           staff: StaffUser = Depends(require(PERM_SALARY_ALL)),
           db: Session = Depends(get_db)):
    """
    Кому сколько начислено, выдано и осталось — за всё время.

    На шиномонтаж и мойку не делится: человеку платят одной суммой, и
    остаток «по мойке» только запутал бы выдачу.

    В ответе видно, может ли этот человек выдавать: прятать кнопку по
    роли на стороне страницы нельзя, решает сервер.
    """
    service = _service(db, staff, shop)
    people = service.salary_balances()

    # Итог по всем: сколько начислено, сколько отдано и сколько ещё
    # должны. Владельцу эта строка нужнее построчной — по ней видно,
    # хватит ли в кассе на выдачу
    return {
        'can_pay': staff.can(PERM_SALARY_PAY),
        'people': people,
        'payouts': service.payout_history(),
        'totals': {
            'accrued': round(sum(row['accrued'] for row in people), 2),
            'paid': round(sum(row['paid'] for row in people), 2),
            'balance': round(sum(row['balance'] for row in people), 2),
            'waiting': round(sum(row['waiting'] for row in people), 2),
        },
    }


@router.post('/salary/pay', summary='Отметить перевод зарплаты на карту')
def pay_salary(payload: PayoutIn, shop: Optional[str] = None,
               staff: StaffUser = Depends(require(PERM_SALARY_PAY)),
               db: Session = Depends(get_db)):
    """
    Владелец перевёл деньги на карту и отмечает это здесь.

    Наличными отсюда не выдают: деньги в кассе, и подтвердить выдачу
    может только тот, кто стоит рядом с ней, — под админским ПИНом в
    программе цеха.
    """
    try:
        payout = _service(db, staff, shop).pay_to_card(
            payload.employee_local_id, payload.amount, payload.comment,
            author_id=staff.id, shop_id=payload.shop_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {'id': payout.id, 'amount': payout.amount,
            'waiting_for_shop': True}


# ----------------------------------------------------------------------
# Настройки записи
# ----------------------------------------------------------------------
#
# Эти четыре настройки владелец меняет и из цеха, и отсюда: посты, часы
# и сам выключатель приёма записи. Из цеха — потому что там стоит
# приёмщик и видит, кто сегодня работает. Отсюда — потому что владелец
# в цеху не сидит, а запись выключить может понадобиться немедленно:
# прорвало воду, не привезли грузы, заболел мастер.
#
# Разошлись — прав тот, кто поставил позже. Обмен приносит время правки
# и сравнивает его с нашим, а не просто перезаписывает наше присланным.
#
# Вниз это уезжает при обмене: сервер сам к цеху не ходит, цех выходит
# на связь. Значит, цех увидит правку в пределах десяти минут, а для
# клиентов из интернета она действует сразу — кабинет читает сервер.

BOOKING_KEYS = ('booking_enabled', 'booking_posts',
                'booking_opens_at', 'booking_closes_at')

MIN_POSTS, MAX_POSTS = 1, 3


class BookingSettingsIn(BaseModel):
    booking_enabled: Optional[bool] = None
    booking_posts: Optional[int] = None
    booking_opens_at: Optional[str] = None
    booking_closes_at: Optional[str] = None


def _one_shop(db, staff, shop):
    """
    Точка, настройки которой правим. Одна и обязательно.

    По всем точкам сразу такие настройки менять нельзя: часы и посты у
    каждой свои, и «применить ко всем» однажды выключило бы запись там,
    где её выключать не собирались.
    """
    shops = tenancy.shops_of(db, staff.account_id)

    if not shop:
        if len(shops) == 1:
            return shops[0]
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail='Выберите точку: настройки записи у '
                                   'каждой свои')

    for row in shops:
        if str(row.id) == str(shop) or row.slug == str(shop):
            return row

    raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Такой точки нет')


def _clock(value, field):
    """«07:00» или «24:00». Иначе человек не узнает, что ошибся."""
    raw = (value or '').strip()
    try:
        hours, minutes = [int(part) for part in raw.split(':')]
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f'{field}: нужно время как 09:00')

    if not (0 <= hours <= 24 and 0 <= minutes <= 59):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=f'{field}: такого времени не бывает')

    return f'{hours:02d}:{minutes:02d}'


@router.get('/booking-settings', summary='Настройки записи точки')
def booking_settings(shop: Optional[str] = None,
                     staff: StaffUser = Depends(require(PERM_BOOKING)),
                     db: Session = Depends(get_db)):
    chosen = _one_shop(db, staff, shop)
    values = {key: shop_settings.get(db, key, shop=chosen)
              for key in BOOKING_KEYS}

    return {
        'shop': {'id': chosen.id, 'slug': chosen.slug, 'name': chosen.name,
                 'address': chosen.address,
                 'last_sync_at': chosen.last_sync_at,
                 'takes_bookings': chosen.takes_bookings},
        'booking_enabled': shop_settings.is_on(values['booking_enabled']),
        'booking_posts': int(float(values['booking_posts'] or 1)),
        'booking_opens_at': values['booking_opens_at'],
        'booking_closes_at': values['booking_closes_at'],
        'changed_at': {key: shop_settings.updated_at(db, key, shop=chosen)
                       for key in BOOKING_KEYS},
    }


@router.put('/booking-settings', summary='Поменять настройки записи')
def set_booking_settings(payload: BookingSettingsIn,
                         shop: Optional[str] = None,
                         staff: StaffUser = Depends(require(PERM_BOOKING)),
                         db: Session = Depends(get_db)):
    """
    Поменять посты, часы записи или выключить приём записи.

    Присланное применяется сразу: кабинет читает сервер и перестанет
    предлагать окна в тот же миг. Цех узнает при ближайшем обмене.
    """
    chosen = _one_shop(db, staff, shop)
    changed = []

    if payload.booking_enabled is not None:
        shop_settings.set_value(db, 'booking_enabled',
                                '1' if payload.booking_enabled else '0',
                                commit=False, shop=chosen)
        # Тот же признак у самой точки: по нему её показывают или
        # прячут в кабинете, не читая настройки на каждый запрос
        chosen.booking_enabled = bool(payload.booking_enabled)
        changed.append('booking_enabled')

    if payload.booking_posts is not None:
        posts = max(MIN_POSTS, min(MAX_POSTS, int(payload.booking_posts)))
        shop_settings.set_value(db, 'booking_posts', posts,
                                commit=False, shop=chosen)
        changed.append('booking_posts')

    if payload.booking_opens_at is not None:
        shop_settings.set_value(
            db, 'booking_opens_at',
            _clock(payload.booking_opens_at, 'Записывать с'),
            commit=False, shop=chosen)
        changed.append('booking_opens_at')

    if payload.booking_closes_at is not None:
        shop_settings.set_value(
            db, 'booking_closes_at',
            _clock(payload.booking_closes_at, 'Записывать до'),
            commit=False, shop=chosen)
        changed.append('booking_closes_at')

    # Открытие позже закрытия — окон не будет вовсе, и человек решит,
    # что сломалась запись. Проверяем по тому, что получилось в итоге,
    # а не по присланному: поменять могли только одно из двух полей.
    #
    # flush обязателен: настройки, которой раньше не было, в базе ещё
    # нет, а сессия сервера не досылает изменения перед запросом сама.
    # Без него проверка читала бы значение по умолчанию вместо того,
    # что только что прислали, и пропускала бы «с 20:00 до 09:00»
    db.flush()

    opens = shop_settings.get(db, 'booking_opens_at', shop=chosen)
    closes = shop_settings.get(db, 'booking_closes_at', shop=chosen)
    if _minutes(opens) >= _minutes(closes):
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f'Записывать с {opens} до {closes} нельзя: '
                   f'закрытие раньше открытия')

    db.commit()
    return {'ok': True, 'changed': changed}


def _minutes(value):
    try:
        hours, minutes = [int(part) for part in str(value).split(':')]
        return hours * 60 + minutes
    except (ValueError, AttributeError, TypeError):
        return 0
