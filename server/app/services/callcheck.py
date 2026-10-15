"""
Подтверждение номера звонком: человек звонит нам, а не мы ему.

Как это выглядит для человека: он вводит телефон, видит номер и кнопку
«Позвонить». Нажал — пошёл вызов, который сбрасывается до соединения.
Отвечать не надо, вводить ничего не надо, звонок бесплатный.

Чем это лучше кода из SMS: нечего прочитать, продиктовать и перепутать,
и не надо ждать, пока оператор донесёт сообщение. Чем хуже: звонить
надо именно с того номера, который ввели, и со скрытого номера не
выйдет. Поэтому запасной путь — SMS — остаётся нужен.

Провайдер подключается настройкой. Пока не подключён, подтверждение
звонком просто не предлагается: ни кнопки, ни упоминания.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings

log = logging.getLogger('tire_server')

TIMEOUT_SECONDS = 15

# Что отвечает провайдер о проверке
PENDING = 'pending'
CONFIRMED = 'confirmed'
EXPIRED = 'expired'


class CallError(Exception):
    """Провайдер отказал или не ответил."""


def available():
    """Подключено ли подтверждение звонком."""
    return bool(settings.CALL_PROVIDER and settings.CALL_PROVIDER != 'off'
                and settings.CALL_TOKEN)


def start(phone):
    """
    Попросить номер, на который человек позвонит.

    Возвращает (идентификатор проверки, номер для звонка, сколько
    секунд на него есть).
    """
    if not available():
        raise CallError('Подтверждение звонком не подключено')

    provider = (settings.CALL_PROVIDER or '').lower()
    if provider == 'flashcall':
        return _start_flashcall(phone)

    raise CallError(f'Неизвестный провайдер звонков: {settings.CALL_PROVIDER}')


def status(check_id):
    """Состояние проверки: ждём звонка, подтвердили или просрочено."""
    if not available():
        raise CallError('Подтверждение звонком не подключено')

    provider = (settings.CALL_PROVIDER or '').lower()
    if provider == 'flashcall':
        return _status_flashcall(check_id)

    raise CallError(f'Неизвестный провайдер звонков: {settings.CALL_PROVIDER}')


# ----------------------------------------------------------------------
# flashcall.ru
# ----------------------------------------------------------------------

BASE = 'https://flashcall.ru/api/v1'


def _call(path, payload=None, query=None):
    url = f'{BASE}{path}'
    if query:
        url += '?' + urllib.parse.urlencode(query)

    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'

    request = urllib.request.Request(url, data=data, headers=headers,
                                     method='POST' if data else 'GET')

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
            return json.loads(answer.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            body = json.loads(e.read().decode('utf-8'))
            detail = body.get('message') or body.get('error') or ''
        except Exception:
            pass
        raise CallError(detail or f'Сервис звонков отказал: {e}')
    except Exception as e:
        raise CallError(f'Сервис звонков не ответил: {e}')


def _e164(phone):
    """Провайдер ждёт номер с плюсом: +79161234567."""
    digits = ''.join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    return '+' + digits


def _start_flashcall(phone):
    answer = _call('/get-phone', {
        'token': settings.CALL_TOKEN,
        'phone': _e164(phone),
    })

    check_id = answer.get('id')
    dial = answer.get('phone')
    if not check_id or not dial:
        raise CallError('Сервис звонков не дал номер для вызова')

    # Своё ограничение снизу: если провайдер однажды вернёт ноль, у
    # человека не должно быть «позвоните за 0 секунд»
    seconds = int(answer.get('expiresIn') or 60)
    return str(check_id), dial, max(30, seconds)


def _status_flashcall(check_id):
    answer = _call('/status', query={
        'token': settings.CALL_TOKEN,
        'id': check_id,
    })

    state = str(answer.get('status') or '').upper()
    if state == 'CONFIRMED':
        return CONFIRMED
    if state == 'EXPIRED':
        return EXPIRED

    # Всё остальное считаем ожиданием: лучше дать человеку дозвониться,
    # чем объявить неудачу из-за незнакомого слова в ответе
    if state != 'PENDING':
        log.warning('Сервис звонков ответил незнакомым состоянием: %s', state)

    return PENDING
