"""
Проверка админского PIN-кода.

Раньше PIN лежал в базе открытым текстом: любой, кто откроет файл базы,
видел его и мог менять цены и ставки зарплаты. Теперь хранится не сам код,
а его хеш — по нему восстановить PIN нельзя.

Старый открытый PIN переносится в хеш автоматически при первой проверке.
"""
import hashlib
import hmac
import os

from models import Settings

# Ключи в таблице настроек
PIN_HASH_KEY = 'admin_pin_hash'
LEGACY_PIN_KEY = 'admin_pin'

DEFAULT_PIN = '0000'

# Столько раз прогоняется алгоритм. Подбор становится дорогим, а проверка
# по-прежнему незаметна для человека.
ITERATIONS = 200_000
ALGORITHM = 'pbkdf2_sha256'


def _hash_pin(pin, salt=None, iterations=ITERATIONS):
    """Собрать строку вида pbkdf2_sha256$итерации$соль$хеш."""
    if salt is None:
        salt = os.urandom(16)

    digest = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def _check_hash(pin, stored):
    """Сверить введённый PIN с сохранённым хешем."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split('$')
        if algorithm != ALGORITHM:
            return False

        expected = hashlib.pbkdf2_hmac(
            'sha256', pin.encode('utf-8'), bytes.fromhex(salt_hex), int(iterations)
        )
        # Сравнение с постоянным временем, чтобы по скорости ответа
        # нельзя было подбирать код по одному символу
        return hmac.compare_digest(expected.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


class AuthService:
    def __init__(self, db):
        self.db = db

    def _get(self, key):
        return self.db.query(Settings).filter(Settings.key == key).first()

    def _set(self, key, value):
        setting = self._get(key)
        if setting:
            setting.value = value
        else:
            self.db.add(Settings(key=key, value=value))

    def ensure_pin_hashed(self):
        """
        Перевести PIN на хранение в виде хеша.

        Вызывается при запуске программы. Если в базе остался старый
        открытый PIN, он превращается в хеш, а открытая запись удаляется.
        """
        if self._get(PIN_HASH_KEY):
            legacy = self._get(LEGACY_PIN_KEY)
            if legacy:
                # Хеш уже есть, открытая копия больше не нужна
                self.db.delete(legacy)
                self.db.commit()
            return False

        legacy = self._get(LEGACY_PIN_KEY)
        pin = legacy.value if legacy and legacy.value else DEFAULT_PIN

        self._set(PIN_HASH_KEY, _hash_pin(pin))
        if legacy:
            self.db.delete(legacy)
        self.db.commit()
        return True

    def verify_pin(self, pin):
        """Верен ли введённый PIN."""
        if pin is None:
            return False

        stored = self._get(PIN_HASH_KEY)
        if not stored or not stored.value:
            # Хеша ещё нет — заводим его и сверяем
            self.ensure_pin_hashed()
            stored = self._get(PIN_HASH_KEY)
            if not stored:
                return False

        return _check_hash(pin, stored.value)

    def change_pin(self, old_pin, new_pin):
        """
        Сменить PIN. Требует текущий код.

        Возвращает True при успехе, иначе поднимает ValueError с причиной.
        """
        if not self.verify_pin(old_pin):
            raise ValueError("Текущий PIN-код указан неверно")

        new_pin = (new_pin or '').strip()
        if len(new_pin) < 4:
            raise ValueError("Новый PIN-код должен быть не короче 4 символов")
        if not new_pin.isdigit():
            raise ValueError("PIN-код должен состоять только из цифр")
        if new_pin == DEFAULT_PIN:
            raise ValueError("Нельзя задать PIN-код по умолчанию (0000)")

        self._set(PIN_HASH_KEY, _hash_pin(new_pin))
        self.db.commit()
        return True

    def is_default_pin(self):
        """Стоит ли до сих пор PIN по умолчанию — стоит предупредить владельца."""
        return self.verify_pin(DEFAULT_PIN)
