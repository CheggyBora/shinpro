"""
Проверка ключа flashcall.ru прямо из программы (решение владельца 30.10.2026).

Ключ звонков раньше просто сохранялся: ошибся в нём — узнаешь, когда
человек не сможет войти в дашборд. Теперь его можно проверить пробным
звонком: программа просит у flashcall.ru номер для вызова, владелец
звонит на него со своего телефона, программа ждёт «подтверждён».

API то же, что у сервера (server/app/services/callcheck.py):
POST /get-phone {token, phone} → {id, phone, expiresIn};
GET /status?token&id → {status: PENDING | CONFIRMED | EXPIRED, callerPhone}.
Платный только состоявшийся звонок — 0,20 ₽; несостоявшийся бесплатный.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://flashcall.ru/api/v1'
TIMEOUT_SECONDS = 15

PENDING, CONFIRMED, EXPIRED = 'pending', 'confirmed', 'expired'


class FlashcallError(Exception):
    """Сервис отказал или не ответил — текст для человека."""


def _call(path, payload=None, query=None):
    url = BASE + path
    if query:
        url += '?' + urllib.parse.urlencode(query)
    data, headers = None, {}
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
        if e.code in (401, 403):
            raise FlashcallError('Ключ не принят — проверьте, что скопирован целиком'
                                 + (f' ({detail})' if detail else ''))
        raise FlashcallError(detail or f'flashcall.ru отказал: код {e.code}')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FlashcallError(f'flashcall.ru не отвечает — проверьте интернет ({e})')
    except ValueError:
        raise FlashcallError('flashcall.ru ответил непонятно — попробуйте ещё раз')


def e164(phone):
    """«8 909 …», «+7 (909) …» → «+7909…»: сервис ждёт номер с плюсом."""
    digits = ''.join(ch for ch in str(phone or '') if ch.isdigit())
    if len(digits) == 11 and digits[0] == '8':
        digits = '7' + digits[1:]
    if len(digits) == 10:
        digits = '7' + digits
    if len(digits) != 11 or digits[0] != '7':
        raise FlashcallError('Номер — российский, 11 цифр: +7 900 000-00-00')
    return '+' + digits


def get_phone(token, phone):
    """Попросить номер для пробного звонка. (id проверки, куда звонить, сколько секунд)."""
    token = (token or '').strip()
    if not token:
        raise FlashcallError('Сначала вставьте ключ')
    answer = _call('/get-phone', {'token': token, 'phone': e164(phone)})
    check_id, dial = answer.get('id'), answer.get('phone')
    if not check_id or not dial:
        raise FlashcallError(answer.get('message') or 'flashcall.ru не дал номер для звонка')
    return str(check_id), str(dial), max(30, int(answer.get('expiresIn') or 60))


def status(token, check_id):
    """(состояние, с какого номера звонили) — PENDING, CONFIRMED или EXPIRED."""
    answer = _call('/status', query={'token': (token or '').strip(), 'id': check_id})
    state = str(answer.get('status') or '').upper()
    caller = answer.get('callerPhone')
    if state == 'CONFIRMED':
        return CONFIRMED, caller
    if state == 'EXPIRED':
        return EXPIRED, caller
    return PENDING, caller
