"""
Кабинет мастера: вход по ПИН, наряд, видео, «Начал» / «Готово»,
предложение работы клиенту, заработок (app/services/master.py).

Пропуск телефона — тот же, что у фото из цеха (app/api/photos.py):
кука после QR. Поверх него мастер входит своим именем и ПИН.

Здесь же страница, по которой клиент отвечает на предложение мастера:
/o/<ссылка> — без входа, ссылку получает только он.
"""
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.photos import WEB_DIR, _device
from app.database import get_db
from app.models import Shop
from app.models.photo import EVENT_DONE, EVENT_START
from app.services import master, photos
from app.services.master import MasterError

router = APIRouter(prefix='/m', tags=['Кабинет мастера'])
offer_router = APIRouter(tags=['Предложение мастера клиенту'])


def _shop(db, device):
    return db.query(Shop).filter(Shop.id == device.shop_id).first()


def _bad(e):
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


class LoginIn(BaseModel):
    employee_local_id: int
    pin: str


class VideoStartIn(BaseModel):
    order_local_id: Optional[int] = None
    license_plate: str = ''
    comment: str = ''
    content_type: str
    size: int


class OfferIn(BaseModel):
    order_local_id: int
    services: List[int]
    comment: str = ''
    photo_id: Optional[int] = None


@router.get('/me', summary='Кто держит телефон и кто есть в точке')
def me(request: Request, response: Response, db: Session = Depends(get_db)):
    device = _device(request, db, response)
    return master.me(db, device, _shop(db, device))


@router.post('/login', summary='Войти своим именем и ПИН')
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        master.login(db, device, payload.employee_local_id, payload.pin)
    except MasterError as e:
        raise _bad(e)
    return master.me(db, device, _shop(db, device))


@router.post('/logout', summary='Выйти — телефон останется подключённым')
def logout(request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    master.logout(db, device)
    return {'ok': True}


@router.get('/order/{local_id}', summary='Наряд: клиент, отправленное, прайс')
def order(local_id: int, request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        return master.order(db, device, _shop(db, device), local_id)
    except MasterError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post('/order/{local_id}/start', summary='Мастер начал работу')
def start(local_id: int, request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        return master.press(db, device, _shop(db, device), local_id, EVENT_START)
    except MasterError as e:
        raise _bad(e)


@router.post('/order/{local_id}/done', summary='Готово — клиенту сразу')
def done(local_id: int, request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        return master.press(db, device, _shop(db, device), local_id, EVENT_DONE)
    except MasterError as e:
        raise _bad(e)


# --- Видео -------------------------------------------------------------

@router.post('/video/start', summary='Начать отправку видео')
def video_start(payload: VideoStartIn, request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        upload = master.start_video(db, device, _shop(db, device), payload.order_local_id,
                                    payload.license_plate, payload.comment,
                                    payload.content_type, payload.size)
    except MasterError as e:
        raise _bad(e)
    return {'upload': upload, 'part_bytes': master.VIDEO_PART_BYTES}


@router.post('/video/part', summary='Кусок видео')
async def video_part(request: Request, upload: str = Query(...),
                     offset: int = Query(..., ge=0), db: Session = Depends(get_db)):
    device = _device(request, db)
    data = await request.body()
    try:
        return {'size': master.add_video_part(device, upload, offset, data)}
    except MasterError as e:
        raise _bad(e)


@router.post('/video/finish', summary='Видео дошло — отправить клиенту')
def video_finish(request: Request, upload: str = Query(...), db: Session = Depends(get_db)):
    device = _device(request, db)
    shop = _shop(db, device)
    try:
        photo = master.finish_video(db, device, shop, upload)
    except MasterError as e:
        raise _bad(e)

    try:
        channel = photos.tell_client(db, shop, photo)
    except Exception as e:
        return {'id': photo.id, 'sent': False, 'reason': str(e)}
    if channel is None:
        return {'id': photo.id, 'sent': False,
                'reason': photo.last_error or 'Клиенту сообщить нечем'}
    return {'id': photo.id, 'sent': True, 'channel': channel}


# --- Предложение работы --------------------------------------------------

@router.post('/offer', summary='Предложить клиенту работу на согласование')
def offer(payload: OfferIn, request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        row = master.create_offer(db, device, _shop(db, device), payload.order_local_id,
                                  payload.services, payload.comment, payload.photo_id)
    except MasterError as e:
        raise _bad(e)
    return master.offer_dict(db, row)


# --- Заработок -----------------------------------------------------------

@router.get('/earnings', summary='Мой заработок')
def earnings(request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    try:
        return master.earnings(db, device, _shop(db, device))
    except MasterError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(e))


# ----------------------------------------------------------------------
# Клиент отвечает на предложение
# ----------------------------------------------------------------------

class AnswerIn(BaseModel):
    answer: str


def _offer(db, token):
    row = master.offer_by_token(db, token)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail='Предложение не найдено — ссылка устарела')
    return row


@offer_router.get('/o/{token}', response_class=HTMLResponse, include_in_schema=False)
def offer_page(token: str):
    with open(os.path.join(WEB_DIR, 'offer.html'), encoding='utf-8') as page:
        return HTMLResponse(page.read(), headers={'Cache-Control': 'no-cache',
                                                  'Referrer-Policy': 'no-referrer'})


@offer_router.get('/public/offer/{token}', include_in_schema=False)
def offer_data(token: str, db: Session = Depends(get_db)):
    return master.offer_public(db, _offer(db, token))


@offer_router.post('/public/offer/{token}', include_in_schema=False)
def offer_answer(token: str, payload: AnswerIn, db: Session = Depends(get_db)):
    row = _offer(db, token)
    try:
        changed = master.answer_offer(db, row, payload.answer)
    except MasterError as e:
        raise _bad(e)
    answer = master.offer_public(db, row)
    answer['changed'] = changed
    return answer
