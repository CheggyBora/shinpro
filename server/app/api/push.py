"""
Уведомления в браузере: что кабинет спрашивает и что присылает.

Подписка — не настройка на сервере, а разрешение, которое человек даёт
браузеру. Поэтому сервер только запоминает выданный браузером адрес и
отдаёт открытый ключ, на который тот подписывается.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client
from app.security import current_client
from app.services import webpush

router = APIRouter(tags=['Уведомления в браузере'])


class PushKeys(BaseModel):
    p256dh: str = Field(..., max_length=200)
    auth: str = Field(..., max_length=100)


class PushIn(BaseModel):
    """То, что отдаёт браузер: `subscription.toJSON()`, как есть."""
    endpoint: str = Field(..., max_length=500)
    keys: PushKeys


class PushOut(BaseModel):
    available: bool
    connected: bool
    devices: int = 0
    public_key: Optional[str] = None


def _device_from(request: Request):
    """
    Чем человек подписался — чтобы в кабинете было понятно, какое это
    устройство. Разбирать строку браузера до версий незачем: хватает
    того, что телефон отличается от компьютера.
    """
    agent = request.headers.get('user-agent', '')

    if 'iPhone' in agent or 'iPad' in agent:
        return 'iPhone'
    if 'Android' in agent:
        return 'Телефон на Android'
    if 'Windows' in agent:
        return 'Компьютер, Windows'
    if 'Mac' in agent:
        return 'Компьютер, Mac'

    return None


@router.get('/me/push', response_model=PushOut,
            summary='Уведомления в браузере')
def status_of(client: Client = Depends(current_client),
              db: Session = Depends(get_db)):
    """
    Можно ли уведомлять этот браузер и подписан ли он уже.

    Открытый ключ отдаём всегда, когда канал настроен: без него браузер
    подписаться не сможет, а секретом он не является.
    """
    if not webpush.available():
        return PushOut(available=False, connected=False)

    rows = webpush.subscriptions(db, client)
    return PushOut(available=True, connected=bool(rows), devices=len(rows),
                   public_key=webpush.public_key())


@router.post('/me/push', response_model=PushOut, summary='Подписать браузер')
def subscribe(payload: PushIn, request: Request,
              client: Client = Depends(current_client),
              db: Session = Depends(get_db)):
    if not webpush.available():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail='Уведомления в браузере не настроены')

    try:
        webpush.subscribe(db, client, payload.endpoint,
                          payload.keys.p256dh, payload.keys.auth,
                          device=_device_from(request))
    except webpush.PushError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    rows = webpush.subscriptions(db, client)
    return PushOut(available=True, connected=True, devices=len(rows),
                   public_key=webpush.public_key())


class PushOff(BaseModel):
    # Без адреса отключаем все устройства: человек нажал в кабинете
    # «Отключить», а кабинет открыт не обязательно на том телефоне,
    # где уведомления мешают
    endpoint: Optional[str] = Field(None, max_length=500)


@router.delete('/me/push', response_model=PushOut,
               summary='Отключить уведомления в браузере')
def unsubscribe(endpoint: Optional[str] = None,
                client: Client = Depends(current_client),
                db: Session = Depends(get_db)):
    webpush.unsubscribe(db, client, endpoint)

    rows = webpush.subscriptions(db, client)
    return PushOut(available=webpush.available(), connected=bool(rows),
                   devices=len(rows),
                   public_key=webpush.public_key())
