"""
Очередь уведомлений клиенту и выбор канала.

Каналов два, и оба ненадёжны по-своему. Телеграм доходит до всех и
бесплатно, но человек должен им пользоваться и нажать «Старт» в боте.
Уведомление в браузере ничего не требует на Android и на компьютере, а
на айфоне работает только после «Добавить на экран» — и молча умирает,
если ярлык удалили. Ни один канал не покрывает всех, поэтому здесь их
два и порядок такой: сначала телеграм, потом браузер.

**Канал выбирается при отправке, а не при создании.** Напоминание
ложится в очередь за сутки до приезда; к моменту отправки человек мог
подключить телеграм или, наоборот, снести кабинет с телефона.

**Одно уведомление — один канал.** Прислать и в телеграм, и в браузер
значит разбудить человека дважды об одном и том же. Если телеграм есть,
браузер не трогаем.

Текст пишется один раз, с разметкой телеграма. Браузеру нужен заголовок
отдельно от текста — разбираем при отправке, а не храним дважды: два
текста разъехались бы при первой же правке.
"""
import logging
import re
from datetime import timedelta

from app.models import (Account, Notice, TITLES, KIND_BOOKED, KIND_REMINDER,
                        KIND_CANCELLED, KIND_MOVED, KIND_STORAGE,
                        BY_TELEGRAM, BY_PUSH,
                        WAITING, SENT, FAILED, SKIPPED)
from app.services import telegram, webpush
from app.utils import now as shop_now

log = logging.getLogger('tire_server')

# За сколько часов до приезда напоминаем
REMIND_HOURS = 20

# Сколько раз пробуем отправить, прежде чем сдаться
MAX_ATTEMPTS = 3


# ----------------------------------------------------------------------
# Чем можно достать человека
# ----------------------------------------------------------------------

def channel_for(db, client, account=None):
    """
    Каким каналом писать этому человеку. None — никаким.

    Телеграм первым: он доходит и на айфоне, и после смены телефона, и
    сообщение в нём остаётся в переписке, а не исчезает со шторки.
    """
    if client is None:
        return None

    if client.telegram_chat_id:
        if account is None or account.telegram_bot_token:
            return BY_TELEGRAM

    if webpush.available() and webpush.connected(db, client):
        return BY_PUSH

    return None


def reachable(db, client, account=None):
    return channel_for(db, client, account) is not None


# ----------------------------------------------------------------------
# Очередь: положить
# ----------------------------------------------------------------------

def add(db, client, kind, text, send_at=None, about=None, about_id=None):
    """
    Положить уведомление в очередь.

    Человеку, до которого не дотянуться ни одним каналом, кладём сразу
    помеченным как пропущенное: строка остаётся — по ней видно, что
    напомнить было нечем, — но отправлять некуда.
    """
    notice = Notice(
        account_id=client.account_id,
        client_id=client.id,
        kind=kind,
        text=text,
        about=about,
        about_id=about_id,
        send_at=send_at or shop_now(),
        state=WAITING if reachable(db, client) else SKIPPED)

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


# ----------------------------------------------------------------------
# Очередь: отправить
# ----------------------------------------------------------------------

_TAGS = re.compile(r'<[^>]+>')


def for_browser(notice):
    """
    Разложить текст на заголовок и тело.

    В шторке телефона видно строку-полторы, и заголовком должно быть
    название шиномонтажа — человек по нему и поймёт, кто его зовёт.
    Первая строка текста как раз название.
    """
    plain = _TAGS.sub('', notice.text).strip()
    lines = [line.strip() for line in plain.split('\n') if line.strip()]

    if len(lines) > 1:
        return lines[0], ' '.join(lines[1:])

    return TITLES.get(notice.kind, 'Шиномонтаж'), plain


def send_due(db, limit=100):
    """
    Отправить созревшие. Возвращает сводку.

    Один человек, заблокировавший бота, не должен срывать рассылку
    остальным, поэтому каждое сообщение отправляется само по себе, а
    сбой пишется в строку.
    """
    accounts = {}
    result = {'sent': 0, 'failed': 0, 'skipped': 0,
              BY_TELEGRAM: 0, BY_PUSH: 0}

    for notice in due(db, limit):
        client = notice.client

        account = accounts.get(notice.account_id)
        if account is None:
            account = db.query(Account).filter(
                Account.id == notice.account_id).first()
            accounts[notice.account_id] = account

        channel = channel_for(db, client, account)
        if channel is None:
            notice.state = SKIPPED
            result['skipped'] += 1
            continue

        notice.attempts += 1
        try:
            if channel == BY_TELEGRAM:
                telegram.send_message(account, client.telegram_chat_id,
                                      notice.text)
            else:
                title, body = for_browser(notice)
                webpush.send(db, client, title, body, url='/z',
                             tag=f'{notice.about or notice.kind}-'
                                 f'{notice.about_id or notice.id}')

            notice.state = SENT
            notice.sent_at = shop_now()
            notice.channel = channel
            notice.last_error = None
            result['sent'] += 1
            result[channel] += 1

        except (telegram.TelegramError, webpush.PushError) as e:
            notice.last_error = str(e)[:255]
            # Сдаёмся после третьей попытки: если человек заблокировал
            # бота или снёс кабинет, сообщение не дойдёт и на сотой
            if notice.attempts >= MAX_ATTEMPTS:
                notice.state = FAILED
                result['failed'] += 1
            log.warning('Уведомление №%s не ушло (%s): %s',
                        notice.id, channel, e)

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
