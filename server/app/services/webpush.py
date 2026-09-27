"""
Уведомления в браузере.

Второй канал рядом с телеграмом, для тех, кто телеграмом не
пользуется. Работает так: кабинет просит у браузера разрешение,
браузер выдаёт адрес своего сервера пуша и два ключа, мы их храним.
Дальше можно послать шифрованное сообщение — браузер разбудит наш
service worker и покажет уведомление, даже если кабинет закрыт.

**Где это действительно работает.** На Android и на компьютере — сразу
после «Разрешить». На айфоне — только если человек добавил кабинет на
домашний экран, и только с iOS 16.4. Удалил ярлык — подписка молча
умерла. Поэтому канал этот не вместо телеграма, а в дополнение:
телеграм доходит до всех, пуш добирает тех, у кого телеграма нет.

**Ключи VAPID** — одна пара на весь сервер. Ими мы подписываем каждое
уведомление, и по ним Google с Apple понимают, кто им пишет. Пара
живёт в переменных окружения: сменить её значит потерять все подписки,
поэтому install.sh генерирует её один раз.

**Что шифруется.** Само сообщение читает только браузер: сервер пуша
видит лишь размер. Ключи для шифрования дал браузер при подписке,
поэтому потерянную подписку восстановить нельзя — только подписаться
заново.
"""
import json
import logging

from app.config import settings
from app.models import PushSubscription
from app.utils import now as shop_now

log = logging.getLogger('tire_server')

# Сколько сервер пуша держит сообщение, если браузер офлайн. Сутки:
# напоминание о записи назавтра к тому времени уже ни к чему
TTL_SECONDS = 24 * 3600

# После какого числа неудач подряд подписку выбрасываем. Адрес может
# не отвечать временно, но десять раз подряд — это мёртвый браузер
MAX_FAILURES = 10


class PushError(Exception):
    """Не отправилось. `gone` — подписка мёртвая, её надо удалить."""

    def __init__(self, message, gone=False):
        super().__init__(message)
        self.gone = gone


def available():
    """Настроены ли ключи. Без них канала просто нет."""
    return bool(settings.PUSH_PUBLIC_KEY and settings.PUSH_PRIVATE_KEY)


def public_key():
    """Ключ, который отдаём браузеру: он подписывается именно на него."""
    return settings.PUSH_PUBLIC_KEY or None


def generate_keys():
    """
    Новая пара ключей.

    Формат задан здесь, в одном месте: браузер принимает открытый ключ
    только таким — несжатая точка кривой, base64 без хвостовых знаков.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())

    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint)
    raw_private = private.private_numbers().private_value.to_bytes(32, 'big')

    def short(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    return short(raw_public), short(raw_private)


# ----------------------------------------------------------------------
# Подписки
# ----------------------------------------------------------------------

def subscribe(db, client, endpoint, p256dh, auth, device=None):
    """
    Запомнить браузер.

    Один и тот же браузер подписывается заново после чистки кэша, и
    адрес при этом может не измениться — поэтому не заводим вторую
    строку, а обновляем ключи в старой.
    """
    if not (endpoint and p256dh and auth):
        raise PushError('Браузер не дал адрес для уведомлений')

    row = db.query(PushSubscription).filter(
        PushSubscription.client_id == client.id,
        PushSubscription.endpoint == endpoint).first()

    if row is None:
        row = PushSubscription(account_id=client.account_id,
                               client_id=client.id,
                               endpoint=endpoint)
        db.add(row)

    row.p256dh = p256dh
    row.auth = auth
    row.device = (device or '')[:120] or None
    row.failures = 0

    db.commit()
    db.refresh(row)
    return row


def subscriptions(db, client):
    return db.query(PushSubscription).filter(
        PushSubscription.client_id == client.id).all()


def connected(db, client):
    return bool(subscriptions(db, client))


def unsubscribe(db, client, endpoint=None):
    """
    Отписать. Без адреса — все устройства человека.

    Отписка с одного телефона не должна выключать уведомления на
    остальных: человек мог просто отдать старый телефон.
    """
    query = db.query(PushSubscription).filter(
        PushSubscription.client_id == client.id)

    if endpoint:
        query = query.filter(PushSubscription.endpoint == endpoint)

    count = 0
    for row in query.all():
        db.delete(row)
        count += 1

    db.commit()
    return count


def forget(db, row):
    """Убрать мёртвую подписку."""
    db.delete(row)
    db.commit()


# ----------------------------------------------------------------------
# Отправка
# ----------------------------------------------------------------------

def deliver(subscription, payload):
    """
    Единственное место, которое правда выходит в сеть.

    Отдельной функцией, чтобы в тестах её подменять: настоящий сервер
    пуша ответит только настоящему браузеру, а проверять надо всю
    остальную работу вокруг.
    """
    from pywebpush import WebPushException, webpush

    claims = {'sub': settings.PUSH_CONTACT or 'mailto:admin@localhost'}

    try:
        webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {'p256dh': subscription.p256dh,
                         'auth': subscription.auth},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.PUSH_PRIVATE_KEY,
            vapid_claims=claims,
            ttl=TTL_SECONDS)
    except WebPushException as e:
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        # 404 — такого адреса нет, 410 — был и кончился. И то и другое
        # значит, что браузера больше нет: держать подписку незачем
        raise PushError(str(e)[:255], gone=code in (404, 410))
    except Exception as e:
        raise PushError('Не удалось отправить уведомление: {0}'.format(e))


def send(db, client, title, body, url=None, tag=None):
    """
    Показать человеку уведомление на всех его устройствах.

    Достаточно одного дошедшего: у человека может быть живой телефон и
    давно забытый компьютер, и молчать из-за второго неправильно.
    Мёртвые подписки по ходу дела выбрасываем.
    """
    rows = subscriptions(db, client)
    if not rows:
        raise PushError('Человек не подписан на уведомления в браузере')

    payload = {'title': title, 'body': body}
    if url:
        payload['url'] = url
    if tag:
        payload['tag'] = tag

    delivered = 0
    last_error = None

    for row in rows:
        try:
            deliver(row, payload)
        except PushError as e:
            last_error = e
            if e.gone:
                log.info('Подписка №%s умерла, убираем', row.id)
                forget(db, row)
                continue

            row.failures = (row.failures or 0) + 1
            if row.failures >= MAX_FAILURES:
                log.info('Подписка №%s не отвечает %s раз, убираем',
                         row.id, row.failures)
                forget(db, row)
            continue

        row.last_ok_at = shop_now()
        row.failures = 0
        delivered += 1

    db.commit()

    if not delivered:
        raise PushError(str(last_error) if last_error
                        else 'Ни одно устройство не приняло уведомление')

    return delivered
