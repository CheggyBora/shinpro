"""
Фото из цеха: принять с телефона мастера и показать клиенту.

Путь намеренно короткий. Мастер снял — клиент получил. Ни одного шага
«потом переслать»: на потоке любой такой шаг означает «никогда», и
именно поэтому фотографии дефектов до клиента не доходили никогда.

Файл лежит на диске, в базе только путь. Складывать картинки в базу —
значит получить базу, которую не скопировать и не восстановить за
разумное время.
"""
import logging
import os
import secrets
from datetime import timedelta

from app.config import settings
from app.models.photo import PHOTO, COVER, MEDIA_PHOTO, MEDIA_VIDEO
from app.models import (MasterDevice, Notice, OpenOrder, OrderPhoto,
                        KIND_READY, BY_TELEGRAM, BY_PUSH, SENT, SKIPPED,
                        FAILED)
from app.services import notices, telegram, webpush
from app.utils import now as shop_now, normalize_plate

log = logging.getLogger('tire_server')

# Что принимаем. Расширение проверяем по тому, что прислал браузер:
# телефон отдаёт jpeg, но у кого-то это будет png со скриншота
KINDS = {
    'image/jpeg': '.jpg',
    'image/jpg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
}

# Видео с телефона мастера. MediaRecorder на айфоне пишет mp4, на
# андроиде — mp4 или webm; снятое камерой через выбор файла — mov
VIDEO_KINDS = {
    'video/mp4': '.mp4',
    'video/quicktime': '.mov',
    'video/webm': '.webm',
}

# Сколько живёт ссылка из QR-кода. Минуты, а не дни: код показан на
# экране в цеху, его видит кто угодно из стоящих рядом, и пропуск в
# чужой цех на сутки — это не то, что стоит раздавать
LINK_MINUTES = 15


class PhotoError(Exception):
    """Понятная причина, почему фото не приняли."""


# ----------------------------------------------------------------------
# Телефоны мастеров
# ----------------------------------------------------------------------

def make_link_token():
    """Одноразовый ключ для QR. Короткий: его читает камера, а не человек."""
    return secrets.token_urlsafe(9)


def register_device(db, shop, name=None, link_sig=None):
    """
    Запомнить телефон, который только что отсканировал QR.

    Отдаём ему постоянный пропуск, чтобы сканировать больше не
    пришлось. Пропуск — не пароль от денег: им можно только прислать
    фото в один цех, и отзывается он одной кнопкой.
    """
    device = MasterDevice(
        shop_id=shop.id,
        token=secrets.token_urlsafe(32),
        name=(name or '').strip()[:80] or None,
        link_sig=link_sig,
        last_seen_at=shop_now())
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def device_by_token(db, token):
    if not token:
        return None

    device = db.query(MasterDevice).filter(
        MasterDevice.token == token,
        MasterDevice.is_active.is_(True)).first()

    if device is not None:
        device.last_seen_at = shop_now()
        db.commit()

    return device


def cars_for(db, shop):
    """Машины, которые сейчас в цеху. Сначала те, что на постах."""
    rows = db.query(OpenOrder).filter(
        OpenOrder.shop_id == shop.id).order_by(
        OpenOrder.state.desc(), OpenOrder.local_id).all()

    return [{
        'order_local_id': row.local_id,
        'license_plate': row.license_plate,
        'state': row.state,
    } for row in rows]


# ----------------------------------------------------------------------
# Приём файла
# ----------------------------------------------------------------------

def save(db, shop, data, content_type, order_local_id=None, plate=None,
         comment=None, author=None, kind=PHOTO, employee_local_id=None):
    """
    Положить снимок на диск и завести строку.

    Клиента ищем по наряду: цех прислал, какие машины в работе, а по
    машине в базе есть владелец. Не нашли — фото всё равно сохраняем:
    оно пригодится приёмщику, даже если отправить его некому.
    """
    suffix = KINDS.get((content_type or '').lower())
    if suffix is None:
        raise PhotoError('Это не фотография. Нужен снимок с камеры')

    if not data:
        raise PhotoError('Пустой файл')

    if len(data) > settings.PHOTO_MAX_BYTES:
        raise PhotoError('Снимок слишком большой. Попробуйте ещё раз')

    folder = os.path.join(settings.PHOTO_DIR, str(shop.id),
                          shop_now().strftime('%Y-%m'))
    os.makedirs(folder, exist_ok=True)

    name = f'{secrets.token_hex(8)}{suffix}'
    path = os.path.join(folder, name)
    with open(path, 'wb') as file:
        file.write(data)

    photo = OrderPhoto(
        shop_id=shop.id,
        order_local_id=order_local_id,
        license_plate=normalize_plate(plate) or None,
        path=os.path.relpath(path, settings.PHOTO_DIR).replace(os.sep, '/'),
        comment=(comment or '').strip()[:1000] or None,
        author=(author or '').strip()[:80] or None,
        kind=COVER if kind == COVER else PHOTO,
        client_id=None,
        media=MEDIA_PHOTO,
        content_type=KINDS.get((content_type or '').lower()) and (content_type or '').lower(),
        size=len(data),
        employee_local_id=employee_local_id)

    photo.client_id = _client_for(db, shop, photo)

    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def video_kind(content_type):
    """«video/mp4;codecs=avc1» -> «video/mp4»; не видео — None."""
    kind = (content_type or '').split(';', 1)[0].strip().lower()
    return kind if kind in VIDEO_KINDS else None


