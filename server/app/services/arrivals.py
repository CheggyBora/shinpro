"""
Машина с телефона: снимок при приезде → номер → наряд в цеху
(docs/order_photo.md).

Телефон только подаёт машину. Наряд создаёт приёмщик в цеху: окно
создания открывается у него само, с номером, клиентом и снимком сбоку.
Без человека за компьютером наряд не появится — так и задумано.

Снимок хранится как OrderPhoto без наряда, с видом cover. Создали
наряд — снимок привязывается к нему и становится обложкой; закрыли
окно — машина снимается, а снимок остаётся без наряда и уйдёт при
обычной уборке старых фото.
"""
from datetime import datetime, time, timedelta

from sqlalchemy import func

from app.models import Appointment, Arrival, Car, Client, OrderPhoto, Visit
from app.models.photo import COVER
from app.services import plates, shop_settings, tenancy
from app.utils import normalize_plate, now as shop_now

TIRE = 'tire'
WASH = 'wash'

# Сколько ждём цех. Дольше двух часов машина с телефона не ждёт: её
# уже оформили руками или она уехала, и всплывать ей поздно
WAIT_HOURS = 2

# Как в цеху (ui/client_card.py)
VEHICLE_TITLES = {'car': 'легковой', 'suv': 'джип/кроссовер',
                  'truck': 'коммерческий'}

DIRECTION_TITLES = {TIRE: 'шиномонтаж', WASH: 'мойка'}


class ArrivalError(Exception):
    """Понятная причина, почему машину не приняли."""


def clean_plate(value):
    """
    Номер с телефона: к виду А123ВВ777. Латиница, похожая на кириллицу,
    становится кириллицей.

    Строгую проверку российского формата здесь не делаем: приезжают и
    машины с номерами других стран, и мотоциклы. Отсекаем только
    очевидный мусор.
    """
    plate = plates.normalize(value)
    if not (4 <= len(plate) <= 12) or not plate.isalnum():
        raise ArrivalError('Впишите номер машины')
    return plate


def clean_directions(value, allowed):
    """
    ["tire"], ["wash"] или ["tire", "wash"] -> «tire», «wash», «tire,wash».

    allowed — направления, для которых включён наряд по фото. Включено
    одно — оно и есть, выбора на телефоне не было. Прислали выключенное —
    отказ: наряд по нему цех создавать не станет. Не прислали ничего —
    первое включённое.
    """
    if not allowed:
        raise ArrivalError('Наряд по фото выключен в программе цеха')

    if isinstance(value, str):
        value = value.split(',')
    found = {str(item).strip().lower() for item in (value or [])}
    found &= {TIRE, WASH}
    if not found:
        return allowed[0]
    off = [name for name in (TIRE, WASH) if name in found and name not in allowed]
    if off:
        raise ArrivalError(f'Наряд по фото для направления «{DIRECTION_TITLES[off[0]]}» '
                           f'выключен в программе цеха')
    return ','.join(name for name in (TIRE, WASH) if name in found)


def directions_list(value):
    return [name for name in (value or TIRE).split(',') if name] or [TIRE]


# ----------------------------------------------------------------------
# Подсказки телефону: есть в базе, записан
# ----------------------------------------------------------------------

def _account_shop_ids(db, shop):
    return [row.id for row in tenancy.shops_of(db, shop.account_id)] or [shop.id]


def complete_plate(db, shop, plate):
    """
    Номер без региона («А123ВВ») дополнить по базе, если такая машина
    у заказчика одна. Двух машин с одной основной частью у одного
    шиномонтажа почти не бывает, а дописать регион за человека —
    сэкономить ему десять касаний в перчатке.
    """
    if not plate or not plates.is_main_part(plate):
        return plate

    found = db.query(Car.license_plate).filter(
        Car.account_id == shop.account_id,
        Car.license_plate.like(plate + '%')).limit(3).all()
    full = {row[0] for row in found
            if row[0] and plates.is_valid(row[0]) and row[0][:6] == plate}
    return full.pop() if len(full) == 1 else plate


