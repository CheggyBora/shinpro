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
from fastapi import Response
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MasterDevice, OrderPhoto, Shop
from app.services import arrivals, photos, plates, shop_settings, tenancy
from app.utils import now as shop_now

router = APIRouter(prefix='/m', tags=['Фото из цеха'])

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'web')

# Ключ из QR — подписанная строка «точка.срок.подпись», а не запись в
# памяти: процессов у сервера два, и ключ, выданный одним, второй не
# узнавал — подключение по QR проходило через раз (ревью 26.10.2026)


def _link_signature(shop_id, until):
    import hashlib
    import hmac

    from app.config import settings
    message = f'master-link:{shop_id}:{until}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()[:32]


def issue_link(shop_id):
    """Выдать ключ для QR: действует LINK_MINUTES минут."""
    import time
    until = int(time.time()) + photos.LINK_MINUTES * 60
    return f'{shop_id}.{until}.{_link_signature(shop_id, until)}'


def _shop_by_link(db, token):
    import hmac
    import time
    try:
        shop_id, until, signature = str(token or '').split('.')
        shop_id, until = int(shop_id), int(until)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, _link_signature(shop_id, until)):
        return None
    if until < time.time():
        return None
    return db.query(Shop).filter(Shop.id == shop_id).first()


# Пропуск мастера живёт в куке, которую ставит сам сервер.
#
# Сначала он лежал в данных страницы, и на айфоне это не работало:
# Safari стирает данные страницы, если её не открывали около недели.
# Мастер, который в межсезонье неделю не слал фото, оказывался снова
# неподключённым и шёл к приёмщику за QR. Куку, поставленную сервером,
# эта чистка не трогает.
#
# Год, и продлеваем при каждом заходе: пока мастер пользуется
# страницей, пропуск не кончается никогда
MASTER_COOKIE = 'tire_master'
MASTER_COOKIE_DAYS = 365


def _token_of(request: Request):
    """Пропуск из куки, а для старых страниц — из заголовка."""
    return (request.cookies.get(MASTER_COOKIE)
            or request.headers.get('X-Master-Key') or '')


def _is_https(request: Request):
    """
    Пришли ли по https. Сервер стоит за nginx, и до него запрос доходит
    уже по http — смотрим, что nginx сказал о настоящем адресе.
    """
    forwarded = (request.headers.get('x-forwarded-proto') or '').lower()
    return forwarded == 'https' or request.url.scheme == 'https'


def _keep(response: Response, token: str, request: Request):
    """Поставить или продлить куку с пропуском."""
    response.set_cookie(
        MASTER_COOKIE, token,
        max_age=MASTER_COOKIE_DAYS * 24 * 3600,
        httponly=True,        # страница его не читает — и чужой скрипт тоже
        # На боевом — только по https, чтобы пропуск не ушёл открытым
        # текстом. На тестовом без https тоже должно работать
        secure=_is_https(request),
        samesite='lax',
        path='/m')


def _device(request: Request, db: Session, response: Response = None):
    """Телефон, который уже заходил."""
    token = _token_of(request)
    device = photos.device_by_token(db, token)
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Телефон не подключён. Отсканируйте QR-код '
                                   'в цеху ещё раз')

    # Заходит — продлеваем. Иначе через год пропуск кончился бы у
    # того, кто пользуется страницей каждый день
    if response is not None:
        _keep(response, token, request)

    return device


# ----------------------------------------------------------------------
# Страница
# ----------------------------------------------------------------------

@router.get('/manifest.webmanifest', include_in_schema=False)
def manifest():
    """
    Ярлык «Фото в наряд» для экрана телефона мастера.

    Открывается **в браузере, а не отдельным окном** — намеренно. На
    айфоне ярлык-окно хранит данные отдельно от Safari, и телефон,
    подключённый по QR в Safari, в таком окне оказался бы снова
    неподключённым. А QR из ярлыка не отсканировать: камера открывает
    ссылку в Safari. Получился бы круг, из которого мастер не выйдет.
    """
    from fastapi.responses import JSONResponse

    return JSONResponse({
        'name': 'Кабинет мастера',
        'short_name': 'Мастер',
        'description': 'Мои машины, фото и видео клиенту, заработок',
        'start_url': '/m',
        'scope': '/m',
        'display': 'browser',
        'background_color': '#f1f5f9',
        'theme_color': '#2563eb',
        'lang': 'ru',
        'icons': [
            {'src': '/z/icon.svg', 'sizes': 'any', 'type': 'image/svg+xml'},
        ],
    }, headers={'Cache-Control': 'public, max-age=3600'})


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
def connect(payload: dict, request: Request, response: Response,
            db: Session = Depends(get_db)):
    """
    Обменять ключ из QR на постоянный пропуск.

    Ключ одноразовый и живёт минуты: он показан на экране в цеху, его
    видит кто угодно из стоящих рядом.
    """
    link = str((payload or {}).get('link') or '')
    shop = _shop_by_link(db, link)
    signature = link.rsplit('.', 1)[-1]
    used = shop is not None and db.query(MasterDevice).filter(
        MasterDevice.link_sig == signature).first() is not None
    if shop is None or used:
        raise HTTPException(
            status.HTTP_410_GONE,
            detail='Код устарел. Попросите приёмщика показать новый')

    from sqlalchemy.exc import IntegrityError
    try:
        device = photos.register_device(db, shop, (payload or {}).get('name'),
                                        link_sig=signature)
    except IntegrityError:
        # Тот же код в ту же секунду с двух телефонов — второй не пускаем
        db.rollback()
        raise HTTPException(status.HTTP_410_GONE,
                            detail='Код устарел. Попросите приёмщика показать новый')
    _keep(response, device.token, request)

    return {
        'key': device.token,
        'shop': shop_settings.title(db, shop),
        'name': device.name,
    }