def save_video(db, shop, temp_path, content_type, order_local_id=None,
               plate=None, comment=None, author=None, employee_local_id=None):
    """
    Положить собранное из кусков видео на место и завести строку.
    Файл переносится, а не копируется: он бывает в сотню мегабайт.
    """
    kind = video_kind(content_type)
    if kind is None:
        raise PhotoError('Это не видео')
    size = os.path.getsize(temp_path)
    if not size:
        raise PhotoError('Пустой файл')

    folder = os.path.join(settings.PHOTO_DIR, str(shop.id),
                          shop_now().strftime('%Y-%m'))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{secrets.token_hex(8)}{VIDEO_KINDS[kind]}')
    os.replace(temp_path, path)

    photo = OrderPhoto(
        shop_id=shop.id,
        order_local_id=order_local_id,
        license_plate=normalize_plate(plate) or None,
        path=os.path.relpath(path, settings.PHOTO_DIR).replace(os.sep, '/'),
        comment=(comment or '').strip()[:1000] or None,
        author=(author or '').strip()[:80] or None,
        kind=PHOTO, media=MEDIA_VIDEO, content_type=kind, size=size,
        employee_local_id=employee_local_id, client_id=None)
    photo.client_id = _client_for(db, shop, photo)
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def media_type(photo):
    """Что отдать браузеру в Content-Type."""
    if photo.content_type:
        return photo.content_type
    return 'video/mp4' if photo.media == MEDIA_VIDEO else 'image/jpeg'


def client_link(db, account, photo):
    """
    Прямая ссылка на файл для клиента — подписанная, без входа. Нужна,
    когда видео в телеграм файлом не пролезает. None — адреса кабинета
    сервер не знает (тестовый сервер без доменов).
    """
    from app.models.account import ROLE_LK
    from app.security import photo_key
    from app.services import onboarding

    base = onboarding.addresses(db, account).get(ROLE_LK)
    if not base or photo.client_id is None:
        return None
    return f'{base}/history/photo/{photo.id}?key={photo_key(photo.id, photo.client_id)}'


def _client_for(db, shop, photo):
    """Чьё это фото. Ищем по машине: номер есть, владелец у машины тоже."""
    from app.models import Car

    plate = photo.license_plate
    if not plate:
        return None

    car = db.query(Car).filter(
        Car.license_plate == plate,
        Car.account_id == shop.account_id).first()

    return car.client_id if car is not None else None


def full_path(photo):
    return os.path.join(settings.PHOTO_DIR, photo.path.replace('/', os.sep))


# ----------------------------------------------------------------------
# Сказать клиенту
# ----------------------------------------------------------------------

def tell_client(db, shop, photo):
    """
    Отправить снимок клиенту. Возвращает название канала или None.

    В Телеграм уходит сама картинка: человек видит её, не выходя из
    переписки. В браузер картинку не отправить, поэтому туда идёт
    уведомление, а снимок ждёт в кабинете.

    Молчать о неудаче нельзя: приёмщик должен знать, что клиенту
    придётся звонить.
    """
    from app.models import Account, Client
    from app.services import shop_settings

    # Обложка — снимок машины для цеха, а не «фото от мастера»: клиенту
    # она не уходит никогда (docs/order_photo.md)
    if photo.kind == COVER:
        return None

    if photo.client_id is None:
        photo.last_error = 'Машина ни за кем не записана'
        db.commit()
        return None

    client = db.query(Client).filter(Client.id == photo.client_id).first()
    account = db.query(Account).filter(
        Account.id == shop.account_id).first()

    channel = notices.channel_for(db, client, account)
    if channel is None:
        photo.last_error = 'Клиент не подключил ни Телеграм, ни кабинет'
        db.commit()
        return None

    name = shop_settings.title(db, shop)
    caption = _caption(name, photo)

    notice = Notice(
        account_id=client.account_id,
        client_id=client.id,
        kind=KIND_READY,
        text=caption,
        about='photo',
        about_id=photo.id,
        send_at=shop_now(),
        state=SENT,
        channel=channel,
        sent_at=shop_now(),
        attempts=1)

    video = photo.media == MEDIA_VIDEO
    try:
        if channel == BY_TELEGRAM and video:
            _video_to_telegram(db, account, client, photo, caption)
        elif channel == BY_TELEGRAM:
            with open(full_path(photo), 'rb') as file:
                telegram.send_photo(account, client.telegram_chat_id,
                                    file.read(), caption)
        else:
            webpush.send(db, client, name,
                         _short(photo) or ('Прислали видео из шиномонтажа' if video
                                           else 'Прислали фото из шиномонтажа'),
                         url='/z', tag=f'photo-{photo.id}')
    except Exception as e:
        notice.state = FAILED
        notice.last_error = str(e)[:255]
        notice.sent_at = None
        db.add(notice)

        photo.last_error = str(e)[:255]
        db.commit()
        log.warning('Фото №%s не ушло (%s): %s', photo.id, channel, e)
        raise

    db.add(notice)
    photo.sent_at = shop_now()
    photo.channel = channel
    photo.last_error = None
    db.commit()
    return channel


