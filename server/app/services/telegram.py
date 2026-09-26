"""
Напоминания клиенту в Telegram.

Почему Telegram, а не push из приложения. Пуш на айфоне работает
только после «Добавить на экран», и часть людей туда не дойдёт. SMS
стоят от восьми рублей за штуку. Telegram бесплатен, доходит до всех,
и человеку не нужно ничего устанавливать — он и так им пользуется.

**Бот принадлежит заказчику.** У каждого шиномонтажа своё название,
и писать клиентам «Колеса» от имени бота «РИФа» нельзя. Токен лежит
в аккаунте.

**Отправляем только тем, кто сам подключился.** В кабинете человек
нажимает кнопку, открывается бот с одноразовым кодом, он жмёт «Старт».
Без этого шага писать ему нельзя — и технически, и по-человечески.

**Уведомление сначала кладётся в очередь.** Telegram может не
ответить, напоминание уходит не сейчас, а накануне, и одно и то же
сообщение не должно уйти дважды.
"""
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from app.models import (Account, Client, Notice, KIND_BOOKED, KIND_REMINDER,
                        KIND_CANCELLED, KIND_MOVED, KIND_STORAGE,
                        WAITING, SENT, FAILED, SKIPPED)
from app.utils import now as shop_now

log = logging.getLogger('tire_server')

API = 'https://api.telegram.org/bot{token}/{method}'
TIMEOUT_SECONDS = 15

# Сколько живёт код привязки. Человек нажимает кнопку и сразу
# переходит в бот — десяти минут с запасом хватает, а валяться в базе
# неделю коду незачем
CODE_MINUTES = 10

# За сколько часов до приезда напоминаем
REMIND_HOURS = 20

# Сколько раз пробуем отправить, прежде чем сдаться
MAX_ATTEMPTS = 3


class TelegramError(Exception):
    """Телеграм отказал. Текст — то, что он ответил."""


# ----------------------------------------------------------------------
# Разговор с телеграмом
# ----------------------------------------------------------------------

