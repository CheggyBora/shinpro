"""
Телефон мастера: отсканировал QR — и шлёт фото прямо в наряд.

Компьютера в этой цепочке нет вовсе. Фотография рождается на телефоне,
и всякий способ «сначала перенести на компьютер» означает, что её не
отправят никогда: на потоке лишних шагов не делают.

Вход устроен так, чтобы им пользовались. Никаких логинов и паролей:
приёмщик показывает QR, мастер наводит камеру, телефон запоминает
пропуск и больше ничего не спрашивает.
"""
import os

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile, status)
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MasterDevice, OrderPhoto, Shop
from app.services import photos, shop_settings, tenancy
from app.utils import now as shop_now

router = APIRouter(prefix='/m', tags=['Фото из цеха'])

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'web')

# Ключи из QR живут в памяти: их мало, живут минуты, и ради них заводить
# таблицу незачем. Перезапустился сервер — приёмщик покажет новый код
_links = {}


def issue_link(shop_id):
    """Выдать одноразовый ключ для QR и убрать протухшие."""
    token = photos.make_link_token()
    now = shop_now()

    for old, (_, until) in list(_links.items()):
        if until < now:
            _links.pop(old, None)

    from datetime import timedelta

    _links[token] = (shop_id, now + timedelta(minutes=photos.LINK_MINUTES))
    return token


def _shop_by_link(db, token):
    pair = _links.get(token or '')
    if pair is None:
        return None

    shop_id, until = pair
    if until < shop_now():
        _links.pop(token, None)
        return None

    return db.query(Shop).filter(Shop.id == shop_id).first()


def _device(request: Request, db: Session):
    """Телефон, который уже заходил. Пропуск лежит у него в браузере."""
    token = request.headers.get('X-Master-Key') or ''
    device = photos.device_by_token(db, token)
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Телефон не подключён. Отсканируйте QR-код '
                                   'в цеху ещё раз')
    return device


# ----------------------------------------------------------------------
# Страница
# ----------------------------------------------------------------------

@router.get('', response_class=HTMLResponse, include_in_schema=False)
@router.get('/k/{link}', response_class=HTMLResponse, include_in_schema=False)
def page(link: str = ''):
    """
    Одна и та же страница: и по ссылке из QR, и по иконке с экрана.

    Она сама разберётся, помнит её телефон или видит впервые: ключ из
    адреса меняется на постоянный пропуск при первом открытии.

    Ключ лежит в отдельном «/k/», а не прямо в «/m/»: иначе адрес
    страницы совпал бы с адресами /m/cars и /m/photo, и телефон,
    спрашивая машины, получал бы в ответ саму страницу.
    """
    path = os.path.join(WEB_DIR, 'master.html')
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Страница не найдена')

    with open(path, encoding='utf-8') as file:
        return HTMLResponse(file.read())


# ----------------------------------------------------------------------
# Подключение телефона
# ----------------------------------------------------------------------

@router.post('/connect', summary='Запомнить телефон мастера')
def connect(payload: dict, db: Session = Depends(get_db)):
    """
    Обменять ключ из QR на постоянный пропуск.

    Ключ одноразовый и живёт минуты: он показан на экране в цеху, его
    видит кто угодно из стоящих рядом.
    """
    shop = _shop_by_link(db, (payload or {}).get('link'))
    if shop is None:
        raise HTTPException(
            status.HTTP_410_GONE,
            detail='Код устарел. Попросите приёмщика показать новый')

    _links.pop(payload.get('link'), None)

    device = photos.register_device(db, shop, (payload or {}).get('name'))
    return {
        'key': device.token,
        'shop': shop_settings.title(db, shop),
        'name': device.name,
    }


@router.get('/cars', summary='Машины, которые сейчас в цеху')
def cars(request: Request, db: Session = Depends(get_db)):
    device = _device(request, db)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()

    return {
        'shop': shop_settings.title(db, shop),
        'name': device.name,
        'cars': photos.cars_for(db, shop),
    }


# ----------------------------------------------------------------------
# Сам снимок
# ----------------------------------------------------------------------

@router.post('/photo', summary='Отправить снимок клиенту')
async def upload(request: Request,
                 file: UploadFile = File(...),
                 order_local_id: int = Form(None),
                 license_plate: str = Form(''),
                 comment: str = Form(''),
                 db: Session = Depends(get_db)):
    """
    Принять снимок и сразу отправить клиенту.

    Второго шага нет намеренно: мастер нажал — клиент получил. Любое
    «потом переслать» на потоке означает «никогда».

    Ответ честный. Не дошло — так и говорим: приёмщик увидит это в
    наряде и позвонит.
    """
    device = _device(request, db)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()

    data = await file.read()

    try:
        photo = photos.save(db, shop, data, file.content_type,
                            order_local_id=order_local_id,
                            plate=license_plate, comment=comment,
                            author=device.name)
    except photos.PhotoError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    try:
        channel = photos.tell_client(db, shop, photo)
    except Exception as e:
        return {'id': photo.id, 'sent': False, 'reason': str(e)}

    if channel is None:
        return {'id': photo.id, 'sent': False,
                'reason': photo.last_error or 'Клиенту сообщить нечем'}

    return {'id': photo.id, 'sent': True, 'channel': channel}


@router.get('/photo/{photo_id}', include_in_schema=False)
def show(photo_id: int, key: str = '', db: Session = Depends(get_db)):
    """
    Сам файл. Открывается по ключу телефона или ключу обмена: смотрят
    его мастер со своего телефона и приёмщик из программы цеха.
    """
    photo = db.query(OrderPhoto).filter(OrderPhoto.id == photo_id).first()
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Фото не найдено')

    device = db.query(MasterDevice).filter(
        MasterDevice.token == key,
        MasterDevice.shop_id == photo.shop_id).first()

    # Либо телефон этой же точки, либо сама программа цеха своим
    # ключом обмена: приёмщик смотрит фото из наряда
    by_sync = tenancy.shop_by_sync_key(db, key)
    allowed = (device is not None
               or (by_sync is not None and by_sync.id == photo.shop_id))

    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail='Нельзя')

    path = photos.full_path(photo)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Файл не найден')

    return FileResponse(path, media_type='image/jpeg',
                        headers={'Cache-Control': 'private, max-age=86400'})
