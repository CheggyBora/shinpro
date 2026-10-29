"""
Сообщения в Telegram о складе и покраске (docs/calendar.md).

Пишем не напрямую, а через очередь: в цеху бывает без интернета, а
водитель должен узнать о комплекте, даже если его заказали в обрыв.
Сообщение ложится в базу и уходит при ближайшей возможности — главное
окно досылает очередь вместе с обменом очередью раз в 20 секунд.

Кому — настраивается по видам (Настройки → Telegram): склад, покраска,
сводка владельцу. Не выбрали никого — тем же, кому сводка по смене.
"""
import json

from logger import log
from models.calendar import TelegramOutbox
from utils import get_moscow_time

KINDS = {
    'storage': 'Склад: отвезти и привезти комплекты',
    'paint': 'Покраска дисков',
    # Задача, поставленная в календаре, — сразу в Telegram; комментарий
    # не уходит никуда (решение владельца 29.10.2026)
    'task': 'Задачи из календаря',
    'digest': 'Сводка задач утром и вечером (с сервера)',
}
ROUTE_KEY = 'telegram_route_{kind}'
MAX_ATTEMPTS = 20
# Сколько ждать, пока контрагент нажмёт «Старт» у бота
PERSONAL_WAIT_DAYS = 3
_asked_at = None

# Главное окно ставит сюда «дослать поскорее»
ON_QUEUED = None


def _settings(db):
    from services.settings_service import SettingsService
    return SettingsService(db)


def route(db, kind):
    """Номера чатов, выбранные для этого вида. Пусто — «как сводке»."""
    raw = _settings(db).get(ROUTE_KEY.format(kind=kind), '') or ''
    try:
        chats = [str(c).strip() for c in json.loads(raw) if str(c).strip()] if raw.strip() else []
    except (ValueError, TypeError):
        chats = []
    return chats


def set_route(db, kind, chat_ids):
    _settings(db).set(ROUTE_KEY.format(kind=kind),
                      json.dumps([str(c) for c in chat_ids if str(c).strip()]))


def recipients(db, kind):
    """Кому отправить: выбранные для вида (только включённые), иначе все включённые."""
    from services.telegram_service import TelegramService
    telegram = TelegramService(db)
    active = telegram.get_active_recipients()
    chosen = set(route(db, kind))
    result = active
    if chosen:
        picked = [r for r in active if r.chat_id in chosen]
        if picked:
            result = picked
    # Плюс люди, которым этот отчёт отмечен в «Доступе» дашборда
    known = {r.chat_id for r in result}
    return result + [r for r in telegram.staff_recipients(kind) if r.chat_id not in known]


def chats_for_server(db, kind):
    """Строка для настроек сервера: пусто — сервер возьмёт общих."""
    from services.telegram_service import TelegramService
    active = {r.chat_id for r in TelegramService(db).get_active_recipients()}
    return ','.join(c for c in route(db, kind) if c in active)


def queue(db, kind, text, target=None):
    """
    Положить сообщение в очередь. Отправит досылка. target — ник
    контрагента: тогда только ему лично.
    """
    row = TelegramOutbox(kind=kind, text=text, created_at=get_moscow_time(),
                         target=target or None)
    db.add(row)
    db.commit()
    if ON_QUEUED is not None:
        try:
            ON_QUEUED()
        except Exception:
            pass
    return row


def pending(db):
    return db.query(TelegramOutbox).filter(
        TelegramOutbox.sent_at.is_(None),
        TelegramOutbox.attempts < MAX_ATTEMPTS).order_by(TelegramOutbox.id).all()


def _personal(db, telegram, row):
    """
    Чат контрагента по нику. Не знаем — спросим бота, кто ему писал.
    None — человек боту ещё не писал. [] — он и так среди получателей
    вида: второй раз то же сообщение ему не шлём.
    """
    global _asked_at
    from datetime import timedelta
    from services.telegram_service import Recipient
    from utils import as_naive
    chat = telegram.chat_of(row.target)
    now = as_naive(get_moscow_time())
    # Бота спрашиваем не чаще раза в две минуты: досылка ходит каждые 20 секунд
    if chat is None and (_asked_at is None or now - _asked_at > timedelta(minutes=2)):
        _asked_at = now
        try:
            telegram.fetch_people()
            db.commit()
        except Exception as e:
            log.warning(f"Не удалось спросить бота, кто ему писал: {e}")
        chat = telegram.chat_of(row.target)
    if chat is None:
        row.last_error = f'@{row.target} ещё не писал боту'
        # Ждём три дня: за это время человек нажмёт «Старт» — или уже не нажмёт
        if row.created_at and now - as_naive(row.created_at) > timedelta(days=PERSONAL_WAIT_DAYS):
            row.attempts = MAX_ATTEMPTS
        db.commit()
        return None
    if chat in {person.chat_id for person in recipients(db, row.kind)}:
        row.sent_at = get_moscow_time()
        db.commit()
        return []
    return [Recipient(chat, '@' + row.target)]


def flush(db):
    """
    Дослать всё, что ждёт. Возвращает, сколько ушло. Бот не настроен —
    сообщения ждут: настроят, и они уйдут.
    """
    from services.telegram_service import TelegramService, TelegramError

    telegram = TelegramService(db)
    if not telegram.get_token():
        return 0
    sent = 0
    for row in pending(db):
        if row.target:
            people = _personal(db, telegram, row)
            if people is None:
                # Ещё не писал боту — подождём: напишет, и сообщение уйдёт
                continue
        else:
            people = recipients(db, row.kind)
        if not people:
            return sent
        delivered = 0
        error = None
        for person in people:
            try:
                telegram._call('sendMessage', {
                    'chat_id': person.chat_id, 'text': row.text,
                    'parse_mode': 'HTML', 'disable_web_page_preview': 'true'})
                delivered += 1
            except TelegramError as e:
                error = str(e)
            except Exception as e:
                error = f'неожиданная ошибка: {e}'
        row.attempts = (row.attempts or 0) + 1
        if delivered:
            row.sent_at = get_moscow_time()
            sent += 1
        else:
            row.last_error = (error or '')[:300]
            log.warning(f"Сообщение в Telegram не ушло: {error}")
            db.commit()
            # Нет связи — дальше пробовать бессмысленно, подождём
            return sent
        db.commit()
    return sent
