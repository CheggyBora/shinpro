"""
Вход персонала и раздача прав.

Вход устроен как у клиента: телефон, код на первом заходе, дальше ПИН.
Разница в том, кого пускают: учётку заводит владелец, и человек с
улицы, знающий чужой номер, сюда не войдёт — его просто нет в списке.

Кто кого заводит:

    владелец  →  админ
    владелец  →  ещё один владелец (и это стоит делать осознанно)

Мастера в дашборд не ходят: свою зарплату они смотрят в программе
цеха, на экране приёмщика.

Отключение действует сразу. Не «до следующего обмена» и не «когда
истечёт токен»: человек теряет доступ в ту же минуту.
"""
from datetime import datetime, timedelta

import secrets

from app.config import settings
from app.models import (Client, LoginCode, StaffUser, StaffAction, REPORT_KINDS,
                        ALL_PERMISSIONS, ROLE_OWNER, ROLE_ADMIN,
                        ROLE_TITLES)
from app.security import (generate_code, hash_secret, secrets_match,
                          is_valid_pin)
from app.services import callcheck, sms, mail, shop_settings
from app.services.auth_service import (AuthError, NeedEmail, STEP_PIN,
                                       STEP_VERIFY, CHANNEL_EMAIL,
                                       CHANNEL_SMS, CHANNEL_CALL)
from app.utils import normalize_phone, normalize_email, is_valid_phone, now as shop_now

PURPOSE_STAFF = 'staff'


class StaffError(Exception):
    """Понятная причина, почему не вышло."""


