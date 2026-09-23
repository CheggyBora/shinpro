"""
Сообщения в Telegram из сервера.

Нужно ровно для одного: клиент записался и попросил достать свой
комплект со склада. Кладовщик должен узнать об этом сразу, а не когда
программа в цеху в следующий раз выйдет на связь, — комплект надо
найти и подготовить заранее.

Бот и получатели берутся из настроек, которые присылает цех: там они
уже заданы для сводки по смене. Заводить вторую настройку на сервере
значило бы, что рано или поздно они разъедутся.

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


def is_configured(db):
    return bool(shop_settings.get(db, 'telegram_token')
                and shop_settings.get(db, 'telegram_chats'))


def send(db, text):
    """
    Отправить всем получателям. Возвращает, скольким дошло.

    Сбой у одного не срывает отправку остальным: заблокировавший бота
    бухгалтер не должен лишать кладовщика заявки.
    """
    token = (shop_settings.get(db, 'telegram_token') or '').strip()
    chats = [chat.strip() for chat
             in (shop_settings.get(db, 'telegram_chats') or '').split(',')
             if chat.strip()]

    if not token or not chats:
        log.info('Telegram не настроен, сообщение не отправлено')
        return 0

    delivered = 0
    for chat in chats:
        body = urllib.parse.urlencode({
            'chat_id': chat,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': 'true',
        }).encode('utf-8')

        try:
            request = urllib.request.Request(API_URL.format(token=token),
                                             data=body)
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
                payload = json.loads(answer.read().decode('utf-8'))
            if payload.get('ok'):
                delivered += 1
            else:
                log.warning('Telegram отклонил сообщение для %s: %s',
                            chat, payload.get('description'))
        except Exception as e:
            log.warning('Не удалось отправить в Telegram для %s: %s', chat, e)

    return delivered


def send_in_background(text):
    """
    Отправить, не задерживая ответ клиенту.

    Своя короткая сессия: та, что обслуживает запрос, закроется раньше,
    чем поток доберётся до отправки.
    """
    def worker():
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            send(db, text)
        finally:
            db.close()

    threading.Thread(target=worker, daemon=True).start()
