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
from app.models.photo import PHOTO, COVER
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


def register_device(db, shop, name=None):
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
         comment=None, author=None, kind=PHOTO):
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
        client_id=None)

    photo.client_id = _client_for(db, shop, photo)

    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


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

    try:
        if channel == BY_TELEGRAM:
            with open(full_path(photo), 'rb') as file:
                telegram.send_photo(account, client.telegram_chat_id,
                                    file.read(), caption)
        else:
            webpush.send(db, client, name,
                         _short(photo) or 'Прислали фото из шиномонтажа',
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


def _short(photo):
    if photo.comment:
        return photo.comment
    if photo.license_plate:
        return f'Фото по машине {photo.license_plate}'
    return ''


def _caption(shop_name, photo):
    lines = [f'<b>{shop_name}</b>']
    if photo.license_plate:
        lines.append(photo.license_plate)
    if photo.comment:
        lines.append(photo.comment)
    else:
        lines.append('Фото из цеха.')
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

    from app.models import Arrival

    edge = shop_now() - timedelta(days=30 * months)
    rows = db.query(OrderPhoto).filter(OrderPhoto.created_at < edge).all()

    # Машины с телефона ссылаются на свой снимок: без них строку снимка
    # не убрать. Сами они к этому времени давно разобраны
    ids = [photo.id for photo in rows]
    if ids:
        db.query(Arrival).filter(Arrival.photo_id.in_(ids)).delete(
            synchronize_session=False)
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
