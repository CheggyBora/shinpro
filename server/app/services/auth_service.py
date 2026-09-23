"""
Вход клиента: телефон и ПИН-код.

Порядок для человека:

1. Вводит **номер телефона** — тот, по которому его знают в шиномонтаже.
2. Если он здесь впервые, один раз приходит **код подтверждения**.
3. Придумывает **ПИН из четырёх цифр**.
4. Дальше и всегда: **телефон + ПИН**. Ни кодов, ни писем.

Зачем код на первом заходе, если вход потом только по ПИНу. Без него
ПИН на чужой номер поставил бы кто угодно — а вместе с ним получил бы
чужое хранение и историю визитов. Номер телефона узнать несложно.
Один код за всю жизнь клиента — небольшая цена за то, чтобы кабинет
принадлежал ему.

Куда слать этот код, решает шиномонтаж: SMS на тот же телефон (проще
человеку, но стоит денег) или письмо на почту (бесплатно, но адрес
придётся спросить).
"""
from datetime import datetime, timedelta

from app.config import settings
from app.models import Client, Device, LoginCode
from app.security import (generate_code, hash_secret, secrets_match,
                          is_valid_pin)
from app.services import sms, mail, shop_settings
from app.utils import (normalize_phone, normalize_email,
                       is_valid_phone, is_valid_email, now as shop_now)

PURPOSE_SIGNUP = 'signup'
PURPOSE_PIN_RESET = 'pin_reset'

CHANNEL_SMS = 'sms'
CHANNEL_EMAIL = 'email'

# Что делать приложению или странице на этом шаге
STEP_PIN = 'pin'          # человек известен, спрашиваем ПИН
STEP_VERIFY = 'verify'    # первый заход, нужен код
STEP_SET_PIN = 'set_pin'  # код принят, пора придумать ПИН


class AuthError(Exception):
    """Понятная человеку причина, почему войти не получилось."""


class NeedEmail(AuthError):
    """
    Код надо отправить письмом, а адреса мы не знаем.

    Отдельный тип, чтобы приложение показало поле почты, а не
    ругательство: человек ничего не сделал неправильно.
    """


