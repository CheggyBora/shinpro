"""Онлайн-запись: свободные окна, заявка, свои записи, отмена."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client
from app.schemas import DayOut, SlotOut, BookingIn, AppointmentOut
from app.security import current_client
from app.services.booking_service import BookingService, BookingError, to_public

router = APIRouter(prefix='/booking', tags=['Запись'])


@router.get('/days', response_model=List[DayOut],
            summary='Свободные окна на ближайшие дни')
def days(wheels_assembled: Optional[bool] = Query(
             None, description='Колёса в сборе — от этого зависит время работ'),
         client: Client = Depends(current_client),
         db: Session = Depends(get_db)):
    """
    Календарь со свободными окнами.

    Длительность зависит от того, в сборе колёса или россыпью, поэтому
    и окна разные: под перекидку готовых колёс место найдётся там,
    где под разбортовку уже не влезет.
    """
    calendar = BookingService(db).calendar(wheels_assembled)
    return [
        DayOut(day=day['day'], is_closed=day['is_closed'],
               opens_at=day['opens_at'], closes_at=day['closes_at'],
               posts=day['posts'],
               slots=[SlotOut(**slot) for slot in day['slots']])
        for day in calendar
    ]


@router.post('', response_model=AppointmentOut, summary='Записаться')
def book(payload: BookingIn,
         client: Client = Depends(current_client),
         db: Session = Depends(get_db)):
    try:
        appointment = BookingService(db).book(
            client, payload.at, payload.license_plate,
            payload.wheels_assembled, payload.comment,
            storage_ids=payload.storage_ids)
    except BookingError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return AppointmentOut(**to_public(appointment))


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