class StaffService:
    def __init__(self, db, account_id=None):
        self.db = db
        self.account_id = account_id

    def _staff(self, phone):
        """Сотрудник этого аккаунта с таким телефоном."""
        return self.db.query(StaffUser).filter(
            StaffUser.phone == phone,
            StaffUser.account_id == self.account_id).first()

    # ------------------------------------------------------------------
    # Вход
    # ------------------------------------------------------------------

    def find(self, phone):
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise AuthError('Номер телефона выглядит неправильно')
        return self._staff(phone)

    def start(self, phone):
        """
        Что спросить у человека, который ввёл номер.

        Про то, что номера нет в списке, говорим тем же ответом, что и
        про «введите ПИН»: иначе по форме входа можно перебрать номера
        и узнать, кто работает в шиномонтаже.
        """
        staff = self.find(phone)

        if staff is None or not staff.is_active:
            return STEP_VERIFY, False

        if not staff.pin_hash or not staff.phone_verified_at:
            return STEP_VERIFY, True

        if staff.pin_failures >= settings.PIN_MAX_FAILURES:
            return STEP_VERIFY, True

        return STEP_PIN, True

    def channel(self):
        """
        Чем подтверждать номер: SMS или письмом.

        Настройка приходит из цеха, поэтому берём её у первой точки
        аккаунта: для сети это общее решение, а не свойство точки.
        """
        from app.services import tenancy

        shops = tenancy.shops_of(self.db, self.account_id)
        value = (shop_settings.get(self.db, 'verify_channel',
                                   shop=shops[0] if shops else None)
                 or CHANNEL_SMS).lower()
        return CHANNEL_EMAIL if value == CHANNEL_EMAIL else CHANNEL_SMS

    def code_available(self):
        """
        Можно ли подтвердить номер кодом.

        Звонок подключён, а SMS нет — только звонок (решение владельца
        29.10.2026: SMS пока не используем). Письмом — если так настроено.
        Не подключено ни то ни другое — как раньше: код уходит в журнал,
        иначе на новом сервере не войти вовсе.
        """
        if self.channel() == CHANNEL_EMAIL:
            return True
        return sms.available(self.db, self._shop()) or not self.call_available()

    def request_code(self, phone, email=None):
        """
        Выслать код сотруднику.

        Если номера нет в списке или доступ закрыт, код не уходит, но
        ответ такой же, как при удаче: снаружи должно быть не видно,
        кто из сотрудников заведён.
        """
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise AuthError('Номер телефона выглядит неправильно')

        if not self.code_available():
            raise AuthError('Вход по SMS выключен — подтвердите номер звонком')

        staff = self._staff(phone)

        seconds = settings.CODE_TTL_MINUTES * 60
        channel = self.channel()

        if staff is None or not staff.is_active:
            return seconds, channel

        self._check_rate_limit(phone)

        target = phone
        if channel == CHANNEL_EMAIL:
            target = normalize_email(email) or self._known_email(phone)
            if not target:
                raise NeedEmail('Укажите почту — на неё придёт код')

        code = generate_code()
        record = LoginCode(
            login=phone,
            account_id=self.account_id,
            channel=channel,
            code_hash=hash_secret(phone, code),
            purpose=PURPOSE_STAFF,
            expires_at=shop_now() + timedelta(
                minutes=settings.CODE_TTL_MINUTES))
        self.db.add(record)
        self.db.commit()

        try:
            if channel == CHANNEL_EMAIL:
                mail.send_code(target, code, purpose=PURPOSE_STAFF)
            else:
                sms.send_code(phone, code, self.db, self._shop())
        except (mail.MailError, sms.SmsError) as e:
            self.db.delete(record)
            self.db.commit()
            raise AuthError(f'Не удалось отправить код: {e}')

        return seconds, channel

    # ------------------------------------------------------------------
    # Подтверждение звонком
    # ------------------------------------------------------------------
    #
    # Устроено так же, как у клиента, и с той же оговоркой: про
    # незаведённый номер снаружи знать не должны. Поэтому чужому номеру
    # отвечаем так же, как своему, — просто звонок не подтвердит никого.

    def _shop(self):
        """Точка, чьи настройки берём: ключи общие на всю сеть."""
        from app.services import tenancy

        shops = tenancy.shops_of(self.db, self.account_id)
        return shops[0] if shops else None

    def call_available(self):
        return callcheck.available(self.db, self._shop())

    def start_call(self, phone):
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise AuthError('Номер телефона выглядит неправильно')

        if not self.call_available():
            raise AuthError('Подтверждение звонком не подключено')

        self._check_rate_limit(phone)

        try:
            check_id, dial, seconds = callcheck.start(
                phone, self.db, self._shop())
        except callcheck.CallError as e:
            raise AuthError(f'Не удалось начать проверку: {e}')

        ticket = secrets.token_urlsafe(24)
        record = LoginCode(
            login=phone,
            account_id=self.account_id,
            channel=CHANNEL_CALL,
            code_hash=hash_secret(phone, ticket),
            external_id=check_id,
            purpose=PURPOSE_STAFF,
            expires_at=shop_now() + timedelta(seconds=seconds))
        self.db.add(record)
        self.db.commit()

        return {'dial': dial, 'ticket': ticket, 'seconds': seconds}

    def check_call(self, phone, ticket):
        """Дозвонился ли. Возвращает сотрудника или None, пока ждём."""
        phone = normalize_phone(phone)

        record = self.db.query(LoginCode).filter(
            LoginCode.login == phone,
            LoginCode.account_id == self.account_id,
            LoginCode.purpose == PURPOSE_STAFF,
            LoginCode.channel == CHANNEL_CALL,
            LoginCode.used_at.is_(None),
        ).order_by(LoginCode.created_at.desc()).first()

        if record is None or not record.external_id:
            raise AuthError('Начните вход заново')

        if not secrets_match(phone, ticket, record.code_hash):
            raise AuthError('Начните вход заново')

        try:
            state = callcheck.status(record.external_id,
                                     self.db, self._shop())
        except callcheck.CallError:
            # Сеть моргнула — не повод отказывать во входе
            return None

        if state == callcheck.PENDING:
            if record.expires_at < shop_now():
                raise AuthError('Время вышло. Начните вход заново')
            return None

        if state == callcheck.EXPIRED:
            raise AuthError('Звонка не было. Начните вход заново')

        record.used_at = shop_now()

        staff = self._staff(phone)
        if staff is None or not staff.is_active:
            # Номер подтверждён, но доступа у него нет. Говорим ровно
            # то же, что при неверном коде: иначе по форме входа можно
            # перебрать номера и узнать, кто здесь работает
            self.db.commit()
            raise AuthError('Доступ закрыт. Обратитесь к владельцу')

        staff.phone_verified_at = shop_now()
        staff.last_seen_at = shop_now()
        staff.pin_failures = 0
        self.db.commit()
        self.db.refresh(staff)
        self.log(staff, 'call', 'вход по звонку')
        return staff

    def _known_email(self, phone):
        client = self.db.query(Client).filter(
            Client.phone == phone,
            Client.account_id == self.account_id).first()
        return client.email if client else None

    def _check_rate_limit(self, phone):
        hour_ago = shop_now() - timedelta(hours=1)
        recent = self.db.query(LoginCode).filter(
            LoginCode.login == phone,
            LoginCode.account_id == self.account_id,
            LoginCode.purpose == PURPOSE_STAFF,
            LoginCode.created_at >= hour_ago).count()

        if recent >= settings.CODE_REQUESTS_PER_HOUR:
            raise AuthError('Слишком много запросов кода. Попробуйте через час')

    def verify_code(self, phone, code):
        """Проверить код и пустить сотрудника."""
        phone = normalize_phone(phone)
        staff = self._staff(phone)

        record = self._take_code(phone, code)

        # Проверяем доступ ПОСЛЕ кода: пока код не сошёлся, человек не
        # должен по ответу понять, заведён такой сотрудник или нет
        if staff is None or not staff.is_active:
            raise AuthError('Доступ к дашборду закрыт. Обратитесь к владельцу')

        record.used_at = shop_now()
        staff.phone_verified_at = shop_now()
        staff.last_seen_at = shop_now()
        staff.pin_failures = 0
        staff.pin_blocked_at = None

        self.db.commit()
        self.db.refresh(staff)
        self.log(staff, 'verify', 'вход по коду')
        return staff

    def _take_code(self, phone, code):
        record = self.db.query(LoginCode).filter(
            LoginCode.login == phone,
            LoginCode.account_id == self.account_id,
            LoginCode.purpose == PURPOSE_STAFF,
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

    def set_pin(self, staff, pin):
        pin = str(pin or '').strip()
        if not is_valid_pin(pin):
            raise AuthError(
                f'ПИН должен состоять из {settings.PIN_LENGTH} цифр '
                f'и не быть слишком простым')

        staff.pin_hash = hash_secret(staff.phone, pin)
        staff.pin_updated_at = shop_now()
        staff.pin_failures = 0
        staff.pin_blocked_at = None
        self.db.commit()
        self.log(staff, 'set_pin', 'задан ПИН')
        return staff

    def login_by_pin(self, phone, pin):
        phone = normalize_phone(phone)
        staff = self._staff(phone)

        if staff is None or not staff.pin_hash:
            raise AuthError('Сначала подтвердите номер и придумайте ПИН')

        if not staff.is_active:
            raise AuthError('Доступ к дашборду закрыт. Обратитесь к владельцу')

        if staff.pin_failures >= settings.PIN_MAX_FAILURES:
            raise AuthError('ПИН заблокирован. Подтвердите номер кодом, '
                            'чтобы задать новый')

        if not secrets_match(phone, str(pin or '').strip(), staff.pin_hash):
            staff.pin_failures += 1
            if staff.pin_failures >= settings.PIN_MAX_FAILURES:
                staff.pin_blocked_at = shop_now()
            self.db.commit()

            left = settings.PIN_MAX_FAILURES - staff.pin_failures
            if left <= 0:
                raise AuthError('ПИН неверный. Попытки закончились, '
                                'подтвердите номер кодом')
            raise AuthError(f'ПИН неверный. Осталось попыток: {left}')

        staff.pin_failures = 0
        staff.last_seen_at = shop_now()
        self.db.commit()
        self.db.refresh(staff)
        self.log(staff, 'login', 'вход по ПИНу')
        return staff

    # ------------------------------------------------------------------
    # Люди и права
    # ------------------------------------------------------------------

    def people(self):
        return self.db.query(StaffUser).filter(
            StaffUser.account_id == self.account_id).order_by(
            StaffUser.id).all()

    def add(self, author, phone, name=None, role=None, permissions=None):
        """Завести сотрудника. Возвращает его учётку."""
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise StaffError('Номер телефона выглядит неправильно')

        role = role or ROLE_ADMIN
        if role not in ROLE_TITLES:
            raise StaffError(f'Неизвестная роль: {role}')
        if role == ROLE_OWNER and (author is None or author.role != ROLE_OWNER):
            raise StaffError('Назначить владельца может только владелец')

        existing = self._staff(phone)
        if existing is not None:
            raise StaffError(f'{phone} уже заведён: {existing.role_title}')

        staff = StaffUser(
            phone=phone,
            account_id=self.account_id,
            name=(name or '').strip() or None,
            role=role,
            created_by_id=author.id if author else None)
        staff.permissions = _pack(permissions)

        self.db.add(staff)
        self.db.commit()
        self.db.refresh(staff)

        self.log(author, 'staff_add',
                 f'заведён {staff.title}, роль: {staff.role_title}')
        return staff

    def update(self, author, staff_id, name=None, role=None, permissions=None,
               is_active=None, phone=None, telegram=None, reports=None):
        staff = self.db.query(StaffUser).filter(
            StaffUser.id == staff_id,
            StaffUser.account_id == self.account_id).first()
        if staff is None:
            raise StaffError('Сотрудник не найден')

        changes = []

        if phone is not None:
            changes.append(self._change_phone(author, staff, phone))

        if telegram is not None:
            staff.telegram = clean_telegram(telegram)
            changes.append(f'Telegram: @{staff.telegram}' if staff.telegram
                           else 'Telegram убран')

        if reports is not None:
            chosen = [kind for kind in reports if kind in REPORT_KINDS]
            staff.reports = ','.join(dict.fromkeys(chosen)) or None
            changes.append('отчёты')

        if name is not None:
            staff.name = (name or '').strip() or None
            changes.append('имя')

        if role is not None:
            if role not in ROLE_TITLES:
                raise StaffError(f'Неизвестная роль: {role}')
            # Владельца назначает и снимает только владелец: иначе админ с
            # правом «Сотрудники» сделал бы себя владельцем
            if (role == ROLE_OWNER or staff.role == ROLE_OWNER) and role != staff.role                     and (author is None or author.role != ROLE_OWNER):
                raise StaffError('Назначить или снять владельца может только владелец')
            if staff.role == ROLE_OWNER and role != ROLE_OWNER:
                self._check_last_owner(staff)
            staff.role = role
            changes.append(f'роль: {staff.role_title}')

        if permissions is not None:
            staff.permissions = _pack(permissions)
            changes.append('права')

        if is_active is not None:
            if not is_active and staff.role == ROLE_OWNER:
                self._check_last_owner(staff)
            staff.is_active = bool(is_active)
            changes.append('доступ открыт' if is_active else 'доступ закрыт')

        # Права изменились — старый токен больше не годится. Иначе
        # снятая галочка подействует только через месяц, когда токен
        # протухнет сам
        staff.access_changed_at = shop_now()

        self.db.commit()
        self.db.refresh(staff)

        self.log(author, 'staff_update',
                 f'{staff.title}: ' + ', '.join(changes))
        return staff

    def _change_phone(self, author, staff, phone):
        """
        Сменить номер. Старый номер перестаёт пускать сразу: ПИН и
        подтверждение сброшены, человек входит заново звонком с нового
        номера. Номер владельца меняет только владелец — иначе админ с
        правом «Сотрудники» мог бы забрать себе дашборд.
        """
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            raise StaffError('Номер телефона выглядит неправильно')
        if phone == staff.phone:
            return 'номер тот же'
        if staff.role == ROLE_OWNER and (author is None or author.role != ROLE_OWNER):
            raise StaffError('Номер владельца может сменить только владелец')
        taken = self._staff(phone)
        if taken is not None and taken.id != staff.id:
            raise StaffError(f'{phone} уже заведён: {taken.title}')
        old = staff.phone
        staff.phone = phone
        staff.pin_hash = None
        staff.pin_updated_at = None
        staff.pin_failures = 0
        staff.pin_blocked_at = None
        staff.phone_verified_at = None
        return f'номер {old} → {phone}'

    def _check_last_owner(self, staff):
        """
        Не дать закрыть доступ последнему владельцу.

        Иначе дашборд запирается: заводить людей может только владелец,
        а войти под ним уже некому.
        """
        others = self.db.query(StaffUser).filter(
            StaffUser.account_id == self.account_id,
            StaffUser.role == ROLE_OWNER,
            StaffUser.is_active.is_(True),
            StaffUser.id != staff.id).count()
        if others == 0:
            raise StaffError('Это последний владелец. Сначала назначьте '
                             'другого, иначе в дашборд никто не войдёт')

    def ensure_owner(self, phone, name=None):
        """
        Завести первого владельца при запуске сервера.

        Первая учётка не может появиться из дашборда: заводить людей
        имеет право только владелец, а его ещё нет. Поэтому номер
        задаётся переменной окружения.
        """
        phone = normalize_phone(phone)
        if not is_valid_phone(phone):
            return None

        staff = self._staff(phone)
        if staff is not None:
            return staff

        # Владелец уже есть — значит, номер из настроек сервера устарел:
        # владелец сменил его в дашборде. Второго владельца со старым
        # номером не заводим, иначе старый номер снова пускал бы в дашборд
        existing = self.db.query(StaffUser).filter(
            StaffUser.account_id == self.account_id,
            StaffUser.role == ROLE_OWNER).first()
        if existing is not None:
            return existing

        staff = StaffUser(phone=phone, name=(name or '').strip() or None,
                          role=ROLE_OWNER, account_id=self.account_id)
        self.db.add(staff)
        self.db.commit()
        self.db.refresh(staff)
        return staff

    # ------------------------------------------------------------------
    # Журнал
    # ------------------------------------------------------------------

    def log(self, staff, action, detail=None):
        self.db.add(StaffAction(
            account_id=self.account_id,
            staff_id=staff.id if staff else None,
            phone=staff.phone if staff else None,
            action=action,
            detail=detail))
        self.db.commit()

    def actions(self, limit=100):
        return self.db.query(StaffAction).filter(
            StaffAction.account_id == self.account_id).order_by(
            StaffAction.happened_at.desc()).limit(limit).all()


def clean_telegram(value):
    """«@Ivan_Shiny», «t.me/ivan_shiny» → «ivan_shiny». Пусто — убрать ник."""
    text = str(value or '').strip()
    for prefix in ('https://', 'http://', 't.me/', 'telegram.me/', '@'):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    text = text.strip().strip('/').lower()
    if not text:
        return None
    if not text.isascii() or not all(ch.isalnum() or ch == '_' for ch in text) \
            or not 5 <= len(text) <= 32:
        raise StaffError('Ник в Telegram — латиницей, цифрами и «_», от 5 символов, '
                         'например @ivan_shiny')
    return text


def report_chats(db, account_id, kind):
    """
    Чаты людей из «Доступа», которым отмечен этот отчёт. Ник → чат знает
    цех (кто писал боту): он присылает это в настройке telegram_usernames.
    """
    from app.services import tenancy
    from app.services.notify import personal_chat
    if account_id is None:
        return []
    people = db.query(StaffUser).filter(StaffUser.account_id == account_id,
                                        StaffUser.is_active.is_(True),
                                        StaffUser.telegram.isnot(None)).all()
    chats = []
    shops = tenancy.shops_of(db, account_id)
    for person in people:
        if not person.gets_report(kind):
            continue
        for shop in shops:
            chat = personal_chat(db, shop, person.telegram)
            if chat:
                chats.append(chat)
                break
    return list(dict.fromkeys(chats))


def report_usernames(db, account_id):
    """{отчёт: [ники]} — цеху: кому ещё слать сводку по смене, склад, покраску."""
    if account_id is None:
        return {}
    people = db.query(StaffUser).filter(StaffUser.account_id == account_id,
                                        StaffUser.is_active.is_(True),
                                        StaffUser.telegram.isnot(None)).all()
    result = {}
    for kind in REPORT_KINDS:
        nicks = sorted({p.telegram for p in people if p.gets_report(kind)})
        if nicks:
            result[kind] = nicks
    return result


def _pack(permissions):
    """
    Сложить права в строку. Пусто — значит «как у роли».

    Отдельно храним только то, что от роли отличается: иначе при
    изменении набора прав у роли пришлось бы обходить всех людей.
    """
    if permissions is None:
        return None
    chosen = [item for item in permissions if item in ALL_PERMISSIONS]
    return ','.join(chosen) if chosen else None