def _video_to_telegram(db, account, client, photo, caption):
    """
    Видео — файлом, если телеграм его примет (mp4 или mov до 50 МБ):
    тогда оно играет прямо в переписке. Иначе — ссылкой на файл.
    """
    if (photo.size or 0) <= telegram.VIDEO_LIMIT and photo.content_type in (
            'video/mp4', 'video/quicktime'):
        with open(full_path(photo), 'rb') as file:
            telegram.send_video(account, client.telegram_chat_id, file.read(), caption)
        return

    link = client_link(db, account, photo)
    if link is None:
        raise telegram.TelegramError('Видео не пролезает в телеграм, а ссылки на кабинет нет')
    telegram.send_message(account, client.telegram_chat_id, caption,
                          buttons=[('Смотреть видео', link)])


def _short(photo):
    if photo.comment:
        return photo.comment
    if photo.license_plate:
        return f'Фото по машине {photo.license_plate}'
    return ''


def _caption(shop_name, photo):
    from html import escape

    lines = [f'<b>{escape(shop_name or "")}</b>']
    if photo.license_plate:
        lines.append(escape(photo.license_plate))
    if photo.author:
        what = 'видео' if photo.media == MEDIA_VIDEO else 'фото'
        lines.append(f'Мастер {escape(photo.author)} прислал {what}.')
    if photo.comment:
        lines.append(escape(photo.comment))
    elif not photo.author:
        lines.append('Видео из цеха.' if photo.media == MEDIA_VIDEO else 'Фото из цеха.')
    return '\n'.join(lines)


# ----------------------------------------------------------------------
# Уборка
# ----------------------------------------------------------------------

def drop_old(db, months=None):
    """
    Убрать снимки старше срока. Файл и строку вместе.

    Фото нужно, пока о нём спорят. Через год о прошлогодней грыже не
    спорит никто, а место оно занимает.
    """
    months = months or settings.PHOTO_KEEP_MONTHS
    if months <= 0:
        return 0

    edge = shop_now() - timedelta(days=30 * months)
    rows = db.query(OrderPhoto).filter(OrderPhoto.created_at < edge).all()
    return _drop(db, rows)


def drop_old_videos(db, days=None):
    """Видео — две недели (решение владельца 27.10.2026): оно тяжёлое."""
    days = settings.VIDEO_KEEP_DAYS if days is None else days
    if days <= 0:
        return 0
    edge = shop_now() - timedelta(days=days)
    rows = db.query(OrderPhoto).filter(OrderPhoto.media == MEDIA_VIDEO,
                                       OrderPhoto.created_at < edge).all()
    return _drop(db, rows)


def _drop(db, rows):
    from app.models import Arrival, WorkOffer

    # Машины с телефона ссылаются на свой снимок: без них строку снимка
    # не убрать. Сами они к этому времени давно разобраны
    ids = [photo.id for photo in rows]
    if ids:
        db.query(Arrival).filter(Arrival.photo_id.in_(ids)).delete(
            synchronize_session=False)
        # Предложение мастера остаётся — без снимка, но с ценой и ответом
        db.query(WorkOffer).filter(WorkOffer.photo_id.in_(ids)).update(
            {WorkOffer.photo_id: None}, synchronize_session=False)
        db.flush()

    gone = 0
    for photo in rows:
        try:
            os.remove(full_path(photo))
        except OSError:
            pass        # файла уже нет — строку всё равно уберём
        db.delete(photo)
        gone += 1

    db.commit()
    return gone