@router.get('/cars', summary='Машины, которые сейчас в цеху')
def cars(request: Request, response: Response,
         db: Session = Depends(get_db)):
    from app.services import master

    device = _device(request, db, response)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()

    return {
        'shop': shop_settings.title(db, shop),
        'name': master.author_of(db, device),
        # Свои машины — сверху, с составом наряда (кабинет мастера)
        'cars': master.cars(db, device, shop),
        # «Новая машина» на телефоне — только если наряд по фото включён
        # хоть для одного направления (docs/order_photo.md)
        'arrival_directions': shop_settings.arrival_photo_directions(db, shop),
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
    from app.services import master

    device = _device(request, db)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()

    data = await file.read()
    person = master.employee_of(db, device)

    try:
        photo = photos.save(db, shop, data, file.content_type,
                            order_local_id=order_local_id,
                            plate=license_plate, comment=comment,
                            author=master.author_of(db, device),
                            employee_local_id=person.local_id if person else None)
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


# ----------------------------------------------------------------------
# Новая машина: снимок при приезде → номер → наряд в цеху
# ----------------------------------------------------------------------

@router.post('/arrival/recognize', summary='Снимок машины: распознать номер')
async def arrival_recognize(request: Request, response: Response,
                            photo: UploadFile = File(...),
                            db: Session = Depends(get_db)):
    """
    Принять снимок машины и прочитать номер (docs/order_photo.md).

    Снимок сохраняется сразу, как обложка без наряда: номер может не
    прочитаться, а фото всё равно станет обложкой. Распознавание — на
    этом сервере, в отдельном потоке: сервер в это время отвечает
    остальным. Не прочиталось — plate пустой, номер впишут руками.
    """
    from fastapi.concurrency import run_in_threadpool

    device = _device(request, db, response)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()

    if not shop_settings.arrival_photo_directions(db, shop):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Наряд по фото выключен в программе цеха')

    data = await photo.read()
    try:
        saved = photos.save(db, shop, data, photo.content_type,
                            author=device.name, kind=photos.COVER)
    except photos.PhotoError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    plate, confidence = await run_in_threadpool(plates.recognize, data)
    if plate:
        # Регион не прочитался — дополняем по базе, если машина одна
        plate = arrivals.complete_plate(db, shop, plate)
        saved.license_plate = plate
        saved.client_id = photos._client_for(db, shop, saved)
        db.commit()

    found = arrivals.hints(db, shop, plate)
    return {
        'photo_id': saved.id,
        'plate': plate or None,
        # Полный ли номер: без региона телефон просит его дописать.
        # Номер другой страны полный как есть
        'plate_complete': bool(plate) and (plates.is_valid(plate)
                                           or bool(plates.foreign_country(plate))),
        # Не российский: BY, KZ… или other — пусть проверят глазами
        'country': plates.foreign_country(plate),
        'confidence': round(confidence or 0.0, 3),
        'known': found['known'],
        'appointment': found['appointment'],
        'wash_enabled': shop_settings.wash_on(db, shop),
        # Для каких направлений включён наряд по фото: по ним телефон
        # рисует выбор «Шиномонтаж / Мойка / Оба». Одно — выбора нет
        'directions_allowed': shop_settings.arrival_photo_directions(db, shop),
    }


@router.post('/arrival/hints', summary='Подсказки по номеру, вписанному руками')
def arrival_hints(payload: dict, request: Request, response: Response,
                  db: Session = Depends(get_db)):
    """«Есть в базе» и «записан на …» для номера, который поправили."""
    device = _device(request, db, response)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()
    plate = plates.normalize((payload or {}).get('plate'))
    return arrivals.hints(db, shop, plate)


@router.post('/arrival', summary='Подать машину в цех')
def arrival_create(payload: dict, request: Request, response: Response,
                   db: Session = Depends(get_db)):
    """
    {"photo_id", "plate", "directions"} → {"ok": true, "arrival_id"}.

    Наряд создаёт приёмщик: цех заберёт машину при ближайшем обмене и
    откроет окно создания наряда с номером и снимком.
    """
    device = _device(request, db, response)
    shop = db.query(Shop).filter(Shop.id == device.shop_id).first()
    payload = payload or {}

    photo_id = payload.get('photo_id')
    try:
        photo_id = int(photo_id) if photo_id not in (None, '') else None
    except (TypeError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Снимок не найден. Переснимите машину')

    try:
        arrival = arrivals.create(db, shop, photo_id, payload.get('plate'),
                                  payload.get('directions'))
    except arrivals.ArrivalError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {'ok': True, 'arrival_id': arrival.id}


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
        MasterDevice.shop_id == photo.shop_id,
        MasterDevice.is_active.is_(True)).first()

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