def call(token, method, payload=None):
    """Запрос к телеграму. Ошибку поднимаем, а не возвращаем молча."""
    if not token:
        raise TelegramError('Бот не подключён')

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST' if data else 'GET')

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
            result = json.loads(answer.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = json.loads(e.read().decode('utf-8')).get('description', '')
        except Exception:
            pass
        raise TelegramError(detail or f'Телеграм отказал: {e}')
    except Exception as e:
        raise TelegramError(f'Не удалось обратиться к телеграму: {e}')

    if not result.get('ok'):
        raise TelegramError(result.get('description', 'Телеграм отказал'))

    return result.get('result')


def connect_bot(db, account, token):
    """
    Подключить бота к аккаунту.

    Токен сразу проверяем: неверный лучше отвергнуть здесь, чем через
    неделю обнаружить, что напоминания никому не уходили.
    """
    info = call(token, 'getMe')

    account.telegram_bot_token = token
    account.telegram_bot_username = info.get('username')
    if not account.telegram_secret:
        account.telegram_secret = secrets.token_urlsafe(24)

    db.commit()
    db.refresh(account)
    return account


def set_webhook(account, base_url):
    """
    Сказать телеграму, куда слать сообщения от людей.

    Адрес с секретом внутри: без него любой, кто узнал адрес сервера,
    писал бы боту от имени телеграма.
    """
    url = f"{base_url.rstrip('/')}/telegram/{account.telegram_secret}"
    return call(account.telegram_bot_token, 'setWebhook', {
        'url': url,
        'allowed_updates': ['message'],
        'drop_pending_updates': True,
    })


def send_message(account, chat_id, text):
    return call(account.telegram_bot_token, 'sendMessage', {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': True,
    })


# ----------------------------------------------------------------------
# Привязка кабинета к боту
# ----------------------------------------------------------------------

def link_code(db, client):
    """
    Одноразовый код для кнопки «Напоминать в Telegram».

    Кабинет отдаёт ссылку на бота с этим кодом. Бот присылает код
    обратно — и по нему находится человек. Иначе связать переписку в
    телеграме с клиентом в базе было бы нечем.
    """
    client.telegram_code = secrets.token_urlsafe(9)
    client.telegram_code_until = shop_now() + timedelta(minutes=CODE_MINUTES)
    db.commit()
    return client.telegram_code


def link_url(account, code):
    if not account.telegram_bot_username:
        return None
    return f'https://t.me/{account.telegram_bot_username}?start={code}'


def link_by_code(db, account, code, chat_id):
    """
    Привязать переписку к человеку. Возвращает клиента или None.

    Код одноразовый: после привязки он стирается, иначе по нему
    подключился бы кто угодно, кому он попался на глаза.
    """
    if not code:
        return None

    client = db.query(Client).filter(
        Client.account_id == account.id,
        Client.telegram_code == code).first()

    if client is None:
        return None

    if client.telegram_code_until and client.telegram_code_until < shop_now():
        return None

    client.telegram_chat_id = str(chat_id)
    client.telegram_linked_at = shop_now()
    client.telegram_code = None
    client.telegram_code_until = None
    db.commit()
    db.refresh(client)

    return client


def unlink(db, client):
    """Отключить напоминания. Пишем только тем, кто сам подключился."""
    client.telegram_chat_id = None
    client.telegram_linked_at = None
    db.commit()
    return client


def handle_update(db, account, update):
    """
    Что пришло от человека в бот.

    Умеет ровно две вещи: привязать кабинет по коду из «Старта» и
    отключить напоминания. Переписку с ботом не разводим: на вопросы
    отвечает шиномонтаж по телефону, а не программа.
    """
    message = (update or {}).get('message') or {}
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    text = (message.get('text') or '').strip()

    if not chat_id:
        return None

    if text.startswith('/start'):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ''

        client = link_by_code(db, account, code, chat_id)
        if client is not None:
            send_message(account, chat_id,
                         f'Готово, {client.name or "здравствуйте"}. '
                         f'Напомним о записи накануне и сообщим, когда '
                         f'закончится срок хранения шин.\n\n'
                         f'Чтобы отключить — /stop')
            return client

        send_message(account, chat_id,
                     'Чтобы получать напоминания, откройте кабинет на '
                     'сайте шиномонтажа и нажмите «Напоминать в Telegram». '
                     'Ссылка оттуда приведёт сюда уже с кодом.')
        return None

    if text.startswith('/stop'):
        client = db.query(Client).filter(
            Client.account_id == account.id,
            Client.telegram_chat_id == str(chat_id)).first()

        if client is not None:
            unlink(db, client)

        send_message(account, chat_id,
                     'Напоминания отключены. Включить обратно можно в '
                     'кабинете на сайте шиномонтажа.')
        return None

    send_message(account, chat_id,
                 'Я умею только напоминать о записи. По всем вопросам '
                 'лучше позвонить в шиномонтаж.')
    return None


# ----------------------------------------------------------------------
# Очередь: положить и отправить
# ----------------------------------------------------------------------

def add(db, client, kind, text, send_at=None, about=None, about_id=None):
    """
    Положить уведомление в очередь.

    Человеку без подключённого бота кладём сразу помеченным как
    пропущенное: строка остаётся — по ней видно, что напомнить было
    нечем, — но отправлять нечего.
    """
    notice = Notice(
        account_id=client.account_id,
        client_id=client.id,
        kind=kind,
        text=text,
        about=about,
        about_id=about_id,
        send_at=send_at or shop_now(),
        state=WAITING if client.telegram_chat_id else SKIPPED)

    db.add(notice)
    db.commit()
    db.refresh(notice)
    return notice


def cancel_about(db, about, about_id, kinds=None):
    """
    Отменить неотправленные уведомления о чём-то.

    Запись отменили — напоминание «завтра приезжать» уходить не должно.
    Уже отправленные не трогаем: сказанного не воротишь.
    """
    query = db.query(Notice).filter(
        Notice.about == about,
        Notice.about_id == about_id,
        Notice.state == WAITING)

    if kinds:
        query = query.filter(Notice.kind.in_(kinds))

    count = 0
    for notice in query.all():
        notice.state = SKIPPED
        count += 1

    db.commit()
    return count


def due(db, limit=100):
    """Что пора отправлять."""
    return db.query(Notice).filter(
        Notice.state == WAITING,
        Notice.send_at <= shop_now()).order_by(
        Notice.send_at).limit(limit).all()


def send_due(db, limit=100):
    """
    Отправить созревшие. Возвращает сводку.

    Заблокировавший бота человек не должен срывать рассылку остальным,
    поэтому каждое сообщение отправляется само по себе, а сбой пишется
    в строку.
    """
    accounts = {}
    result = {'sent': 0, 'failed': 0, 'skipped': 0}

    for notice in due(db, limit):
        client = notice.client

        if client is None or not client.telegram_chat_id:
            notice.state = SKIPPED
            result['skipped'] += 1
            continue

        account = accounts.get(notice.account_id)
        if account is None:
            account = db.query(Account).filter(
                Account.id == notice.account_id).first()
            accounts[notice.account_id] = account

        if account is None or not account.telegram_bot_token:
            notice.state = SKIPPED
            result['skipped'] += 1
            continue

        notice.attempts += 1
        try:
            send_message(account, client.telegram_chat_id, notice.text)
            notice.state = SENT
            notice.sent_at = shop_now()
            notice.last_error = None
            result['sent'] += 1
        except TelegramError as e:
            notice.last_error = str(e)[:255]
            # Сдаёмся после третьей попытки: если человек заблокировал
            # бота, сообщение не дойдёт и на сотой
            if notice.attempts >= MAX_ATTEMPTS:
                notice.state = FAILED
                result['failed'] += 1
            log.warning('Уведомление №%s не ушло: %s', notice.id, e)

    db.commit()
    return result


# ----------------------------------------------------------------------
# Тексты
# ----------------------------------------------------------------------

def when_text(moment):
    return moment.strftime('%d.%m в %H:%M')


def booked_text(shop_name, appointment):
    return (f'<b>{shop_name}</b>\n'
            f'Записали вас на {when_text(appointment.scheduled_at)}.\n'
            f'Работы займут около {appointment.duration_minutes or 60} мин.'
            + (f'\nМашина: {appointment.license_plate}'
               if appointment.license_plate else ''))


def reminder_text(shop_name, appointment):
    return (f'<b>{shop_name}</b>\n'
            f'Напоминаем: вы записаны на '
            f'{when_text(appointment.scheduled_at)}.'
            + (f'\nМашина: {appointment.license_plate}'
               if appointment.license_plate else '')
            + '\n\nНе получается — отмените в кабинете, окно достанется '
              'другому.')


def cancelled_text(shop_name, appointment):
    return (f'<b>{shop_name}</b>\n'
            f'Запись на {when_text(appointment.scheduled_at)} отменена.')


def moved_text(shop_name, appointment):
    return (f'<b>{shop_name}</b>\n'
            f'Ваша запись перенесена на '
            f'{when_text(appointment.scheduled_at)}.')


def plan_for_appointment(db, client, shop_name, appointment):
    """
    Разложить уведомления по записи: подтверждение сейчас, напоминание
    накануне.

    Напоминание не ставим, если до приезда меньше, чем срок напоминания:
    сообщение «напоминаем, вы записаны» через минуту после записи —
    издевательство.
    """
    made = []

    made.append(add(db, client, KIND_BOOKED,
                    booked_text(shop_name, appointment),
                    about='appointment', about_id=appointment.id))

    remind_at = appointment.scheduled_at - timedelta(hours=REMIND_HOURS)
    if remind_at > shop_now():
        made.append(add(db, client, KIND_REMINDER,
                        reminder_text(shop_name, appointment),
                        send_at=remind_at,
                        about='appointment', about_id=appointment.id))

    return made
