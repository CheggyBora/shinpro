"""
Сообщения в Telegram из сервера — для своих, а не для клиентов.

Зачем: клиент записался и попросил достать свой комплект со склада,
или пора сводки по задачам владельцу. Кладовщик должен узнать о
комплекте сразу, а не когда программа в цеху в следующий раз выйдет
на связь, — комплект надо найти и подготовить заранее.

Бот и получатели берутся из настроек, которые присылает цех: там они
уже заданы для сводки по смене. Заводить вторую настройку на сервере
значило бы, что рано или поздно они разъедутся.

Получатели — по видам сообщений (docs/calendar.md): склад, покраска,
сводка по задачам. Для вида задана своя строка — шлём туда; пусто —
тем же, кому сводка по смене (`telegram_chats`). Так владелец, ничего
не настраивая, получает всё, а кладовщика можно отделить потом.

Настройки у каждой точки свои. Без точки отправлять некуда: бот и
чаты одной точки — не повод слать в них заявки другой.

Отправляем в отдельном потоке: клиент нажал «Записаться» и должен
увидеть подтверждение сразу, а не ждать, пока ответит Telegram.
"""
import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request

from app.services import shop_settings

log = logging.getLogger('tire_server')

API_URL = 'https://api.telegram.org/bot{token}/sendMessage'
TIMEOUT_SECONDS = 15

# Виды сообщений, у которых могут быть свои получатели
KIND_STORAGE = 'storage'
KIND_PAINT = 'paint'
KIND_DIGEST = 'digest'
KINDS = (KIND_STORAGE, KIND_PAINT, KIND_DIGEST)


def _split(value):
    return [chat.strip() for chat in (value or '').split(',')
            if chat.strip()]


def token_of(db, shop):
    return (shop_settings.get(db, 'telegram_token', shop=shop) or '').strip()


def chats_for(db, shop, kind=None):
    """
    Кому слать сообщение этого вида.

    Своя строка для вида пустая — значит, тем же, кому сводка по смене:
    пустая настройка означает «как у всех», а не «никому».
    """
    if kind in KINDS:
        own = _split(shop_settings.get(db, f'telegram_chats_{kind}',
                                       shop=shop))
        if own:
            return own
    return _split(shop_settings.get(db, 'telegram_chats', shop=shop))


def is_configured(db, shop, kind=None):
    return bool(token_of(db, shop) and chats_for(db, shop, kind))


def _post(token, chat, text):
    """Одно сообщение в один чат. True — Telegram принял."""
    body = urllib.parse.urlencode({
        'chat_id': chat,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true',
    }).encode('utf-8')

    request = urllib.request.Request(API_URL.format(token=token), data=body)
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
        payload = json.loads(answer.read().decode('utf-8'))
    if not payload.get('ok'):
        log.warning('Telegram отклонил сообщение для %s: %s',
                    chat, payload.get('description'))
        return False
    return True


def send(db, text, shop=None, kind=None):
    """
    Отправить всем получателям точки. Возвращает, скольким дошло.

    Сбой у одного не срывает отправку остальным: заблокировавший бота
    бухгалтер не должен лишать кладовщика заявки.
    """
    if shop is None:
        log.info('Точка не указана, сообщение в Telegram не отправлено')
        return 0

    token = token_of(db, shop)
    chats = chats_for(db, shop, kind)

    if not token or not chats:
        log.info('Telegram не настроен, сообщение не отправлено')
        return 0

    delivered = 0
    for chat in chats:
        try:
            if _post(token, chat, text):
                delivered += 1
        except Exception as e:
            log.warning('Не удалось отправить в Telegram для %s: %s', chat, e)

    return delivered


def send_in_background(text, shop=None, kind=None):
    """
    Отправить, не задерживая ответ клиенту.

    Своя короткая сессия: та, что обслуживает запрос, закроется раньше,
    чем поток доберётся до отправки. Поэтому и точку берём номером, а не
    объектом: объект привязан к той, закрывающейся сессии.
    """
    shop_id = getattr(shop, 'id', shop)

    def worker():
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            send(db, text, shop=shop_id, kind=kind)
        finally:
            db.close()

    threading.Thread(target=worker, daemon=True).start()
