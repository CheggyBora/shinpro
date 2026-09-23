"""
Кто и на что имеет право.

Клиент входит по номеру телефона и получает токен — им он подписывает
каждый следующий запрос. Программа в цеху ходит не по клиентскому
токену, а по отдельному ключу: обмен даёт доступ ко всей базе сразу,
и путать эти два права нельзя.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Client
from app.utils import now as shop_now

ALGORITHM = 'HS256'


# ----------------------------------------------------------------------
# Коды входа
# ----------------------------------------------------------------------

def generate_code():
    """Код из SMS. secrets, а не random: код — это ключ от кабинета."""
    top = 10 ** settings.CODE_LENGTH
    return str(secrets.randbelow(top)).zfill(settings.CODE_LENGTH)


def hash_secret(login, secret):
    """
    Отпечаток кода или ПИНа. В базе лежит он, а не сам код.

    Логин подмешан в соль: одинаковые коды у разных людей дают разные
    отпечатки, и по базе не видно, у кого что совпало.
    """
    material = f"{login}:{secret}".encode('utf-8')
    return hashlib.pbkdf2_hmac(
        'sha256', material, settings.SECRET_KEY.encode('utf-8'), 100_000).hex()


def secrets_match(login, secret, stored_hash):
    """Сравнение за постоянное время: иначе код подбирается по задержке ответа."""
    if not stored_hash:
        return False
    return hmac.compare_digest(hash_secret(login, secret), stored_hash)


def is_valid_pin(pin):
    """
    Годится ли ПИН.

    Только цифры и нужной длины. Отказываем в четырёх одинаковых цифрах
    и в подряд идущих: «1111» и «1234» ставит каждый десятый, и подбор
    начинают именно с них.
    """
    pin = str(pin or '').strip()
    if len(pin) != settings.PIN_LENGTH or not pin.isdigit():
        return False

    if len(set(pin)) == 1:
        return False

    digits = [int(char) for char in pin]
    ascending = all(b - a == 1 for a, b in zip(digits, digits[1:]))
    descending = all(a - b == 1 for a, b in zip(digits, digits[1:]))
    return not (ascending or descending)


# ----------------------------------------------------------------------
# Токены
# ----------------------------------------------------------------------

def create_token(client_id):
    # Срок жизни токена — по UTC: так его проверяет библиотека. Всё
    # остальное время на сервере — время шиномонтажа, см. app/utils.now
    payload = {
        'sub': str(client_id),
        'exp': datetime.utcnow() + timedelta(days=settings.TOKEN_DAYS),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token):
    """Номер клиента из токена. None, если токен испорчен или просрочен."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload['sub'])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# Проверки на входе в запрос
# ----------------------------------------------------------------------

def current_client(authorization: str = Header(default=''),
                   db: Session = Depends(get_db)):
    """Клиент, приславший запрос. Без действующего токена — отказ."""
    if not authorization.lower().startswith('bearer '):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Нужен вход в приложение')

    client_id = decode_token(authorization[7:].strip())
    if client_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Вход устарел, войдите заново')

    client = db.query(Client).filter(Client.id == client_id).first()
    if client is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Клиент не найден')

    if client.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Доступ закрыт, обратитесь в шиномонтаж')

    client.last_seen_at = shop_now()
    db.commit()
    return client


def create_staff_token(staff):
    """
    Токен сотрудника.

    Отдельный от клиентского: у них разные двери, и токен от кабинета
    не должен открывать дашборд с зарплатами всего шиномонтажа.

    В токен кладём отметку времени последнего изменения доступа. Сняли
    права или закрыли доступ — выданные раньше токены перестают
    годиться сразу, а не доживают свои тридцать дней.
    """
    payload = {
        'sub': str(staff.id),
        'kind': 'staff',
        'acc': staff.access_changed_at.isoformat() if staff.access_changed_at else '',
        'exp': datetime.utcnow() + timedelta(days=settings.STAFF_TOKEN_DAYS),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def current_staff(authorization: str = Header(default=''),
                  db: Session = Depends(get_db)):
    """Сотрудник, приславший запрос. Без действующего токена — отказ."""
    from app.models import StaffUser

    if not authorization.lower().startswith('bearer '):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Нужен вход в дашборд')

    try:
        payload = jwt.decode(authorization[7:].strip(), settings.SECRET_KEY,
                             algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Вход устарел, войдите заново')

    if payload.get('kind') != 'staff':
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Этот вход не для дашборда')

    staff = db.query(StaffUser).filter(
        StaffUser.id == int(payload.get('sub', 0) or 0)).first()

    if staff is None or not staff.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Доступ к дашборду закрыт')

    saved = staff.access_changed_at.isoformat() if staff.access_changed_at else ''
    if payload.get('acc') != saved:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Права изменились, войдите заново')

    staff.last_seen_at = shop_now()
    db.commit()
    return staff


def require(permission):
    """
    Проверка права для конкретного запроса.

    Используется как зависимость: Depends(require(PERM_REVENUE)).
    Отказ говорит, что прав нет, и не уточняет, что именно скрыто:
    подсказывать, где лежат зарплаты, незачем.
    """
    def check(staff=Depends(current_staff)):
        if not staff.can(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail='Нет доступа к этому разделу')
        return staff

    return check


def require_sync_key(x_sync_key: str = Header(default='')):
    """
    Пропустить только программу из цеха.

    Пока ключ не задан в настройках, обмен закрыт совсем: сервер,
    поднятый «на посмотреть», не должен по умолчанию отдавать всю базу
    клиентов тому, кто угадал адрес.
    """
    if not settings.SYNC_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail='Обмен не настроен: не задан SERVER_SYNC_KEY')

    if not hmac.compare_digest(x_sync_key or '', settings.SYNC_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail='Неверный ключ обмена')
    return True
