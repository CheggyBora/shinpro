"""
Отправка кода входа по SMS.

Провайдер и ключ задаются **в программе цеха** и приезжают обменом.
Так владелец меняет ключ сам, не заходя на сервер, и у каждого
заказчика он свой — сообщения оплачивает тот, кому они нужны.

В переменных окружения сервера ключ тоже можно задать: он работает
как общий, пока точка не прислала свой.

Пока договора нет ни там, ни там, работает режим «log»: код пишется
в журнал сервера, а не уходит клиенту. Так приложение можно
разрабатывать и показывать, не платя за каждое сообщение — но в бою
этот режим означает, что войти не сможет никто, кроме того, у кого
есть доступ к журналу.
"""
import logging
import urllib.parse
import urllib.request

from app.config import settings

log = logging.getLogger('tire_server')

TIMEOUT_SECONDS = 15


class SmsError(Exception):
    pass


def setup(db=None, shop=None):
    """
    Какой провайдер, ключ и подпись. Сначала то, что прислал цех.

    Ключ без провайдера и провайдер без ключа одинаково бесполезны:
    берём пару целиком или не берём вовсе.
    """
    provider = (settings.SMS_PROVIDER or 'log').strip().lower()
    key = settings.SMS_API_KEY
    sender = settings.SMS_SENDER

    if db is not None:
        from app.services import shop_settings

        theirs = (shop_settings.get(db, 'sms_provider', shop=shop)
                  or '').strip().lower()
        their_key = (shop_settings.get(db, 'sms_key', shop=shop) or '').strip()

        if theirs and theirs not in ('log', 'off') and their_key:
            provider, key = theirs, their_key
            sender = (shop_settings.get(db, 'sms_sender', shop=shop)
                      or '').strip() or sender

    return provider, key, sender


def available(db=None, shop=None):
    """Уйдёт ли сообщение человеку, а не в журнал."""
    provider, key, _ = setup(db, shop)
    return bool(provider not in ('log', 'off', '') and key)


def send_code(phone, code, db=None, shop=None, shop_name=None):
    """
    Отправить код на номер. Ошибка провайдера — это SmsError.

    Возвращает True, если сообщение принято к отправке.
    """
    provider, key, sender = setup(db, shop)

    text = (f"{shop_name or settings.SHOP_NAME}: код для входа {code}. "
            f"Никому его не сообщайте.")

    if provider in ('log', 'off', ''):
        # Ровно та строка, по которой код можно найти при разработке
        log.warning("SMS не отправлена (провайдер не подключён). "
                    "Номер %s, код %s", phone, code)
        return True

    if provider == 'smsru':
        return _send_via_smsru(phone, text, key, sender)

    raise SmsError(f"Неизвестный SMS-провайдер: {provider}")


def _send_via_smsru(phone, text, key, sender=None):
    """
    SMS.RU — самый ходовой в России, работает по обычному GET-запросу.

    Другие провайдеры добавляются такой же функцией: разница только
    в адресе и названиях полей.
    """
    if not key:
        raise SmsError("Не задан ключ SMS-провайдера. "
                       "Задайте его в программе цеха: "
                       "Настройки → SMS и звонки")

    params = {
        'api_id': key,
        'to': phone,
        'msg': text,
        'json': 1,
    }
    if sender:
        params['from'] = sender

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
