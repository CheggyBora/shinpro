"""
Онлайн-очередь: встать из дома и приехать к своему времени.

Клиент занимает место и говорит, через сколько будет. Порядок
считается по времени прибытия: кто приедет раньше, того и обслужат
раньше. Иначе житель соседнего дома ждал бы того, кто едет час, а
пост всё это время стоял бы пустым.

Приёмщик ведёт очередь со своей стороны: видит, кто уже на месте, а
кто ещё едет, зовёт на пост и отмечает, когда машину взяли в работу.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, QueueTicket, Shop, OPEN_STATES
from app.security import current_client
from app.services import queue_service, shop_settings, tenancy
from app.utils import format_phone, now as shop_now

router = APIRouter(prefix='/queue', tags=['Онлайн-очередь'])


class JoinIn(BaseModel):
    minutes_away: int = 0
    license_plate: Optional[str] = None
    wheels_assembled: Optional[bool] = None
    comment: Optional[str] = None
    shop: Optional[str] = None


def _shop(db, client, wanted=None):
    try:
        shop = tenancy.shop_for(db, client.account_id, wanted)
    except tenancy.ShopNeeded as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))

    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Точка не найдена')

    return shop


def _mine(db, shop, client):
    return db.query(QueueTicket).filter(
        QueueTicket.shop_id == shop.id,
        QueueTicket.client_id == client.id,
        QueueTicket.state.in_(OPEN_STATES)).first()


def _answer(db, shop, ticket, now=None):
    """
    Что показать человеку: какой он по счёту и когда примерно.

    Время называем честно — «примерно»: это очередь, а не запись, и
    обещать минуту в минуту здесь нельзя.
    """
    now = now or shop_now()
    times = queue_service.forecast(db, shop, now)

    return {
        'id': ticket.id,
        'state': ticket.state,
        'place': queue_service.place_of(db, shop, ticket, now),
        'about_at': times.get(ticket.id),
        'arrived': ticket.is_here,
        'eta_at': ticket.eta_at,
        'license_plate': ticket.license_plate,
        'ahead': max(0, (queue_service.place_of(db, shop, ticket, now) or 1) - 1),
    }


@router.get('/online', summary='Работает ли онлайн-очередь')
def online(shop: Optional[str] = Query(None),
           client: Client = Depends(current_client),
           db: Session = Depends(get_db)):
    """
    Можно ли вообще вставать в очередь и что там сейчас.

    Если постов под очередь не выделено, кнопки быть не должно: лучше
    её не показывать вовсе, чем показать и отказать по нажатию.
    """
    chosen = _shop(db, client, shop)
    now = shop_now()

    mine = _mine(db, chosen, client)
    waiting = queue_service.line(db, chosen, now)

    return {
        'enabled': queue_service.enabled(db, chosen),
        'posts': queue_service.posts_for(db, chosen),
        'people': len(waiting),
        'here': sum(1 for row in waiting if row.is_here),
        'post_busy_until': queue_service.busy_until(db, chosen, now),
        'mine': _answer(db, chosen, mine, now) if mine else None,
    }


@router.post('/join', summary='Встать в очередь')
def join(payload: JoinIn, client: Client = Depends(current_client),
         db: Session = Depends(get_db)):
    chosen = _shop(db, client, payload.shop)

    try:
        ticket = queue_service.join(
            db, chosen, client, payload.minutes_away,
            plate=payload.license_plate,
            wheels_assembled=payload.wheels_assembled,
            comment=payload.comment)
    except queue_service.QueueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return _answer(db, chosen, ticket)


@router.post('/arrived', summary='Я на месте')
def arrived(shop: Optional[str] = Query(None),
            client: Client = Depends(current_client),
            db: Session = Depends(get_db)):
    """
    Отметиться у ворот.

    Без этого звать человека нельзя: пост простоит, пока он едет.
    """
    chosen = _shop(db, client, shop)
    ticket = _mine(db, chosen, client)

    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Вас нет в очереди')

    queue_service.arrived(db, chosen, ticket)
    return _answer(db, chosen, ticket)


@router.post('/leave', summary='Уйти из очереди')
def leave(shop: Optional[str] = Query(None),
          client: Client = Depends(current_client),
          db: Session = Depends(get_db)):
    chosen = _shop(db, client, shop)
    ticket = _mine(db, chosen, client)

    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Вас нет в очереди')

    queue_service.leave(db, ticket)
    return {'ok': True}
