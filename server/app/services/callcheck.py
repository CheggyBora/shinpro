"""
Подтверждение номера звонком: человек звонит нам, а не мы ему.

Как это выглядит для человека: он вводит телефон, видит номер и кнопку
«Позвонить». Нажал — пошёл вызов, который сбрасывается до соединения.
Отвечать не надо, вводить ничего не надо, звонок бесплатный.

Чем это лучше кода из SMS: нечего прочитать, продиктовать и перепутать,
и не надо ждать, пока оператор донесёт сообщение. Чем хуже: звонить
надо именно с того номера, который ввели, и со скрытого номера не
выйдет. Поэтому запасной путь — SMS — остаётся нужен.

Провайдер и ключ задаются **в программе цеха** и приезжают обменом,
как часы записи и бот для напоминаний. Так владелец меняет ключ сам,
не заходя на сервер, и у каждого заказчика он свой — звонки оплачивает
тот, кому они нужны.

В переменных окружения сервера ключ тоже можно задать: он работает
как общий, пока точка не прислала свой. Это нужно при настройке, когда
обмена с цехом ещё нет.

Пока ключа нет ни там, ни там, подтверждение звонком не предлагается:
ни кнопки, ни упоминания.
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


def setup(db=None, shop=None):
    """
    Какой сервис звонков и с каким ключом. (провайдер, ключ).

    Сначала смотрим, что прислал цех: там ключ меняет владелец, и его
    правка главнее. Пусто — берём из окружения сервера.
    """
    provider = (settings.CALL_PROVIDER or 'off').strip().lower()
    token = settings.CALL_TOKEN

    if db is not None:
        from app.services import shop_settings

        theirs = (shop_settings.get(db, 'call_provider', shop=shop)
                  or '').strip().lower()
        key = (shop_settings.get(db, 'call_token', shop=shop) or '').strip()

        # Ключ без провайдера и провайдер без ключа одинаково бесполезны:
        # берём пару целиком или не берём вовсе
        if theirs and theirs != 'off' and key:
            provider, token = theirs, key

    return provider, token


def available(db=None, shop=None):
    """Подключено ли подтверждение звонком."""
    provider, token = setup(db, shop)
    return bool(provider and provider != 'off' and token)


def start(phone, db=None, shop=None):
    """
    Попросить номер, на который человек позвонит.

    Возвращает (идентификатор проверки, номер для звонка, сколько
    секунд на него есть).
    """
    provider, token = setup(db, shop)
    if not token or provider in ('', 'off'):
        raise CallError('Подтверждение звонком не подключено')

    if provider == 'flashcall':
        return _start_flashcall(phone, token)

    raise CallError(f'Неизвестный провайдер звонков: {provider}')


def status(check_id, db=None, shop=None):
    """Состояние проверки: ждём звонка, подтвердили или просрочено."""
    provider, token = setup(db, shop)
    if not token or provider in ('', 'off'):
        raise CallError('Подтверждение звонком не подключено')

    if provider == 'flashcall':
        return _status_flashcall(check_id, token)

    raise CallError(f'Неизвестный провайдер звонков: {provider}')


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


def _start_flashcall(phone, token):
    answer = _call('/get-phone', {
        'token': token,
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


def _status_flashcall(check_id, token):
    answer = _call('/status', query={
        'token': token,
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
