"""
Запись по ссылке из браузера.

Клиент приезжает два раза в год и ставить приложение ради этого не
станет — и это не лень, а здравый смысл. Ссылку он откроет: она уже
в переписке, нажатие в один палец.

Здесь то же самое, что видит приложение, но без входа: свободные окна
и кнопка «записаться». Запись приходит в цех с пометкой «по ссылке,
не подтверждена» — приёмщик видит её и решает сам. Ставить заслон
из кодов подтверждения на пути человека, который хочет отдать деньги,
дороже, чем разобрать редкую выдуманную запись.

От баловства защищаемся мягко: с одного адреса и на один телефон
нельзя набить десяток записей за день.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Appointment, Car, Client, StoredSet, PENDING
from app.schemas import DayOut, SlotOut
from app.services import shop_settings, notify, tenancy
from app.services.booking_service import (clean_diameter, BookingService, BookingError,
                                           SLOT_TAKEN, service_for)
from app.utils import normalize_plate, normalize_phone, format_phone, now as shop_now

router = APIRouter(prefix='/public', tags=['Запись по ссылке'])

# Источник записи: по нему приёмщик отличает её от звонка и от приложения
SOURCE_LINK = 'link'

# Сколько записей можно сделать с одного адреса за час. Живой человек
# записывается один раз, изредка два — на себя и на жену
MAX_PER_ADDRESS_HOUR = 5

# И сколько активных записей может висеть на одном телефоне
MAX_ACTIVE_PER_PHONE = 3

_recent = {}


def _too_often(address):
    """Простой счётчик в памяти: от баловства хватает, базу не трогаем."""
    now = shop_now()
    edge = now - timedelta(hours=1)

    marks = [mark for mark in _recent.get(address, []) if mark > edge]
    _recent[address] = marks

    if len(marks) >= MAX_PER_ADDRESS_HOUR:
        return True

    marks.append(now)
    return False


class PublicInfoOut(BaseModel):
    shop: Optional[str] = None
    shop_name: str
    shop_phone: Optional[str] = None
    shop_address: Optional[str] = None
    minutes_assembled: int
    minutes_tires: int
    # Что можно записать через кабинет (docs/booking_wash.md). Оба —
    # кабинет первым шагом спрашивает «Шиномонтаж / Мойка»
    tire_booking: bool = True
    wash_booking: bool = False
    wash_minutes: int = 30
    # Как видят организацию клиенты: своё название, цвет и логотип
    brand_name: Optional[str] = None
    brand_color: str = '#2563eb'
    has_logo: bool = False
    logo_version: str = ''


class PublicBookingIn(BaseModel):
    # Куда записываться. Пусто — когда точка на сервере одна
    shop: Optional[str] = None
    at: datetime
    license_plate: str
    client_phone: str
    client_name: Optional[str] = None
    wheels_assembled: Optional[bool] = None
    wheel_diameter: Optional[str] = None
    # Шиномонтаж (по умолчанию) или мойка; для мойки — класс машины
    direction: Optional[str] = None
    wash_class: Optional[str] = None


class PublicBookingOut(BaseModel):
    ok: bool = True
    at: datetime
    duration_minutes: int
    shop_phone: Optional[str] = None
    storage_requested: int = 0
    message: str


def _shop(db, wanted=None):
    """
    Точка, о которой эта страница.

    Имя точки берётся из адреса: /z/shinomontazh-rif. Когда точка на
    сервере одна, имя можно не писать — но как только их становится
    больше, угадывать нельзя: человек записался бы не туда, куда думал.
    """
    shop = tenancy.page_shop(db, wanted)

    if shop is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail='Шиномонтаж не найден. Проверьте ссылку')

    # Проверяем здесь, а не только при показе списка: ссылку могли
    # сохранить в закладках, переслать или набрать руками
    if not shop.takes_bookings:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail='Этот адрес сейчас не принимает запись через интернет. '
                   'Позвоните нам, пожалуйста')

    from app.security import check_paid
    check_paid(db, shop.account_id)

    return shop


@router.get('/info', response_model=PublicInfoOut, summary='О шиномонтаже')
def info(shop: Optional[str] = Query(None, description='Короткое имя точки'),
         db: Session = Depends(get_db)):
    from app.services import branding

    row = _shop(db, shop)
    brand = branding.brand_of(db, row.account, row)
    return PublicInfoOut(
        brand_name=brand['name'],
        brand_color=brand['color'],
        has_logo=brand['has_logo'],
        logo_version=brand['logo_version'],
        shop=row.slug,
        shop_name=shop_settings.title(db, row),
        shop_phone=shop_settings.get(db, 'shop_phone', shop=row) or row.phone,
        shop_address=shop_settings.get(db, 'shop_address', shop=row) or row.address,
        minutes_assembled=shop_settings.get_int(db, 'booking_minutes_assembled',
                                                shop=row),
        minutes_tires=shop_settings.get_int(db, 'booking_minutes_tires', shop=row),
        tire_booking=bool(row.booking_enabled),
        wash_booking=shop_settings.wash_booking_on(db, row),
        wash_minutes=shop_settings.get_int(db, 'wash_booking_minutes', shop=row))


@router.get('/shops', summary='Точки, куда можно записаться')
def shops(db: Session = Depends(get_db)):
    """
    Список точек — чтобы человек выбрал, в какую едет.

    Нужен, когда кабинет открыт с голого адреса, без имени точки.
    Пока точка одна, страница открывает её сразу; как только их
    становится больше, угадывать нельзя — записать человека не в тот
    шиномонтаж хуже, чем спросить лишний раз.

    Чужих точек здесь не бывает: берём только те, что принадлежат
    заказчику этого сервера.
    """
    try:
        account_id = tenancy.account_for(db)
    except tenancy.ShopNeeded:
        # Заказчиков несколько: без имени точки выбирать не из чего,
        # и показывать чужие названия тем более нельзя
        return []

    if account_id is None:
        return []

    # Показываем только те, куда правда можно записаться. Точка, ни
    # разу не вышедшая на связь, или с выключенной записью, в списке
    # не нужна: человек выберет её и упрётся
    return [{
        'slug': row.slug,
        'name': shop_settings.title(db, row),
        'address': shop_settings.address(db, row),
    } for row in tenancy.shops_of(db, account_id) if row.takes_bookings]


@router.get('/paint', summary='Калькулятор покраски дисков')
def paint(shop: Optional[str] = Query(None, description='Короткое имя точки'),
          db: Session = Depends(get_db)):
    """
    Размеры, цены и дополнения для калькулятора покраски.

    Считает кабинет у себя, по этим числам — тем же составом, каким
    считает приёмщик в цеху. Отдельного расчёта на сервере нет
    намеренно: два места расчёта однажды назовут человеку разные суммы.

    Пока цех ничего не прислал, возвращаем выключенный калькулятор:
    выдумать цены на покраску нельзя, а показать нули — хуже, чем не
    показать ничего.
    """
    import json

    raw = shop_settings.get(db, 'paint_config', shop=_shop(db, shop))
    if not raw:
        return {'available': False, 'sizes': [], 'options': [],
                'wheels_default': 4}

    try:
        config = json.loads(raw)
    except ValueError:
        return {'available': False, 'sizes': [], 'options': [],
                'wheels_default': 4}

    config['available'] = bool(config.get('sizes'))
    return config


@router.get('/days', response_model=List[DayOut], summary='Свободные окна')
def days(wheels_assembled: Optional[bool] = Query(None),
         shop: Optional[str] = Query(None, description='Короткое имя точки'),
         direction: Optional[str] = Query(
             None, description='tire — шиномонтаж (по умолчанию), wash — мойка'),
         wash_class: Optional[str] = Query(
             None, description='Класс машины для мойки'),
         db: Session = Depends(get_db)):
    # Класс машины принимаем, но окна мойки от него пока не зависят
    try:
        service = service_for(db, _shop(db, shop), direction)
    except BookingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    calendar = service.calendar(wheels_assembled)
    return [
        DayOut(day=day['day'], is_closed=day['is_closed'],
               opens_at=day['opens_at'], closes_at=day['closes_at'],
               posts=day['posts'],
               slots=[SlotOut(**slot) for slot in day['slots']])
        for day in calendar
    ]


def _is_assembled(storage_type):
    """
    Комплект на дисках или голые шины.

    Определяем по типу хранения, а не спрашиваем клиента: программа
    знает точнее — комплект принимал мастер и записал, что именно.
    """
    if not storage_type:
        return None
    return 'диск' in storage_type.lower()


def _set_title(row):
    parts = [row.storage_type or 'Комплект']
    if row.diameter:
        parts.append(row.diameter)
    if row.brand:
        parts.append(row.brand)
    if row.wheel_type:
        parts.append(row.wheel_type.lower())
    return ' · '.join(parts)


@router.post('/book', response_model=PublicBookingOut, summary='Записаться')
def book(payload: PublicBookingIn, request: Request,
         shop: Optional[str] = Query(None, description='Короткое имя точки'),
         db: Session = Depends(get_db)):
    address = request.client.host if request.client else 'unknown'
    if _too_often(address):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail='Слишком много записей подряд. Позвоните в шиномонтаж')

    plate = normalize_plate(payload.license_plate)
    phone = normalize_phone(payload.client_phone)
    name = (payload.client_name or '').strip() or None

    if not plate:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Укажите номер автомобиля')
    if len(phone) != 11:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Укажите номер телефона полностью')

    # Имя точки принимаем и в теле, и в адресе: остальные запросы
    # страницы шлют его в адресе, и заставлять её делать для записи
    # исключение — верный способ однажды его потерять
    shop = _shop(db, payload.shop or shop)
    try:
        service = service_for(db, shop, payload.direction)
        # Мойке нужен класс машины, а колёса, диаметр и склад — нет
        wash_class = (service.check_wash_class(payload.wash_class)
                      if service.is_wash else None)
    except BookingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    now = shop_now()

    if payload.at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Это время уже прошло')

    limit = now + timedelta(days=service.days_ahead())
    if payload.at > limit:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f'Записаться можно не дальше чем на '
                   f'{service.days_ahead()} дн. вперёд')

    if _active_count(db, phone) >= MAX_ACTIVE_PER_PHONE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail='На этот телефон уже есть незакрытые записи. '
                   'Позвоните в шиномонтаж, если нужна ещё одна')

    car = db.query(Car).filter(
        Car.license_plate == plate,
        Car.account_id == shop.account_id).first()

    wheels = None if service.is_wash else payload.wheels_assembled
    if wheels is None and car is not None and not service.is_wash:
        wheels = car.wheels_assembled

    duration = service.duration_for(wheels)

    settings = service.day_settings(payload.at.date())
    if settings['is_closed']:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='В этот день мойка не работает'
                            if service.is_wash
                            else 'В этот день шиномонтаж не работает')

    if not service._slot_is_free(payload.at, duration, settings['posts']):
        # Тот же ответ, что получит приёмщик в цеху: событие одно, и
        # разные формулировки заставляли бы думать, что запреты разные
        raise HTTPException(status.HTTP_409_CONFLICT, detail=SLOT_TAKEN)

    # Клиента заводим: он уже назвал телефон, и цеху он понадобится.
    # Машину тоже — иначе при следующем визите заведётся вторая
    client = db.query(Client).filter(
        Client.phone == phone,
        Client.account_id == shop.account_id).first()
    if client is None:
        client = Client(phone=phone, name=name, account_id=shop.account_id)
        db.add(client)
        db.flush()
    elif name and not client.name:
        client.name = name

    if car is None:
        car = Car(license_plate=plate, client_id=client.id,
                  account_id=shop.account_id)
        db.add(car)
        db.flush()
    elif car.client_id is None:
        car.client_id = client.id

    if wheels is not None and car.wheels_assembled is None:
        car.wheels_assembled = wheels

    appointment = Appointment(
        shop_id=shop.id,
        client_id=client.id,
        car_id=car.id,
        scheduled_at=payload.at,
        duration_minutes=duration,
        license_plate=plate,
        client_name=name or client.name,
        client_phone=phone,
        wheels_assembled=wheels,
        wheel_diameter=(None if service.is_wash
                        else clean_diameter(payload.wheel_diameter)),
        direction=service.direction,
        wash_class=wash_class,
        status='scheduled',
        source=SOURCE_LINK)

    db.add(appointment)
    db.commit()

    shop_phone = shop_settings.get(db, 'shop_phone', shop=shop) or shop.phone
    return PublicBookingOut(
        at=payload.at,
        duration_minutes=duration,
        shop_phone=shop_phone,
        message=f'Записали на {payload.at:%d.%m} в {payload.at:%H:%M}. '
                + (f'Мойка займёт около {duration} мин.' if service.is_wash
                   else f'Работы займут около {duration} мин.'))


def _tell_the_shop(db, appointment, stored, client):
    """
    Сообщить в Telegram, что к записи нужно достать комплект.

    Ждать следующего обмена нельзя: между записью и приездом может
    быть меньше суток, а комплект надо найти на складе и подготовить.
    """
    sets = '\n'.join(f'• № {row.id} — {_set_title(row)}' for row in stored)
    who = client.name or 'без имени'

    notify.send_in_background(
        f'<b>Достать комплект со склада</b>\n\n'
        f'{appointment.scheduled_at:%d.%m.%Y} в '
        f'{appointment.scheduled_at:%H:%M}\n'
        f'{appointment.license_plate} · {who} · '
        f'{format_phone(appointment.client_phone)}\n\n'
        f'{sets}\n\n'
        f'Записался сам, по ссылке.',
        shop=appointment.shop_id, kind=notify.KIND_STORAGE)


def _active_count(db, phone):
    """Сколько записей уже ждёт этого человека."""
    return db.query(Appointment).filter(
        Appointment.client_phone == phone,
        Appointment.status == 'scheduled',
        Appointment.scheduled_at >= shop_now()).count()
