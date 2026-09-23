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
from app.services import shop_settings, notify
from app.services.booking_service import BookingService, BookingError
from app.utils import normalize_plate, normalize_phone, format_phone

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
    now = datetime.utcnow()
    edge = now - timedelta(hours=1)

    marks = [mark for mark in _recent.get(address, []) if mark > edge]
    _recent[address] = marks

    if len(marks) >= MAX_PER_ADDRESS_HOUR:
        return True

    marks.append(now)
    return False


class PublicInfoOut(BaseModel):
    shop_name: str
    shop_phone: Optional[str] = None
    shop_address: Optional[str] = None
    minutes_assembled: int
    minutes_tires: int


class PublicBookingIn(BaseModel):
    at: datetime
    license_plate: str
    client_phone: str
    client_name: Optional[str] = None
    wheels_assembled: Optional[bool] = None


class PublicBookingOut(BaseModel):
    ok: bool = True
    at: datetime
    duration_minutes: int
    shop_phone: Optional[str] = None
    storage_requested: int = 0
    message: str


@router.get('/info', response_model=PublicInfoOut, summary='О шиномонтаже')
def info(db: Session = Depends(get_db)):
    return PublicInfoOut(
        shop_name=shop_settings.get(db, 'shop_name') or 'Шиномонтаж',
        shop_phone=shop_settings.get(db, 'shop_phone'),
        shop_address=shop_settings.get(db, 'shop_address'),
        minutes_assembled=shop_settings.get_int(db, 'booking_minutes_assembled'),
        minutes_tires=shop_settings.get_int(db, 'booking_minutes_tires'))


@router.get('/days', response_model=List[DayOut], summary='Свободные окна')
def days(wheels_assembled: Optional[bool] = Query(None),
         db: Session = Depends(get_db)):
    calendar = BookingService(db).calendar(wheels_assembled)
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

    service = BookingService(db)
    now = datetime.now()

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

    car = db.query(Car).filter(Car.license_plate == plate).first()

    wheels = payload.wheels_assembled
    if wheels is None and car is not None:
        wheels = car.wheels_assembled

    duration = service.duration_for(wheels)

    settings = service.day_settings(payload.at.date())
    if settings['is_closed']:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='В этот день шиномонтаж не работает')

    if not service._slot_is_free(payload.at, duration, settings['posts']):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail='Это время только что заняли. '
                                   'Выберите другое')

    # Клиента заводим: он уже назвал телефон, и цеху он понадобится.
    # Машину тоже — иначе при следующем визите заведётся вторая
    client = db.query(Client).filter(Client.phone == phone).first()
    if client is None:
        client = Client(phone=phone, name=name)
        db.add(client)
        db.flush()
    elif name and not client.name:
        client.name = name

    if car is None:
        car = Car(license_plate=plate, client_id=client.id)
        db.add(car)
        db.flush()
    elif car.client_id is None:
        car.client_id = client.id

    if wheels is not None and car.wheels_assembled is None:
        car.wheels_assembled = wheels

    appointment = Appointment(
        client_id=client.id,
        car_id=car.id,
        scheduled_at=payload.at,
        duration_minutes=duration,
        license_plate=plate,
        client_name=name or client.name,
        client_phone=phone,
        wheels_assembled=wheels,
        status='scheduled',
        source=SOURCE_LINK)

    db.add(appointment)
    db.commit()

    shop_phone = shop_settings.get(db, 'shop_phone')
    return PublicBookingOut(
        at=payload.at,
        duration_minutes=duration,
        shop_phone=shop_phone,
        message=f'Записали на {payload.at:%d.%m} в {payload.at:%H:%M}. '
                f'Работы займут около {duration} мин.')


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
        f'Записался сам, по ссылке.')


def _active_count(db, phone):
    """Сколько записей уже ждёт этого человека."""
    return db.query(Appointment).filter(
        Appointment.client_phone == phone,
        Appointment.status == 'scheduled',
        Appointment.scheduled_at >= datetime.now()).count()
