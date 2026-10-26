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
                        KIND_ARRIVE, KIND_LATE,
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

    Человеку, до которого не дотянуться ни одним каналом, срочное кладём
    сразу помеченным как пропущенное: строка остаётся — по ней видно,
    что сказать было нечем. Отложенное — ждёт: обычно человек
    записывается и тут же подключает Telegram, и напоминание накануне
    должно до него дойти. Канал проверяется ещё раз при отправке.
    """
    send_at = send_at or shop_now()
    later = send_at > shop_now()
    notice = Notice(
        account_id=client.account_id,
        client_id=client.id,
        kind=kind,
        text=text,
        about=about,
        about_id=about_id,
        send_at=send_at,
        state=WAITING if (later or reachable(db, client)) else SKIPPED)

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


def deliver(db, notice, account, channel):
    """
    Отправить одно сообщение выбранным каналом.

    Отдельно от рассылки, потому что часть сообщений уходит не по
    расписанию, а в ответ на действие человека: приёмщик нажал
    «машина готова» и должен сразу увидеть, дошло или нет.
    """
    client = notice.client

    if channel == BY_TELEGRAM:
        telegram.send_message(account, client.telegram_chat_id, notice.text)
    else:
        title, body = for_browser(notice)
        webpush.send(db, client, title, body, url='/z',
                     tag=f'{notice.about or notice.kind}-'
                         f'{notice.about_id or notice.id}')

    notice.state = SENT
    notice.sent_at = shop_now()
    notice.channel = channel
    notice.last_error = None
    return channel


def send_now(db, client, account, kind, text, about=None, about_id=None):
    """
    Сказать клиенту прямо сейчас и вернуть, чем сказали.

    Возвращает название канала или None, если сказать нечем: человек
    не подключил ни Телеграм, ни уведомления в браузере. Приёмщику
    важно узнать об этом сразу — он снимет трубку и позвонит, а не
    будет думать, что клиента уже позвали.

    Ошибку наружу не прячем: «отправлено» вместо «не дошло» хуже, чем
    честное сообщение о сбое.
    """
    channel = channel_for(db, client, account)

    notice = add(db, client, kind, text, about=about, about_id=about_id)
    if channel is None:
        notice.state = SKIPPED
        db.commit()
        return None

    notice.attempts += 1
    try:
        deliver(db, notice, account, channel)
    except (telegram.TelegramError, webpush.PushError) as e:
        notice.last_error = str(e)[:255]
        notice.state = FAILED
        db.commit()
        log.warning('Не удалось сказать клиенту (%s): %s', channel, e)
        raise

    db.commit()
    return channel


def _out_of_season(db, notice):
    """
    «Пост отдали очереди» — неправда, если очередь выключили.

    И у мойки: живой очереди там нет вовсе, отдавать пост некому. Такое
    сообщение не планируется, но запись могли перевести на мойку уже
    после — проверяем и при отправке.
    """
    if notice.kind != KIND_LATE or notice.about != 'appointment':
        return False
    from app.models import Appointment
    from app.services import shop_settings
    row = db.get(Appointment, notice.about_id)
    if row is None:
        return False
    return (row.direction == 'wash'
            or not shop_settings.live_queue_on(db, row.shop_id))


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
        if channel is None or _out_of_season(db, notice):
            notice.state = SKIPPED
            result['skipped'] += 1
            continue

        notice.attempts += 1
        try:
            deliver(db, notice, account, channel)
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


# Когда напомнить «подъезжайте»: за полчаса — таймер рассылки ходит раз в
# пять минут, и сообщение должно успеть до выезда
ARRIVE_BEFORE_MINUTES = 30
# Приезжать за столько минут до записи
ARRIVE_EARLY_MINUTES = 10
LATE_MINUTES_DEFAULT = 10


def arrive_text(shop_name, appointment, queue_on=True):
    come = appointment.scheduled_at - timedelta(minutes=ARRIVE_EARLY_MINUTES)
    return (f'<b>{shop_name}</b>\n'
            f'Ждём вас в {appointment.scheduled_at.strftime("%H:%M")} — '
            f'подъезжайте к {come.strftime("%H:%M")}.'
            + (f'\nМашина: {appointment.license_plate}'
               if appointment.license_plate else '')
            + ('\n\nНа месте нажмите «Я на месте» в личном кабинете — '
               'дадим первый свободный пост.' if queue_on else ''))


def late_text(shop_name, appointment, minutes):
    return (f'<b>{shop_name}</b>\n'
            f'Запись на {appointment.scheduled_at.strftime("%H:%M")}: вы '
            f'опаздываете больше чем на {minutes} мин, и пост отдали очереди.'
            f'\nПодъезжайте — встанете первым на ближайший свободный пост.')


def called_text(shop_name, plate, post):
    return (f'<b>{shop_name}</b>\n'
            f'Проезжайте на пост {post}.'
            + (f'\n{plate}' if plate else '')
            + '\nСхема, куда ехать, — в личном кабинете.')


def ready_text(shop_name, plate=None):
    """
    Машина готова.

    Коротко и без «спасибо за обращение»: человек читает это в шторке
    телефона, и ему нужно понять две вещи — кто пишет и что ехать.
    """
    return (f'<b>{shop_name}</b>\n'
            f'Машина готова, можно забирать.'
            + (f'\n{plate}' if plate else ''))


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

    made.extend(plan_arrival(db, client, shop_name, appointment))
    return made


def plan_arrival(db, client, shop_name, appointment):
    """
    Перед самой записью — «подъезжайте за 10 минут», и на случай
    опоздания — что пост отдали очереди. Нажмёт «Я на месте» или цех
    отметит приезд — второе отменится. При переносе — ставится заново.
    """
    from app.services import shop_settings
    made = []
    # У мойки живой очереди нет: ни «Я на месте», ни «пост отдали
    # очереди» (docs/booking_wash.md). «Подъезжайте» — как у всех
    queue_on = (appointment.direction != 'wash'
                and shop_settings.live_queue_on(db, appointment.shop_id))
    arrive_at = appointment.scheduled_at - timedelta(minutes=ARRIVE_BEFORE_MINUTES)
    if arrive_at > shop_now():
        made.append(add(db, client, KIND_ARRIVE,
                        arrive_text(shop_name, appointment, queue_on),
                        send_at=arrive_at,
                        about='appointment', about_id=appointment.id))

    late = late_minutes(db, appointment.shop_id)
    late_at = appointment.scheduled_at + timedelta(minutes=late)
    # «Пост отдали очереди» — только когда очередь ведётся
    if queue_on and late_at > shop_now():
        made.append(add(db, client, KIND_LATE,
                        late_text(shop_name, appointment, late),
                        send_at=late_at,
                        about='appointment', about_id=appointment.id))
    return made


def late_minutes(db, shop_id):
    """Через сколько минут опоздания запись перестаёт держать пост."""
    from app.services import shop_settings
    try:
        value = int(shop_settings.get(db, 'booking_late_minutes', shop=shop_id)
                    or LATE_MINUTES_DEFAULT)
    except (TypeError, ValueError):
        value = LATE_MINUTES_DEFAULT
    return max(1, value)
