"""
Кабинет мастера на телефоне (решение владельца 27.10.2026).

Телефон подключается по QR, как и раньше (app/api/photos.py). Дальше
мастер один раз выбирает себя из сотрудников точки и вводит ПИН,
который ему поставил приёмщик. С этого момента у него своё:

    «Мои машины»   наряды, где он мастер, — сверху
    наряд          фото и видео клиенту, «Начал» / «Готово»
    предложение    «грыжа — замена шины 650 ₽» на согласование клиенту
    заработок      сегодня, неделя, к выплате — если владелец включил

Наряд живёт в цеху, сервер его не меняет. «Начал» и «Готово» ждут цех
событием (MasterEvent), ответ клиента на предложение — тоже: цех
забирает их при живом обмене и сам ставит услугу в наряд. «Готово»
клиенту сервер говорит сразу: человек ждёт машину сейчас.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, time, timedelta

from app.config import settings
from app.models import (Account, Car, Client, MasterEvent, OpenOrder,
                        OrderPhoto, SalaryAccrual, SalaryPayout,
                        ShopEmployee, ShopService, Visit, WorkOffer,
                        KIND_READY, BY_TELEGRAM)
from app.models.account import ROLE_LK
from app.models.photo import (COVER, EVENT_DONE, EVENT_START, MEDIA_VIDEO,
                              OFFER_CALL, OFFER_NO, OFFER_PENDING, OFFER_YES)
from app.services import notices, photos, shop_settings, telegram, webpush
from app.utils import now as shop_now, normalize_plate

# Неверный ПИН подряд — и вход с этого телефона закрыт на 15 минут
PIN_TRIES = 5
PIN_LOCK_MINUTES = 15

# Клиент молчит дольше — приёмщику напоминание позвонить
SILENT_MINUTES = 10

# Владелец решает, видят ли мастера свой заработок (выключатель в
# программе цеха, «Сотрудники»). Пусто или «0» — не видят
SALARY_SETTING = 'master_salary_visible'

VIDEO_PART_BYTES = 4 * 1024 * 1024

ANSWERS = {'yes': OFFER_YES, 'call': OFFER_CALL, 'no': OFFER_NO}
ANSWER_TITLES = {
    OFFER_PENDING: 'Ждём ответа',
    OFFER_YES: 'Согласен',
    OFFER_CALL: 'Просит позвонить',
    OFFER_NO: 'Отказался',
}


class MasterError(ValueError):
    """Понятная мастеру причина отказа."""


def hash_pin(pin):
    """
    Отпечаток ПИН — тот же, что считает программа цеха. Четыре цифры
    отпечаток не спрячет; бережёт другое — предел попыток с телефона.
    """
    return hashlib.sha256(f'tire-master-pin:{str(pin).strip()}'.encode('utf-8')).hexdigest()


# ----------------------------------------------------------------------
# Кто держит телефон
# ----------------------------------------------------------------------

def employee_of(db, device):
    """
    Сотрудник телефона. Уволили или сняли ПИН — телефон сам выходит из
    кабинета: заработок уволенного другим показывать нельзя.
    """
    if device is None or device.employee_local_id is None:
        return None
    row = db.query(ShopEmployee).filter(
        ShopEmployee.shop_id == device.shop_id,
        ShopEmployee.local_id == device.employee_local_id).first()
    if row is None or not row.is_active or not row.pin_hash:
        return None
    return row


def _name(row):
    return row.name or f'№{row.local_id}'


def employees(db, shop):
    rows = db.query(ShopEmployee).filter(
        ShopEmployee.shop_id == shop.id,
        ShopEmployee.is_active.is_(True)).all()
    rows.sort(key=lambda row: (_name(row).lower(), row.local_id))
    return [{'local_id': row.local_id, 'name': _name(row),
             'has_pin': bool(row.pin_hash)} for row in rows]


def login(db, device, local_id, pin):
    now = shop_now()
    if device.locked_until is not None and device.locked_until > now:
        minutes = max(1, int((device.locked_until - now).total_seconds() // 60) + 1)
        raise MasterError(f'Много неверных ПИН. Попробуйте через {minutes} мин')

    row = db.query(ShopEmployee).filter(
        ShopEmployee.shop_id == device.shop_id,
        ShopEmployee.local_id == local_id,
        ShopEmployee.is_active.is_(True)).first()
    if row is None:
        raise MasterError('Такого сотрудника в этой точке нет')
    if not row.pin_hash:
        raise MasterError('ПИН ещё не задан. Попросите приёмщика: '
                          '«Сотрудники» → «ПИН для телефона»')

    if not hmac.compare_digest(row.pin_hash, hash_pin(pin)):
        device.pin_fails = (device.pin_fails or 0) + 1
        if device.pin_fails >= PIN_TRIES:
            device.pin_fails = 0
            device.locked_until = now + timedelta(minutes=PIN_LOCK_MINUTES)
        db.commit()
        raise MasterError('Неверный ПИН')

    device.employee_local_id = row.local_id
    device.name = (row.name or device.name or '')[:80] or None
    device.pin_fails = 0
    device.locked_until = None
    db.commit()
    return row


def logout(db, device):
    device.employee_local_id = None
    db.commit()


def author_of(db, device):
    person = employee_of(db, device)
    return _name(person) if person is not None else device.name


def salary_visible(db, shop):
    return shop_settings.get(db, SALARY_SETTING, shop=shop) == '1'


def me(db, device, shop):
    person = employee_of(db, device)
    return {
        'shop': shop_settings.title(db, shop),
        'employee': ({'local_id': person.local_id, 'name': _name(person)}
                     if person is not None else None),
        'employees': employees(db, shop),
        'salary_visible': salary_visible(db, shop),
    }


def _need_login(db, device):
    person = employee_of(db, device)
    if person is None:
        raise MasterError('Войдите под своим именем: «Кто вы» на главной')
    return person


# ----------------------------------------------------------------------
# Машины в цеху
# ----------------------------------------------------------------------

def _pending_starts(db, shop):
    """Нажатое на телефоне и ещё не забранное цехом: показываем сразу."""
    edge = shop_now() - timedelta(days=1)
    result = {}
    for row in db.query(MasterEvent).filter(
            MasterEvent.shop_id == shop.id,
            MasterEvent.taken_at.is_(None),
            MasterEvent.created_at > edge).order_by(MasterEvent.id).all():
        result[row.order_local_id] = row
    return result


def _state(row, pending):
    event = pending.get(row.local_id)
    if row.finished_at is not None or (event is not None and event.kind == EVENT_DONE):
        return 'done'
    if row.state == 'work' or (event is not None and event.kind == EVENT_START):
        return 'work'
    return 'waiting'


def _lines(text):
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def cars(db, device, shop):
    person = employee_of(db, device)
    names = {row.local_id: _name(row) for row in db.query(ShopEmployee).filter(
        ShopEmployee.shop_id == shop.id).all()}
    pending = _pending_starts(db, shop)
    rows = db.query(OpenOrder).filter(OpenOrder.shop_id == shop.id).all()

    counts = {}
    if rows:
        for photo in db.query(OrderPhoto).filter(
                OrderPhoto.shop_id == shop.id,
                OrderPhoto.kind != COVER,
                OrderPhoto.order_local_id.in_([row.local_id for row in rows])).all():
            item = counts.setdefault(photo.order_local_id,
                                     {'photo': 0, 'video': 0, 'viewed': False})
            item['video' if photo.media == MEDIA_VIDEO else 'photo'] += 1
            item['viewed'] = item['viewed'] or photo.viewed_at is not None

    result = []
    for row in rows:
        ids = row.master_ids()
        state = _state(row, pending)
        result.append({
            'order_local_id': row.local_id,
            'license_plate': row.license_plate,
            'state': state,
            'started_at': row.started_at.isoformat() if row.started_at else None,
            'planned_minutes': row.planned_minutes or 0,
            'car': row.car,
            'client_name': row.client_name,
            'wheel_diameter': row.wheel_diameter,
            'services': _lines(row.services),
            'post': row.post,
            'masters': [names.get(local_id, f'№{local_id}') for local_id in ids],
            'mine': person is not None and person.local_id in ids,
            'told': row.told_at is not None,
            'sent': counts.get(row.local_id, {'photo': 0, 'video': 0, 'viewed': False}),
        })

    order = {'work': 0, 'waiting': 1, 'done': 2}
    result.sort(key=lambda car: (not car['mine'], order[car['state']], car['order_local_id']))
    return result


def _open_order(db, shop, local_id):
    row = db.query(OpenOrder).filter(OpenOrder.shop_id == shop.id,
                                     OpenOrder.local_id == local_id).first()
    if row is None:
        raise MasterError('Этой машины уже нет в цеху')
    return row


def client_of(db, shop, plate):
    plate = normalize_plate(plate)
    if not plate:
        return None
    car = db.query(Car).filter(Car.license_plate == plate,
                               Car.account_id == shop.account_id).first()
    if car is None or car.client_id is None:
        return None
    return db.query(Client).filter(Client.id == car.client_id).first()


def _media_dict(row):
    return {
        'id': row.id,
        'media': row.media or 'photo',
        'comment': row.comment,
        'author': row.author,
        'created_at': row.created_at.isoformat(),
        'sent': row.sent_at is not None,
        'channel': row.channel,
        'error': row.last_error,
        'viewed': row.viewed_at is not None,
    }


def order(db, device, shop, local_id):
    row = _open_order(db, shop, local_id)
    client = client_of(db, shop, row.license_plate)
    account = db.get(Account, shop.account_id)
    channel = notices.channel_for(db, client, account) if client else None

    media = db.query(OrderPhoto).filter(
        OrderPhoto.shop_id == shop.id,
        OrderPhoto.kind != COVER,
        OrderPhoto.order_local_id == local_id).order_by(OrderPhoto.created_at.desc()).all()
    offers = db.query(WorkOffer).filter(
        WorkOffer.shop_id == shop.id,
        WorkOffer.order_local_id == local_id).order_by(WorkOffer.created_at.desc()).all()

    car = cars_one(db, device, shop, row)
    car.update({
        'client': {
            'name': (client.name if client else None) or row.client_name,
            # Куда уйдёт: телеграм, уведомление в кабинет или некуда
            'channel': channel,
        },
        'media': [_media_dict(item) for item in media],
        'offers': [offer_dict(db, item) for item in offers],
        'services_offer': offerable(db, shop, row),
    })
    return car


def cars_one(db, device, shop, row):
    for car in cars(db, device, shop):
        if car['order_local_id'] == row.local_id:
            return car
    raise MasterError('Этой машины уже нет в цеху')


# ----------------------------------------------------------------------
# Прайс: что можно предложить по этой машине
# ----------------------------------------------------------------------

def _price_key(service, row):
    if service.direction == 'wash':
        return (row.wash_class or '').strip().lower()
    digits = re.sub(r'\D', '', row.wheel_diameter or '')
    return f'R{digits}' if digits else ''


def offerable(db, shop, row):
    """
    Услуги с ценой для этой машины: шиномонтаж — по радиусу наряда,
    мойка — по классу машины. Цены нет — услугу не предлагаем: обещать
    клиенту «цена уточняется» мастер не должен.
    """
    result = []
    for service in db.query(ShopService).filter(ShopService.shop_id == shop.id).all():
        try:
            prices = json.loads(service.prices or '{}')
        except ValueError:
            prices = {}
        price = prices.get(_price_key(service, row)) or prices.get('')
        if not price:
            continue
        result.append({'local_id': service.local_id, 'name': service.name,
                       'direction': service.direction, 'price': int(round(price))})
    result.sort(key=lambda item: item['name'].lower())
    return result


# ----------------------------------------------------------------------
# «Начал» / «Готово»
# ----------------------------------------------------------------------

def press(db, device, shop, local_id, kind):
    person = _need_login(db, device)
    row = _open_order(db, shop, local_id)
    pending = _pending_starts(db, shop)
    state = _state(row, pending)

    if kind == EVENT_START and state != 'waiting':
        return {'ok': True, 'told': None}
    if kind == EVENT_DONE and state == 'done':
        return {'ok': True, 'told': None, 'reason': 'Уже отмечено «Готово»'}

    event = MasterEvent(shop_id=shop.id, order_local_id=local_id, kind=kind,
                        employee_local_id=person.local_id, author=_name(person),
                        created_at=shop_now())
    db.add(event)
    db.commit()

    told, reason = None, None
    if kind == EVENT_DONE:
        told, reason = tell_ready(db, shop, row)
        event.told = told is not None
        db.commit()
    return {'ok': True, 'told': told, 'reason': reason}


def tell_ready(db, shop, row):
    """«Машина готова» клиенту — сразу. Возвращает (канал, причина)."""
    if row.told_at is not None:
        return None, 'Клиенту уже сказали'
    client = client_of(db, shop, row.license_plate)
    if client is None:
        return None, 'Машина ни за кем не записана — скажите приёмщику'
    account = db.get(Account, shop.account_id)
    try:
        channel = notices.send_now(
            db, client, account, KIND_READY,
            notices.ready_text(shop_settings.title(db, shop), row.license_plate),
            about='order', about_id=row.local_id)
    except Exception as e:
        return None, f'Не доставлено: {e}'
    if channel is None:
        return None, 'Клиент не подключил ни Телеграм, ни кабинет — нужен звонок'
    return channel, None


def event_dict(row):
    return {'id': row.id, 'order_local_id': row.order_local_id, 'kind': row.kind,
            'employee_local_id': row.employee_local_id, 'author': row.author,
            'created_at': row.created_at.isoformat(), 'told': bool(row.told)}


def pending_events(db, shop):
    edge = shop_now() - timedelta(days=1)
    return db.query(MasterEvent).filter(
        MasterEvent.shop_id == shop.id,
        MasterEvent.taken_at.is_(None),
        MasterEvent.created_at > edge).order_by(MasterEvent.id).all()


def take_event(db, shop, event_id):
    row = db.query(MasterEvent).filter(MasterEvent.id == event_id,
                                       MasterEvent.shop_id == shop.id).first()
    if row is None:
        return False
    row.taken_at = row.taken_at or shop_now()
    db.commit()
    return True


# ----------------------------------------------------------------------
# Предложить работу
# ----------------------------------------------------------------------

def offer_items(offer):
    try:
        return json.loads(offer.items or '[]')
    except ValueError:
        return []


def offer_dict(db, offer):
    client = db.get(Client, offer.client_id) if offer.client_id else None
    return {
        'id': offer.id,
        'order_local_id': offer.order_local_id,
        'license_plate': offer.license_plate,
        'items': offer_items(offer),
        'total': offer.total,
        'comment': offer.comment,
        'author': offer.author,
        'employee_local_id': offer.employee_local_id,
        'state': offer.state,
        'state_title': ANSWER_TITLES.get(offer.state, offer.state),
        'sent': offer.sent_at is not None,
        'channel': offer.channel,
        'error': offer.last_error,
        'created_at': offer.created_at.isoformat(),
        'answered_at': offer.answered_at.isoformat() if offer.answered_at else None,
        'client_name': client.name if client else None,
        'client_phone': client.phone if client else None,
    }


def offer_link(db, account, offer):
    from app.services import onboarding

    base = onboarding.addresses(db, account).get(ROLE_LK)
    return f'{base}/o/{offer.token}' if base else None


def _money(value):
    return f'{int(value):,}'.replace(',', ' ') + ' ₽'


def offer_text(shop_name, offer):
    from html import escape

    lines = [f'<b>{escape(shop_name or "")}</b>']
    if offer.license_plate:
        lines.append(escape(offer.license_plate))
    lines.append(f'Мастер {escape(offer.author)} предлагает:' if offer.author
                 else 'Мастер предлагает:')
    for item in offer_items(offer):
        lines.append(f'• {escape(item["name"])} — {_money(item["price"])}')
    if len(offer_items(offer)) > 1:
        lines.append(f'Итого {_money(offer.total)}')
    if offer.comment:
        lines.append(escape(offer.comment))
    lines.append('Ответьте по кнопке — мастер ждёт.')
    return '\n'.join(lines)


def create_offer(db, device, shop, local_id, service_ids, comment=None, photo_id=None):
    person = _need_login(db, device)
    row = _open_order(db, shop, local_id)

    prices = {item['local_id']: item for item in offerable(db, shop, row)}
    items = [prices[int(i)] for i in (service_ids or []) if str(i).isdigit() and int(i) in prices]
    if not items:
        raise MasterError('Отметьте, что сделать, — из прайса')

    client = client_of(db, shop, row.license_plate)
    if client is None:
        raise MasterError('Машина ни за кем не записана — предложить некому. Скажите приёмщику')

    photo = None
    if photo_id:
        photo = db.query(OrderPhoto).filter(
            OrderPhoto.id == int(photo_id), OrderPhoto.shop_id == shop.id,
            OrderPhoto.kind != COVER).first()

    offer = WorkOffer(
        shop_id=shop.id, client_id=client.id, order_local_id=local_id,
        license_plate=row.license_plate, photo_id=photo.id if photo else None,
        items=json.dumps([{'local_id': item['local_id'], 'name': item['name'],
                           'price': item['price']} for item in items], ensure_ascii=False),
        total=int(sum(item['price'] for item in items)),
        comment=(comment or '').strip()[:500] or None,
        token=secrets.token_urlsafe(24),
        employee_local_id=person.local_id, author=_name(person),
        state=OFFER_PENDING, created_at=shop_now())
    db.add(offer)
    db.commit()
    db.refresh(offer)

    send_offer(db, shop, offer, client)
    return offer


def send_offer(db, shop, offer, client):
    account = db.get(Account, shop.account_id)
    channel = notices.channel_for(db, client, account)
    if channel is None:
        offer.last_error = 'Клиент не подключил ни Телеграм, ни кабинет — нужен звонок'
        db.commit()
        return None

    name = shop_settings.title(db, shop)
    link = offer_link(db, account, offer)
    try:
        if channel == BY_TELEGRAM:
            telegram.send_message(account, client.telegram_chat_id, offer_text(name, offer),
                                  buttons=[('Посмотреть и ответить', link)] if link else None)
        else:
            webpush.send(db, client, name,
                         f'Мастер предлагает: {offer_items(offer)[0]["name"]} — '
                         f'{_money(offer.total)}',
                         url=f'/o/{offer.token}', tag=f'offer-{offer.id}')
    except Exception as e:
        offer.last_error = str(e)[:255]
        db.commit()
        return None

    offer.sent_at = shop_now()
    offer.channel = channel
    offer.last_error = None
    db.commit()
    return channel


def offer_by_token(db, token):
    if not token or len(token) > 64:
        return None
    return db.query(WorkOffer).filter(WorkOffer.token == token).first()


def offer_public(db, offer):
    """Что видит клиент по ссылке: без входа, ссылка и есть пропуск."""
    from app.models import Shop
    from app.security import photo_key
    from app.services import branding

    shop = db.get(Shop, offer.shop_id)
    account = db.get(Account, shop.account_id)
    media = None
    photo = offer.photo
    if photo is not None and photo.client_id is not None:
        media = {'media': photo.media or 'photo',
                 'url': f'/history/photo/{photo.id}?key={photo_key(photo.id, photo.client_id)}'}
    return {
        'shop': branding.brand_name(db, account, shop),
        'color': branding.brand_color(account),
        'license_plate': offer.license_plate,
        'author': offer.author,
        'items': offer_items(offer),
        'total': offer.total,
        'comment': offer.comment,
        'state': offer.state,
        'state_title': ANSWER_TITLES.get(offer.state, offer.state),
        'media': media,
    }


def answer_offer(db, offer, answer):
    state = ANSWERS.get(answer)
    if state is None:
        raise MasterError('Непонятный ответ')
    if offer.state != OFFER_PENDING:
        return False
    offer.state = state
    offer.answered_at = shop_now()
    db.commit()
    return True


def offers_for_shop(db, shop):
    """
    Что сказать приёмщику: ответы, которые цех ещё не разобрал, и
    молчание дольше 10 минут — пора звонить.
    """
    now = shop_now()
    answered = db.query(WorkOffer).filter(
        WorkOffer.shop_id == shop.id,
        WorkOffer.state != OFFER_PENDING,
        WorkOffer.taken_at.is_(None)).all()
    silent = db.query(WorkOffer).filter(
        WorkOffer.shop_id == shop.id,
        WorkOffer.state == OFFER_PENDING,
        WorkOffer.reminded_at.is_(None),
        WorkOffer.created_at < now - timedelta(minutes=SILENT_MINUTES),
        WorkOffer.created_at > now - timedelta(days=1)).all()

    result = []
    for offer in answered:
        item = offer_dict(db, offer)
        item['kind'] = 'answer'
        result.append(item)
    for offer in silent:
        item = offer_dict(db, offer)
        item['kind'] = 'silent'
        result.append(item)
    result.sort(key=lambda item: item['id'])
    return result


def take_offer(db, shop, offer_id):
    offer = db.query(WorkOffer).filter(WorkOffer.id == offer_id,
                                       WorkOffer.shop_id == shop.id).first()
    if offer is None:
        return False
    if offer.state == OFFER_PENDING:
        offer.reminded_at = offer.reminded_at or shop_now()
    else:
        offer.taken_at = offer.taken_at or shop_now()
    db.commit()
    return True


def client_offers(db, client):
    """Ждущие ответа — карточкой в кабинете клиента."""
    edge = shop_now() - timedelta(days=2)
    rows = db.query(WorkOffer).filter(
        WorkOffer.client_id == client.id,
        WorkOffer.state == OFFER_PENDING,
        WorkOffer.created_at > edge).order_by(WorkOffer.created_at.desc()).all()
    return [{'token': row.token, 'license_plate': row.license_plate,
             'author': row.author, 'items': offer_items(row), 'total': row.total}
            for row in rows]


# ----------------------------------------------------------------------
# Заработок
# ----------------------------------------------------------------------

def earnings(db, device, shop):
    if not salary_visible(db, shop):
        raise MasterError('Заработок в кабинете выключен владельцем')
    person = _need_login(db, device)

    today = shop_now().date()
    week_start = datetime.combine(today - timedelta(days=6), time.min)

    rows = db.query(SalaryAccrual, Visit).join(
        Visit, SalaryAccrual.visit_id == Visit.id).filter(
        Visit.shop_id == shop.id,
        Visit.is_deleted.is_(False),
        SalaryAccrual.employee_local_id == person.local_id,
        Visit.visited_at >= week_start).all()

    days = {today - timedelta(days=offset): 0.0 for offset in range(7)}
    visits = {}
    for accrual, visit in rows:
        day = visit.visited_at.date()
        if day in days:
            days[day] += accrual.amount or 0.0
        if day == today:
            item = visits.setdefault(visit.id, {
                'license_plate': visit.license_plate,
                'services': _lines(visit.services)[:2],
                'amount': 0.0, 'at': visit.visited_at.isoformat()})
            item['amount'] += accrual.amount or 0.0

    from sqlalchemy import func

    accrued = db.query(func.sum(SalaryAccrual.amount)).join(
        Visit, SalaryAccrual.visit_id == Visit.id).filter(
        Visit.shop_id == shop.id, Visit.is_deleted.is_(False),
        SalaryAccrual.employee_local_id == person.local_id).scalar() or 0.0
    paid = db.query(func.sum(SalaryPayout.amount)).filter(
        SalaryPayout.shop_id == shop.id,
        SalaryPayout.employee_local_id == person.local_id).scalar() or 0.0
    payouts = db.query(SalaryPayout).filter(
        SalaryPayout.shop_id == shop.id,
        SalaryPayout.employee_local_id == person.local_id).order_by(
        SalaryPayout.paid_at.desc().nullslast(), SalaryPayout.id.desc()).limit(5).all()

    today_rows = sorted(visits.values(), key=lambda item: item['at'], reverse=True)
    return {
        'name': _name(person),
        'today': round(days[today], 2),
        'today_orders': len(today_rows),
        'orders': [{**item, 'amount': round(item['amount'], 2)} for item in today_rows],
        'week': [{'day': day.isoformat(), 'amount': round(days[day], 2)}
                 for day in sorted(days)],
        'balance': round(accrued - paid, 2),
        'payouts': [{'amount': round(row.amount or 0.0, 2),
                     'paid_at': row.paid_at.isoformat() if row.paid_at else None,
                     'method': row.method} for row in payouts],
    }


# ----------------------------------------------------------------------
# Видео: кусками
# ----------------------------------------------------------------------
#
# Минута видео — 10–25 МБ, а nginx пускает до 10 МБ за запрос. Телефон
# режет файл на куски по 4 МБ, сервер складывает их по порядку и только
# целиком отдаёт клиенту

_UPLOAD_RE = re.compile(r'^[0-9a-f]{32}$')


def _uploads():
    folder = os.path.join(settings.PHOTO_DIR, '.uploads')
    os.makedirs(folder, exist_ok=True)
    return folder


def _upload_paths(upload_id):
    if not _UPLOAD_RE.match(upload_id or ''):
        raise MasterError('Загрузка не найдена, отправьте заново')
    base = os.path.join(_uploads(), upload_id)
    return base + '.part', base + '.json'


def _upload_meta(device, upload_id):
    part, meta_path = _upload_paths(upload_id)
    try:
        with open(meta_path, encoding='utf-8') as file:
            meta = json.load(file)
    except (OSError, ValueError):
        raise MasterError('Загрузка не найдена, отправьте заново')
    if meta.get('device_id') != device.id or not os.path.isfile(part):
        raise MasterError('Загрузка не найдена, отправьте заново')
    return part, meta_path, meta


def start_video(db, device, shop, order_local_id, plate, comment, content_type, size):
    kind = photos.video_kind(content_type)
    if kind is None:
        raise MasterError('Это не видео. Нужна запись с камеры')
    if not size or size <= 0:
        raise MasterError('Пустое видео')
    if size > settings.VIDEO_MAX_BYTES:
        raise MasterError('Видео слишком большое — снимите короче, до минуты')

    limit = shop_now().timestamp() - 86400
    for name in os.listdir(_uploads()):
        path = os.path.join(_uploads(), name)
        try:
            if os.path.getmtime(path) < limit:
                os.remove(path)
        except OSError:
            pass

    upload_id = secrets.token_hex(16)
    part, meta_path = _upload_paths(upload_id)
    open(part, 'wb').close()
    with open(meta_path, 'w', encoding='utf-8') as file:
        json.dump({'device_id': device.id, 'shop_id': shop.id,
                   'order_local_id': order_local_id, 'plate': plate,
                   'comment': comment, 'content_type': kind, 'size': int(size)}, file,
                  ensure_ascii=False)
    return upload_id


def add_video_part(device, upload_id, offset, data):
    part, _meta_path, meta = _upload_meta(device, upload_id)
    if len(data) > VIDEO_PART_BYTES:
        raise MasterError('Кусок больше 4 МБ')
    have = os.path.getsize(part)
    if offset != have:
        raise MasterError(f'Ожидался кусок с {have}')
    if have + len(data) > meta['size']:
        raise MasterError('Видео длиннее, чем обещано')
    with open(part, 'ab') as file:
        file.write(data)
    return have + len(data)


def finish_video(db, device, shop, upload_id):
    part, meta_path, meta = _upload_meta(device, upload_id)
    if os.path.getsize(part) != meta['size']:
        raise MasterError('Видео дошло не целиком, отправьте заново')

    person = employee_of(db, device)
    try:
        photo = photos.save_video(
            db, shop, part, meta['content_type'],
            order_local_id=meta.get('order_local_id'), plate=meta.get('plate'),
            comment=meta.get('comment'), author=author_of(db, device),
            employee_local_id=person.local_id if person else None)
    except photos.PhotoError as e:
        raise MasterError(str(e))
    finally:
        for path in (part, meta_path):
            try:
                os.remove(path)
            except OSError:
                pass
    return photo
