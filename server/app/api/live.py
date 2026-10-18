"""
Живая очередь по QR (docs/live_queue.md).

Человек у въезда сканирует QR, открывается /z/<точка>/q: номер машины,
телефон, диаметр, колёса — «Встать в очередь». Место лежит в куке
телефона: обновил страницу, закрыл и открыл — он на своём месте.

Раздаёт посты программа цеха. Сервер только принимает места и
показывает человеку то, что прислал цех: какой он по счёту, примерно
когда, на какой пост ехать. Обмен — POST /sync/live.
"""
import secrets
from datetime import timedelta
from typing import List, Optional

from fastapi import (APIRouter, Depends, Header, HTTPException, Query,
                     Request, Response, status)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, Shop, KIND_QUEUE
from app.models.live import LiveTicket, WAITING, CALLED, SERVING, DONE, LEFT, ACTIVE
from app.security import decode_token, require_sync_key
from app.services import notices, tenancy
from app.utils import normalize_phone, normalize_plate, now as shop_now

router = APIRouter(prefix='/live', tags=['Живая очередь'])
sync_router = APIRouter(prefix='/sync', tags=['Обмен с цехом'])

COOKIE = 'tire_live'
COOKIE_HOURS = 12
# Цех молчит дольше — считаем, что у него нет связи: место по QR
# не даём, иначе человек будет ждать в очереди, которую никто не видит
ONLINE_MINUTES = 3

DIAMETERS = [f'R{n}' for n in range(13, 25)]
STATES = (WAITING, CALLED, SERVING, DONE, LEFT)


# ----------------------------------------------------------------------
# Помощники
# ----------------------------------------------------------------------

def _shop(db, slug):
    shop = tenancy.shop_by_slug(db, slug) if slug else tenancy.only_shop(db)
    if shop is None or not shop.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail='Шиномонтаж не найден. Проверьте ссылку')
    return shop


def _online(shop):
    if not shop.last_sync_at:
        return False
    return shop_now() - shop.last_sync_at <= timedelta(minutes=ONLINE_MINUTES)


def _client(db, authorization, shop):
    """Кто вошёл в кабинет — или None. Без входа очередь тоже работает."""
    if not authorization or not authorization.lower().startswith('bearer '):
        return None
    client_id = decode_token(authorization.split(' ', 1)[1].strip())
    if not client_id:
        return None
    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None or client.is_blocked or client.account_id != shop.account_id:
        return None
    return client


def _is_https(request: Request):
    forwarded = (request.headers.get('x-forwarded-proto') or '').lower()
    return forwarded == 'https' or request.url.scheme == 'https'


def _keep(response: Response, token: str, request: Request):
    response.set_cookie(COOKIE, token, max_age=COOKIE_HOURS * 3600,
                        httponly=True, secure=_is_https(request),
                        samesite='lax', path='/')


def _mine(db, shop, request):
    token = request.cookies.get(COOKIE) or ''
    if not token:
        return None
    return db.query(LiveTicket).filter(LiveTicket.token == token,
                                       LiveTicket.shop_id == shop.id).first()


def view(ticket):
    if ticket is None:
        return None
    post = ticket.post_number if ticket.state in (CALLED, SERVING) else None
    return {
        'license_plate': ticket.license_plate,
        'state': ticket.state,
        'place': ticket.place,
        'eta': ticket.eta_at.strftime('%H:%M') if ticket.eta_at else None,
        'post': post,
        # Схема площадки со стрелками до поста
        'scene': f'/parking?client=1#post{post}' if post else None,
        'seen_by_shop': ticket.local_id is not None,
    }


# ----------------------------------------------------------------------
# Страница очереди
# ----------------------------------------------------------------------

class JoinIn(BaseModel):
    license_plate: str
    phone: Optional[str] = None
    wheel_diameter: Optional[str] = None
    wheels_assembled: Optional[bool] = None


@router.get('/state', summary='Моё место в очереди')
def state(request: Request, shop: Optional[str] = Query(None),
          authorization: str = Header(default=''),
          db: Session = Depends(get_db)):
    place = _shop(db, shop)
    client = _client(db, authorization, place)
    mine = _mine(db, place, request)
    return {
        'shop': place.name,
        'online': _online(place),
        'ticket': view(mine) if mine and mine.state != LEFT else None,
        'diameters': DIAMETERS,
        'signed_in': client is not None,
        'phone': client.phone if client else None,
    }