class AuthService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Куда слать код
    # ------------------------------------------------------------------

    def channel(self):
        value = (shop_settings.get(self.db, 'verify_channel') or CHANNEL_SMS).lower()
        return CHANNEL_EMAIL if value == CHANNEL_EMAIL else CHANNEL_SMS

    # ------------------------------------------------------------------
    # Шаг первый: кто пришёл
    # ------------------------------------------------------------------

    def start(self, phone):
        """
        Что показать человеку, который ввёл номер.

        Возвращает (шаг, известен_ли, заблокирован_ли_ПИН).
        """
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise AuthError('Номер телефона выглядит неправильно')

        client = self.db.query(Client).filter(Client.phone == phone).first()

        # Клиент может быть заведён цехом при обычном визите — но
        # кабинет он ещё не открывал, значит подтверждение нужно
        if client is None or not client.pin_hash or not client.phone_verified_at:
            return STEP_VERIFY, client is not None, False

        blocked = client.pin_failures >= settings.PIN_MAX_FAILURES
        return (STEP_VERIFY if blocked else STEP_PIN), True, blocked

    # ------------------------------------------------------------------
    # Шаг второй: код подтверждения
    # ------------------------------------------------------------------

    def request_code(self, phone, email=None, purpose=PURPOSE_SIGNUP):
        """
        Выслать код. Возвращает (сколько секунд живёт, каким каналом).

        Письмом — только если так настроен шиномонтаж; тогда адрес
        обязателен, и об этом говорим отдельным ответом.
        """
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise AuthError('Номер телефона выглядит неправильно')

        channel = self.channel()
        target = phone

        if channel == CHANNEL_EMAIL:
            target = normalize_email(email) or self._known_email(phone)
            if not target:
                raise NeedEmail('Укажите почту — на неё придёт код')
            if not is_valid_email(target):
                raise AuthError('Почта выглядит неправильно')

        self._check_rate_limit(phone)

        code = generate_code()
        record = LoginCode(
            login=phone,
            channel=channel,
            code_hash=hash_secret(phone, code),
            purpose=purpose,
            expires_at=shop_now() + timedelta(
                minutes=settings.CODE_TTL_MINUTES))
        self.db.add(record)
        self.db.commit()

        try:
            if channel == CHANNEL_EMAIL:
                mail.send_code(target, code, purpose=purpose)
                self._remember_email(phone, target)
            else:
                sms.send_code(phone, code)
        except (mail.MailError, sms.SmsError) as e:
            # Код уже в базе, но человек его не получит — незачем
            # оставлять мусор и занимать лимит попыток
            self.db.delete(record)
            self.db.commit()
            raise AuthError(f'Не удалось отправить код: {e}')

        return settings.CODE_TTL_MINUTES * 60, channel

    def _known_email(self, phone):
        client = self.db.query(Client).filter(Client.phone == phone).first()
        return client.email if client else None

    def _remember_email(self, phone, email):
        client = self.db.query(Client).filter(Client.phone == phone).first()
        if client is not None and not client.email:
            client.email = email
            self.db.commit()

    def _check_rate_limit(self, phone):
        """Не давать заказывать коды пачками — SMS платные."""
        hour_ago = shop_now() - timedelta(hours=1)
        recent = self.db.query(LoginCode).filter(
            LoginCode.login == phone,
            LoginCode.created_at >= hour_ago).count()

        if recent >= settings.CODE_REQUESTS_PER_HOUR:
            raise AuthError(
                'Слишком много запросов кода. Попробуйте через час '
                'или позвоните в шиномонтаж')

    # ------------------------------------------------------------------
    # Шаг третий: проверка кода
    # ------------------------------------------------------------------

    def verify_code(self, phone, code):
        """
        Проверить код и вернуть клиента.

        Здесь же человек связывается со своей карточкой в цеху: если
        по этому телефону клиент уже есть, кабинет открывается к нему,
        со всеми машинами, хранением и историей.
        """
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise AuthError('Номер телефона выглядит неправильно')

        record = self._take_code(phone, code)

        client = self.db.query(Client).filter(Client.phone == phone).first()
        if client is None:
            client = Client(phone=phone)
            self.db.add(client)

        record.used_at = shop_now()
        client.phone_verified_at = shop_now()
        client.last_seen_at = shop_now()

        # Код подтверждён — прежние промахи ПИНом прощаем
        client.pin_failures = 0
        client.pin_blocked_at = None

        self.db.commit()
        self.db.refresh(client)
        return client

    def _take_code(self, phone, code):
        record = self.db.query(LoginCode).filter(
            LoginCode.login == phone,
            LoginCode.used_at.is_(None),
        ).order_by(LoginCode.created_at.desc()).first()

        if record is None:
            raise AuthError('Запросите код заново')

        if record.expires_at < shop_now():
            raise AuthError('Срок действия кода истёк, запросите новый')

        if record.attempts >= settings.CODE_MAX_ATTEMPTS:
            raise AuthError('Слишком много неверных попыток, запросите новый код')

        if not secrets_match(phone, str(code or '').strip(), record.code_hash):
            record.attempts += 1
            self.db.commit()
            left = settings.CODE_MAX_ATTEMPTS - record.attempts
            if left <= 0:
                raise AuthError('Код неверный. Попытки закончились, '
                                'запросите новый код')
            raise AuthError(f'Код неверный. Осталось попыток: {left}')

        return record

    # ------------------------------------------------------------------
    # ПИН-код
    # ------------------------------------------------------------------

    def set_pin(self, client, pin):
        """Придумать или сменить ПИН. Вызывается уже после подтверждения."""
        pin = str(pin or '').strip()
        if not is_valid_pin(pin):
            raise AuthError(
                f'ПИН должен состоять из {settings.PIN_LENGTH} цифр '
                f'и не быть слишком простым — {"1" * settings.PIN_LENGTH} '
                f'и 1234 не подойдут')

        client.pin_hash = hash_secret(client.phone, pin)
        client.pin_updated_at = shop_now()
        client.pin_failures = 0
        client.pin_blocked_at = None
        self.db.commit()
        return client

    def login_by_pin(self, phone, pin):
        """
        Обычный вход: телефон и ПИН.

        Промахи считаем по клиенту, а не по устройству: четыре цифры
        иначе перебираются за минуту с любого телефона.
        """
        phone = normalize_phone(phone)
        client = self.db.query(Client).filter(Client.phone == phone).first()

        if client is None or not client.pin_hash:
            raise AuthError('Сначала подтвердите номер и придумайте ПИН')

        if client.pin_failures >= settings.PIN_MAX_FAILURES:
            raise AuthError('ПИН заблокирован. Подтвердите номер кодом, '
                            'чтобы задать новый')

        if not secrets_match(phone, str(pin or '').strip(), client.pin_hash):
            client.pin_failures += 1
            if client.pin_failures >= settings.PIN_MAX_FAILURES:
                client.pin_blocked_at = shop_now()
            self.db.commit()

            left = settings.PIN_MAX_FAILURES - client.pin_failures
            if left <= 0:
                raise AuthError('ПИН неверный. Попытки закончились, '
                                'подтвердите номер кодом')
            raise AuthError(f'ПИН неверный. Осталось попыток: {left}')

        client.pin_failures = 0
        client.last_seen_at = shop_now()
        self.db.commit()
        self.db.refresh(client)
        return client

    def forget_pin(self, client):
        client.pin_hash = None
        client.pin_updated_at = None
        self.db.commit()
        return client

    # ------------------------------------------------------------------
    # Устройства
    # ------------------------------------------------------------------

    def register_push_token(self, client, device_id, push_token,
                            platform=None, app_version=None):
        """Запомнить, куда слать уведомления этому клиенту."""
        if not device_id:
            return None

        device = self.db.query(Device).filter(
            Device.device_id == device_id).first()

        if device is None:
            device = Device(device_id=device_id, client_id=client.id)
            self.db.add(device)

        # Телефон могли передать другому человеку — привязку переставляем
        device.client_id = client.id
        device.push_token = (push_token or '').strip() or None
        device.platform = platform
        device.app_version = app_version
        device.last_seen_at = shop_now()
        device.is_active = True

        self.db.commit()
        self.db.refresh(device)
        return device