def known(db, shop, plate):
    """Есть ли машина в базе: чья, какая, когда была. Нет — None."""
    plate = normalize_plate(plate)
    if not plate:
        return None

    car = db.query(Car).filter(
        Car.account_id == shop.account_id,
        Car.license_plate == plate).first()

    last = db.query(func.max(Visit.visited_at)).filter(
        Visit.shop_id.in_(_account_shop_ids(db, shop)),
        Visit.license_plate == plate,
        Visit.is_deleted.is_(False)).scalar()

    if car is None and last is None:
        return None

    client = None
    if car is not None and car.client_id is not None:
        client = db.query(Client).filter(Client.id == car.client_id).first()

    about = []
    if car is not None:
        if car.vehicle_type:
            about.append(VEHICLE_TITLES.get(car.vehicle_type, car.vehicle_type))
        if car.wheel_diameter:
            diameter = str(car.wheel_diameter)
            about.append(diameter if diameter.upper().startswith('R')
                         else f'R{diameter}')

    return {
        'client_name': client.name if client is not None else None,
        'car': ' · '.join(about) or None,
        'last_visit': last.date().isoformat() if last else None,
    }


def appointment(db, shop, plate):
    """Записан ли номер сегодня в эту точку: ближайшая запись. Нет — None."""
    plate = normalize_plate(plate)
    if not plate:
        return None

    today = shop_now().date()
    row = db.query(Appointment).filter(
        Appointment.shop_id == shop.id,
        Appointment.license_plate == plate,
        Appointment.status.in_(('scheduled', 'arrived')),
        Appointment.scheduled_at >= datetime.combine(today, time.min),
        Appointment.scheduled_at <= datetime.combine(today, time.max)).order_by(
        Appointment.scheduled_at).first()
    if row is None:
        return None

    return {'time': row.scheduled_at.strftime('%H:%M'),
            'direction': row.direction or TIRE}


def hints(db, shop, plate):
    """То, что телефон показывает под номером."""
    return {
        'known': known(db, shop, plate) if plate else None,
        'appointment': appointment(db, shop, plate) if plate else None,
    }


# ----------------------------------------------------------------------
# Машина
# ----------------------------------------------------------------------

def create(db, shop, photo_id, plate, directions):
    """Подать машину в цех. Снимок — свой точки и ещё ничей."""
    plate = clean_plate(plate)
    # Сразу, до снимка: выключенное направление — отказ без побочных правок
    clean_directions(directions, shop_settings.arrival_photo_directions(db, shop))

    photo = None
    if photo_id is not None:
        photo = db.query(OrderPhoto).filter(
            OrderPhoto.id == photo_id,
            OrderPhoto.shop_id == shop.id,
            OrderPhoto.kind == COVER).first()
        if photo is None:
            raise ArrivalError('Снимок не найден. Переснимите машину')
        taken = db.query(Arrival).filter(Arrival.photo_id == photo.id).first()
        if taken is not None:
            raise ArrivalError('Эта машина уже отправлена в цех')
        if photo.order_local_id is not None:
            raise ArrivalError('Этот снимок уже стал обложкой наряда')

        # Номер поправили на телефоне — снимок должен знать верный
        photo.license_plate = plate

    arrival = Arrival(
        shop_id=shop.id,
        photo_id=photo.id if photo is not None else None,
        plate=plate,
        directions=clean_directions(
            directions, shop_settings.arrival_photo_directions(db, shop)),
        created_at=shop_now())
    db.add(arrival)
    db.commit()
    db.refresh(arrival)
    return arrival


def pending(db, shop):
    """Ждущие цеха машины: не разобраны и не старше двух часов."""
    edge = shop_now() - timedelta(hours=WAIT_HOURS)
    return db.query(Arrival).filter(
        Arrival.shop_id == shop.id,
        Arrival.done_at.is_(None),
        Arrival.created_at >= edge).order_by(Arrival.created_at).all()


def to_dict(arrival):
    return {
        'id': arrival.id,
        'plate': arrival.plate,
        'directions': directions_list(arrival.directions),
        'photo_id': arrival.photo_id,
        'created_at': arrival.created_at,
    }


def of_shop(db, shop, arrival_id):
    return db.query(Arrival).filter(
        Arrival.id == arrival_id, Arrival.shop_id == shop.id).first()


def done(db, shop, arrival, order_local_id=None):
    """
    Цех разобрался с машиной.

    С номером наряда — снимок становится обложкой этого наряда. Без
    него — приёмщик закрыл окно: машина снимается и больше не всплывает.
    Повтор с номером наряда после закрытия окна тоже принимаем: приёмщик
    мог закрыть окно и создать наряд позже, из той же машины.
    """
    arrival.done_at = arrival.done_at or shop_now()

    if order_local_id is not None:
        arrival.order_local_id = order_local_id
        photo = arrival.photo
        if photo is not None:
            from app.services.photos import _client_for

            photo.order_local_id = order_local_id
            photo.kind = COVER
            photo.license_plate = arrival.plate
            photo.client_id = _client_for(db, shop, photo)

    db.commit()
    return arrival