@router.post('/join', summary='Встать в очередь')
def join(payload: JoinIn, request: Request, response: Response,
         shop: Optional[str] = Query(None),
         authorization: str = Header(default=''),
         db: Session = Depends(get_db)):
    place = _shop(db, shop)
    if not _online(place):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Сейчас нет связи с шиномонтажом. Подойдите, пожалуйста, '
                   'к приёмщику — он поставит вас в очередь')

    client = _client(db, authorization, place)
    plate = normalize_plate(payload.license_plate)
    if not plate:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail='Укажите номер машины')
    phone = client.phone if client else normalize_phone(payload.phone or '')
    if not phone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail='Укажите телефон')
    if payload.wheel_diameter and payload.wheel_diameter not in DIAMETERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail='Диаметр — от R13 до R24')

    # Одна машина — одно место. Тот же телефон возвращает на своё
    # место; с чужим — отказ, иначе по номеру можно снять чужое место
    existing = db.query(LiveTicket).filter(
        LiveTicket.shop_id == place.id, LiveTicket.license_plate == plate,
        LiveTicket.state.in_(ACTIVE), LiveTicket.left_by_client.is_(False)).first()
    if existing is not None:
        if existing.phone and existing.phone != phone:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail='Эта машина уже в очереди с другим телефоном. '
                       'Подойдите к приёмщику')
        _keep(response, existing.token, request)
        return view(existing)

    ticket = LiveTicket(
        shop_id=place.id, client_id=client.id if client else None,
        token=secrets.token_urlsafe(24), license_plate=plate, phone=phone,
        wheel_diameter=payload.wheel_diameter,
        wheels_assembled=payload.wheels_assembled, state=WAITING)
    db.add(ticket)
    db.commit()
    _keep(response, ticket.token, request)
    return view(ticket)


@router.post('/leave', summary='Выйти из очереди')
def leave(request: Request, response: Response,
          shop: Optional[str] = Query(None), db: Session = Depends(get_db)):
    place = _shop(db, shop)
    mine = _mine(db, place, request)
    if mine is None or mine.state not in ACTIVE:
        # Место уже закрыто (обслужили) — забываем его, чтобы можно
        # было встать снова
        response.delete_cookie(COOKIE, path='/')
        return {'left': False}
    mine.left_by_client = True
    if mine.local_id is None:
        # Цех ещё не видел — просто закрываем
        mine.state = LEFT
    db.commit()
    return {'left': True}


# ----------------------------------------------------------------------
# Обмен с цехом
# ----------------------------------------------------------------------

class EntryIn(BaseModel):
    local_id: int
    server_id: Optional[int] = None
    state: str
    place: Optional[int] = None
    eta_at: Optional[str] = None
    post_number: Optional[int] = None


class LiveIn(BaseModel):
    entries: List[EntryIn] = []


def _parse(moment):
    if not moment:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(moment).replace(tzinfo=None)
    except ValueError:
        return None


def _tell(db, shop, ticket):
    """Позвали — сказать тем, кто вошёл в кабинет. Без входа — видно на странице."""
    if ticket.told_at is not None:
        return
    ticket.told_at = shop_now()
    if not ticket.client_id:
        return
    client = db.query(Client).filter(Client.id == ticket.client_id).first()
    if client is None:
        return
    text = (f'{ticket.license_plate}: проезжайте на пост {ticket.post_number}. '
            f'Схема — на странице очереди.')
    try:
        notices.send_now(db, client, shop.account, KIND_QUEUE, text)
    except Exception:
        pass        # не дошло — на странице очереди всё равно видно


@sync_router.post('/live', summary='Живая очередь: обмен с цехом')
def exchange(payload: LiveIn, shop: Shop = Depends(require_sync_key),
             db: Session = Depends(get_db)):
    for entry in payload.entries:
        if entry.server_id is None or entry.state not in STATES:
            continue
        ticket = db.query(LiveTicket).filter(
            LiveTicket.id == entry.server_id,
            LiveTicket.shop_id == shop.id).first()
        if ticket is None:
            continue
        ticket.local_id = entry.local_id
        if ticket.left_by_client and entry.state in ACTIVE:
            continue        # ушёл сам — цех сейчас узнает и закроет
        ticket.state = entry.state
        ticket.place = entry.place
        ticket.eta_at = _parse(entry.eta_at)
        ticket.post_number = entry.post_number
        if entry.state == CALLED:
            ticket.called_at = ticket.called_at or shop_now()
            _tell(db, shop, ticket)
        elif entry.state == WAITING:
            # Не подъехал и снова ждёт: следующий вызов — снова сказать
            ticket.called_at = None
            ticket.told_at = None
    db.commit()

    fresh = db.query(LiveTicket).filter(
        LiveTicket.shop_id == shop.id, LiveTicket.local_id.is_(None),
        LiveTicket.state == WAITING, LiveTicket.left_by_client.is_(False)).all()
    left = db.query(LiveTicket).filter(
        LiveTicket.shop_id == shop.id, LiveTicket.left_by_client.is_(True),
        LiveTicket.local_id.isnot(None), LiveTicket.state.in_(ACTIVE)).all()
    return {
        'new': [{'server_id': t.id, 'license_plate': t.license_plate,
                 'phone': t.phone, 'wheel_diameter': t.wheel_diameter,
                 'wheels_assembled': t.wheels_assembled,
                 'joined_at': t.created_at.isoformat()} for t in fresh],
        'left': [t.id for t in left],
    }
