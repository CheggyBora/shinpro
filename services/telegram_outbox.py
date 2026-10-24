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
    'digest': 'Сводка задач утром и вечером (с сервера)',
}
ROUTE_KEY = 'telegram_route_{kind}'
MAX_ATTEMPTS = 20

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
    active = TelegramService(db).get_active_recipients()
    chosen = set(route(db, kind))
    if chosen:
        picked = [r for r in active if r.chat_id in chosen]
        if picked:
            return picked
    return active


def chats_for_server(db, kind):
    """Строка для настроек сервера: пусто — сервер возьмёт общих."""
    from services.telegram_service import TelegramService
    active = {r.chat_id for r in TelegramService(db).get_active_recipients()}
    return ','.join(c for c in route(db, kind) if c in active)


def queue(db, kind, text):
    """Положить сообщение в очередь. Отправит досылка."""
    row = TelegramOutbox(kind=kind, text=text, created_at=get_moscow_time())
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
