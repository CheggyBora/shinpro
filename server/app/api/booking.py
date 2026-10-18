"""Онлайн-запись: свободные окна, заявка, свои записи, отмена."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import tenancy
from app.models import Client
from app.schemas import DayOut, SlotOut, BookingIn, AppointmentOut
from app.security import current_client
from app.services.booking_service import BookingService, BookingError, to_public

router = APIRouter(prefix='/booking', tags=['Запись'])


def _shop(db, client, wanted=None):
    """
    Точка, о которой спрашивает клиент.

    У сети их может быть несколько, и тогда приложение обязано сказать,
    какая имеется в виду. Чужую не подставить: выбираем только среди
    точек того аккаунта, к которому относится сам клиент.
    """
    try:
        shop = tenancy.shop_for(db, client.account_id, wanted)
    except tenancy.ShopNeeded as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))

    if shop is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail='Шиномонтаж ещё не настроен')

    return shop


@router.get('/shops', summary='Точки, в которые можно записаться')
def shops(client: Client = Depends(current_client),
          db: Session = Depends(get_db)):
    return [{'id': shop.id, 'slug': shop.slug, 'name': shop.name,
             'address': shop.address, 'phone': shop.phone}
            for shop in tenancy.shops_of(db, client.account_id)]


@router.get('/days', response_model=List[DayOut],
            summary='Свободные окна на ближайшие дни')
def days(wheels_assembled: Optional[bool] = Query(
             None, description='Колёса в сборе — от этого зависит время работ'),
         shop: Optional[str] = Query(
             None, description='Точка. Нужна, когда их у сети несколько'),
         with_storage: Optional[bool] = Query(
             False, description='Клиент просит комплект со склада — '
                                'ближайшие дни закрыты'),
         client: Client = Depends(current_client),
         db: Session = Depends(get_db)):
    """
    Календарь со свободными окнами.

    Длительность зависит от того, в сборе колёса или россыпью, поэтому
    и окна разные: под перекидку готовых колёс место найдётся там,
    где под разбортовку уже не влезет.
    """
    calendar = BookingService(db, _shop(db, client, shop)).calendar(
        wheels_assembled, with_storage=bool(with_storage))
    return [
        DayOut(day=day['day'], is_closed=day['is_closed'],
               opens_at=day['opens_at'], closes_at=day['closes_at'],
               posts=day['posts'],
               storage_too_soon=day['storage_too_soon'],
               slots=[SlotOut(**slot) for slot in day['slots']])
        for day in calendar
    ]


@router.post('', response_model=AppointmentOut, summary='Записаться')
def book(payload: BookingIn,
         shop: Optional[str] = Query(None, description='Короткое имя точки'),
         client: Client = Depends(current_client),
         db: Session = Depends(get_db)):
    try:
        appointment = BookingService(
            db, _shop(db, client, payload.shop or shop)).book(
            client, payload.at, payload.license_plate,
            payload.wheels_assembled, payload.comment,
            storage_ids=payload.storage_ids,
            wheel_diameter=payload.wheel_diameter)
    except BookingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return AppointmentOut(**to_public(appointment))


@router.post('/{appointment_id}/here', response_model=AppointmentOut,
             summary='Я на месте')
def here(appointment_id: int, client: Client = Depends(current_client),
         db: Session = Depends(get_db)):
    """
    Записанный подъехал. Цех даст ему первый свободный пост — раньше
    живой очереди (docs/live_queue.md). Сообщение «вы опоздали» больше
    не нужно.
    """
    from app.models import Appointment, KIND_ARRIVE, KIND_LATE
    from app.services import notices
    from app.services.booking_service import can_check_in
    from app.utils import now as shop_now

    row = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.client_id == client.id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Запись не найдена')
    if row.on_site_at is None:
        if not can_check_in(row):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail='Отметиться можно за час до записи и в течение часа после')
        row.on_site_at = shop_now()
        db.commit()
        notices.cancel_about(db, 'appointment', row.id, kinds=[KIND_ARRIVE, KIND_LATE])
    return AppointmentOut(**to_public(row))


@router.get('/my', response_model=List[AppointmentOut],
            summary='Мои записи')
def my_appointments(include_past: bool = False,
                    client: Client = Depends(current_client),
                    db: Session = Depends(get_db)):
    rows = BookingService(db).my_appointments(client, include_past=include_past)
    return [AppointmentOut(**to_public(row)) for row in rows]


@router.delete('/{appointment_id}', response_model=AppointmentOut,
               summary='Отменить свою запись')
def cancel(appointment_id: int,
           client: Client = Depends(current_client),
           db: Session = Depends(get_db)):
    try:
        appointment = BookingService(db).cancel(client, appointment_id)
    except BookingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return AppointmentOut(**to_public(appointment))
