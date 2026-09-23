"""
Отправка кода входа по SMS.

Провайдер подключается настройкой. Пока договора нет, работает режим
«log»: код пишется в журнал сервера, а не уходит клиенту. Так приложение
можно разрабатывать и показывать, не платя за каждое сообщение — но
в бою этот режим означает, что войти не сможет никто, кроме того,
у кого есть доступ к журналу.
"""
import logging
import urllib.parse
import urllib.request

from app.config import settings

log = logging.getLogger('tire_server')

TIMEOUT_SECONDS = 15


class SmsError(Exception):
    pass


def send_code(phone, code):
    """
    Отправить код на номер. Ошибка провайдера — это SmsError.

    Возвращает True, если сообщение принято к отправке.
    """
    text = (f"{settings.SHOP_NAME}: код для входа {code}. "
            f"Никому его не сообщайте.")

    provider = (settings.SMS_PROVIDER or 'log').lower()
    if provider == 'log':
        # Ровно та строка, по которой код можно найти при разработке
        log.warning("SMS не отправлена (провайдер не подключён). "
                    "Номер %s, код %s", phone, code)
        return True

    if provider == 'smsru':
        return _send_via_smsru(phone, text)

    raise SmsError(f"Неизвестный SMS-провайдер: {settings.SMS_PROVIDER}")


def _send_via_smsru(phone, text):
    """
    SMS.RU — самый ходовой в России, работает по обычному GET-запросу.

    Другие провайдеры добавляются такой же функцией: разница только
    в адресе и названиях полей.
    """
    if not settings.SMS_API_KEY:
        raise SmsError("Не задан ключ SMS-провайдера (SERVER_SMS_API_KEY)")

    params = {
        'api_id': settings.SMS_API_KEY,
        'to': phone,
        'msg': text,
        'json': 1,
    }
    if settings.SMS_SENDER:
        params['from'] = settings.SMS_SENDER

    url = 'https://sms.ru/sms/send?' + urllib.parse.urlencode(params)

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            payload = response.read().decode('utf-8')
    except Exception as e:
        raise SmsError(f"Не удалось связаться с SMS-провайдером: {e}")

    import json
    try:
        answer = json.loads(payload)
    except ValueError:
        raise SmsError(f"Непонятный ответ провайдера: {payload[:200]}")

    if answer.get('status') != 'OK':
        raise SmsError(answer.get('status_text') or 'Провайдер отклонил отправку')

    return True
