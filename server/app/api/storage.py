"""
Шины на хранении и заявка привезти комплект к дате.

Заявка не меняет ничего в цеху сама — она ложится в очередь и ждёт,
пока программа шиномонтажа её заберёт. До этого клиент видит
«заявка отправлена», а не «привезём»: обещать за цех сервер не вправе.
"""
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, StoredSet, PENDING
from app.schemas import StoredSetOut, StorageRequestIn
from app.security import current_client
from app.utils import now as shop_now

router = APIRouter(prefix='/storage', tags=['Хранение шин'])

# Заявку принимаем не «на завтра утром», а с запасом: комплект надо
# найти на складе и подготовить
MIN_HOURS_AHEAD = 12


def _to_public(row, now=None):
    now = now or shop_now()
    days_left = None
    if row.expires_at:
        days_left = (row.expires_at - now).days

    return StoredSetOut(
        id=row.id,
        license_plate=row.license_plate,
        storage_type=row.storage_type,
        wheel_type=row.wheel_type,
        diameter=row.diameter,
        brand=row.brand,
        accepted_at=row.accepted_at,
        expires_at=row.expires_at,
        days_left=days_left,
        status=row.status,
        requested_for=row.requested_for,
        request_state=row.request_state)


@router.get('', response_model=List[StoredSetOut],
            summary='Мои комплекты на хранении')
def my_sets(client: Client = Depends(current_client),
            db: Session = Depends(get_db)):
    rows = db.query(StoredSet).filter(
        StoredSet.client_id == client.id,
        StoredSet.status == 'stored',
    ).order_by(StoredSet.accepted_at.desc()).all()

    return [_to_public(row) for row in rows]


@router.post('/{set_id}/request', response_model=StoredSetOut,
             summary='Попросить привезти комплект к дате')
def request_delivery(set_id: int, payload: StorageRequestIn,
                     client: Client = Depends(current_client),
                     db: Session = Depends(get_db)):
    row = db.query(StoredSet).filter(
        StoredSet.id == set_id,
        StoredSet.client_id == client.id).first()

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail='Комплект не найден')

    if row.status != 'stored':
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Этот комплект уже выдан')

    now = shop_now()
    if payload.at < now + timedelta(hours=MIN_HOURS_AHEAD):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f'Комплект нужно заказать минимум за {MIN_HOURS_AHEAD} ч. '
                   f'Если нужно срочно — позвоните в шиномонтаж')

    row.requested_for = payload.at
    row.request_state = PENDING
    row.requested_at = now
    db.commit()
    db.refresh(row)
    return _to_public(row, now=now)


@router.delete('/{set_id}/request', response_model=StoredSetOut,
               summary='Отменить заявку на комплект')
def cancel_request(set_id: int,
                   client: Client = Depends(current_client),
                   db: Session = Depends(get_db)):
    row = db.query(StoredSet).filter(
        StoredSet.id == set_id,
        StoredSet.client_id == client.id).first()

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail='Комплект не найден')

    # Отмену тоже надо донести до цеха — комплект уже могли начать
    # доставать. Поэтому не стираем заявку, а помечаем отменённой
    row.requested_for = None
    row.request_state = PENDING if row.request_state else None
    db.commit()
    db.refresh(row)
    return _to_public(row)
