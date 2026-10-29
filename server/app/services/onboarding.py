"""
Запуск новой точки: коды подключения, заказчики, программа для скачивания.

Решение владельца 27.10.2026: точки будут ставить люди, которые плохо
разбираются в компьютере. Поэтому ни SSH, ни ключа из 43 знаков:

    «Заказчики» → «Новый заказчик»   — название и телефон владельца
          ↓ код из 8 цифр и сообщение со ссылкой
    setup.ДОМЕН                      — по коду скачивается программа
          ↓
    программа цеха → тот же код      — получает ключ обмена сама
          ↓
    дашборд организации              — владелец входит по своему номеру

Код срабатывает один раз и живёт 48 часов. Ключ обмена при этом не
видит никто: он рождается на сервере и уходит прямо в программу.
Старый компьютер точки работает, пока код не введут на новом, —
переподключение не останавливает обмен ни на минуту.
"""
import hashlib
import json
import os
import re
import secrets
from datetime import timedelta

from app.config import settings
from app.models import Account, Shop, AccountDomain, ConnectCode, ConnectAttempt, StaffUser
from app.models.account import ROLE_LK, ROLE_ADMIN, DOMAIN_ACTIVE, KIND_OWN
from app.models.staff import ROLE_OWNER
from app.services import billing, tenancy
from app.utils import (now as shop_now, normalize_phone, is_valid_phone,
                       format_phone)

CODE_HOURS = 48
CODE_DIGITS = 8

# Неверных кодов: с одного адреса за 15 минут и со всех за час. Кодов
# сто миллионов, действующих — единицы; с таким пределом угадать
# нельзя, а ошибиться цифрой пару раз можно спокойно
FAILS_PER_ADDRESS = 10
FAILS_TOTAL = 300

PROGRAM_FILE = 'TireShop.exe'
# Больше — это не наша программа: сейчас она весит около 40 МБ
PROGRAM_MAX_BYTES = 200 * 1024 * 1024
PART_MAX_BYTES = 4 * 1024 * 1024


class CodeError(ValueError):
    """Код не подошёл. Текст — для человека."""


class TooManyTries(CodeError):
    pass


class OnboardingError(ValueError):
    """Заказчика или точку завести нельзя. Текст — для человека."""


# ----------------------------------------------------------------------
# Коды
# ----------------------------------------------------------------------

def clean_code(raw):
    """«4827 1935», «4827-1935» -> «48271935»."""
    return re.sub(r'\D', '', raw or '')


def pretty_code(code):
    return f'{code[:4]} {code[4:]}' if code and len(code) == CODE_DIGITS else code


def _live(db):
    now = shop_now()
    return db.query(ConnectCode).filter(
        ConnectCode.used_at.is_(None),
        ConnectCode.cancelled_at.is_(None),
        ConnectCode.expires_at > now)


def active_code(db, shop):
    return _live(db).filter(ConnectCode.shop_id == shop.id).order_by(
        ConnectCode.id.desc()).first()


def cancel_code(db, shop):
    for row in _live(db).filter(ConnectCode.shop_id == shop.id).all():
        row.cancelled_at = shop_now()
    db.commit()


def issue_code(db, shop, staff_id=None):
    """
    Новый код для точки. Прежний действующий отменяется: код у точки
    один, иначе непонятно, какой из разосланных ещё в силе.
    """
    if shop.account is not None and not shop.account.is_active:
        raise OnboardingError('Организация отключена')

    now = shop_now()
    for row in _live(db).filter(ConnectCode.shop_id == shop.id).all():
        row.cancelled_at = now

    taken = {row.code for row in _live(db).all()}
    while True:
        code = ''.join(str(secrets.randbelow(10)) for _ in range(CODE_DIGITS))
        # С нуля не начинаем: Excel и телефоны съедают ведущий ноль
        if code[0] != '0' and code not in taken:
            break

    row = ConnectCode(shop_id=shop.id, code=code, created_at=now,
                      expires_at=now + timedelta(hours=CODE_HOURS),
                      created_by=staff_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _check_tries(db, address):
    now = shop_now()
    mine = db.query(ConnectAttempt).filter(
        ConnectAttempt.address == address,
        ConnectAttempt.at > now - timedelta(minutes=15)).count()
    if mine >= FAILS_PER_ADDRESS:
        raise TooManyTries('Слишком много неверных кодов. Попробуйте через 15 минут')
    total = db.query(ConnectAttempt).filter(
        ConnectAttempt.at > now - timedelta(hours=1)).count()
    if total >= FAILS_TOTAL:
        raise TooManyTries('Сейчас проверить код нельзя. Попробуйте через час')


def _failed(db, address):
    now = shop_now()
    db.add(ConnectAttempt(address=(address or '?')[:64], at=now))
    # Старые попытки больше ничего не решают
    db.query(ConnectAttempt).filter(
        ConnectAttempt.at < now - timedelta(days=1)).delete(synchronize_session=False)
    db.commit()


def find(db, raw, address):
    """
    Действующий код. Не тратит его: так страница скачивания и программа
    могут показать «Найдено: …» до подключения.
    """
    address = (address or '?')[:64]
    _check_tries(db, address)

    code = clean_code(raw)
    if len(code) != CODE_DIGITS:
        _failed(db, address)
        raise CodeError('В коде 8 цифр')

    row = db.query(ConnectCode).filter(ConnectCode.code == code).order_by(
        ConnectCode.id.desc()).first()
    if row is None:
        _failed(db, address)
        raise CodeError('Код не найден. Проверьте цифры или попросите новый')

    shop = row.shop
    if (row.used_at or row.cancelled_at or row.expires_at <= shop_now()
            or shop is None or not shop.is_active
            or (shop.account is not None and not shop.account.is_active)):
        raise CodeError('Код уже не действует. Попросите новый у того, кто его прислал')
    return row


def redeem(db, raw, address):
    """
    Ввели код в программе цеха: точке новый ключ обмена, код погашен.
    Возвращает (точка, ключ). Ключ открытым — только в этом ответе.
    """
    row = find(db, raw, address)
    shop = row.shop
    key = tenancy.generate_key()
    shop.sync_key_hash = tenancy.hash_key(key)
    shop.sync_key_set_at = shop_now()
    row.used_at = shop_now()
    db.commit()
    return shop, key


# ----------------------------------------------------------------------
# Что сказать человеку
# ----------------------------------------------------------------------

def addresses(db, account):
    """
    По каким адресам открываются запись и дашборд организации: свой
    домен, если он уже работает, иначе наш поддомен.
    """
    home = tenancy.home_account(db)
    if home is not None and account.id == home.id and settings.HOME_HOSTS:
        result = {}
        for host in settings.HOME_HOSTS:
            role = ROLE_ADMIN if host.startswith('admin.') else ROLE_LK
            result.setdefault(role, f'https://{host}')
        return result

    result = {role: f'https://{name}' for role, name in tenancy.our_names(account).items()}
    for row in account.domains:
        if row.kind == KIND_OWN and row.status == DOMAIN_ACTIVE:
            result[row.role] = f'https://{row.name}'
    return result


def setup_url(db):
    """
    Ссылка на страницу скачивания. setup.ДОМЕН — когда у него есть
    сертификат; до того та же страница на lk. сервера.
    """
    host = tenancy.setup_host()
    if host:
        row = db.query(AccountDomain).filter(AccountDomain.name == host).first()
        if row is not None and row.status == DOMAIN_ACTIVE:
            return f'https://{host}'
    for name in settings.HOME_HOSTS:
        if not name.startswith('admin.'):
            return f'https://{name}/setup'
    return '/setup'


def mask_phone(phone):
    """+7 (916) 123-45-12 -> +7 (916) ···-··-12: виден, но не целиком."""
    text = format_phone(phone) if phone else ''
    total = sum(char.isdigit() for char in text)
    out, seen = [], 0
    for char in text:
        if char.isdigit():
            seen += 1
            # Код страны и оператора — видно, последние две — видно
            if 4 < seen <= total - 2:
                char = '·'
        out.append(char)
    return ''.join(out)


def owners(db, account):
    from app.models import StaffUser
    return db.query(StaffUser).filter(
        StaffUser.account_id == account.id,
        StaffUser.role == ROLE_OWNER,
        StaffUser.is_active.is_(True)).order_by(StaffUser.id).all()


def describe(db, shop):
    """Чья точка и куда идти дальше — для «Найдено» и последнего экрана."""
    account = shop.account
    places = addresses(db, account)
    people = owners(db, account)
    return {
        'account': (account.brand_name or account.name),
        'shop': shop.name,
        'shop_slug': shop.slug,
        'lk_url': places.get(ROLE_LK),
        'admin_url': places.get(ROLE_ADMIN),
        'owner_phone': mask_phone(people[0].phone) if people else None,
    }


def invite_text(db, shop, code_row):
    """Сообщение для WhatsApp или Telegram — одним куском, как есть."""
    account = shop.account
    until = code_row.expires_at
    return (
        f'Программа для «{account.brand_name or account.name}», точка «{shop.name}».\n\n'
        f'1. Откройте {setup_url(db)}\n'
        f'2. Введите код {pretty_code(code_row.code)} и скачайте программу.\n'
        f'3. Запустите её и введите этот же код — дальше она всё спросит сама.\n\n'
        f'Код срабатывает один раз и действует до {until:%d.%m, %H:%M}.')


def code_out(db, shop, row):
    if row is None:
        return None
    return {
        'code': pretty_code(row.code),
        'expires_at': row.expires_at.isoformat(),
        'text': invite_text(db, shop, row),
        'setup_url': setup_url(db),
    }


# ----------------------------------------------------------------------
# Заказчики
# ----------------------------------------------------------------------

def is_platform_owner(db, staff):
    """
    Видит ли сотрудник «Заказчиков»: владелец организации, которая
    держит сервер. Задан SERVER_OWNER_PHONE — только этот номер.
    """
    if staff is None or not staff.is_active or staff.role != ROLE_OWNER:
        return False
    home = tenancy.home_account(db)
    if home is None or staff.account_id != home.id:
        return False
    # Отмечен флагом — он и владелец сервера, с каким бы номером ни был
    if staff.is_platform_owner:
        return True
    flagged = db.query(StaffUser).filter(StaffUser.account_id == home.id,
                                         StaffUser.is_platform_owner.is_(True)).count()
    if flagged:
        return False
    owner = normalize_phone(settings.OWNER_PHONE) if settings.OWNER_PHONE else ''
    return not owner or staff.phone == owner


_SLUG_RE = re.compile(r'^[a-z0-9]([a-z0-9-]{0,46}[a-z0-9])?$')


def check_slug(db, slug):
    slug = (slug or '').strip().lower()
    if not _SLUG_RE.match(slug):
        raise OnboardingError('Короткое имя: латинские буквы, цифры и дефис. Пример: koleso')
    if not tenancy._slug_fits_address(slug):
        raise OnboardingError('Это имя занято под служебный адрес, выберите другое')
    if slug in tenancy.taken_slugs(db):
        raise OnboardingError('Это имя уже занято')
    return slug


def create_customer(db, name, owner_phone, slug=None, shop_name=None,
                    paid_until=None, staff_id=None):
    """
    Новая организация: первая точка без ключа (ключ даст код), владелец
    для входа в дашборд и код подключения. Возвращает (аккаунт, точка, код).
    """
    name = re.sub(r'\s+', ' ', name or '').strip()
    if not name:
        raise OnboardingError('Впишите название')
    phone = normalize_phone(owner_phone)
    if not is_valid_phone(phone):
        raise OnboardingError('Телефон владельца выглядит неправильно')
    wanted = check_slug(db, slug) if slug else None

    from app.services.staff_service import StaffService

    account, shop, _key = tenancy.create_account(db, name[:200], (shop_name or name)[:200],
                                                 slug=wanted)
    # Ключа нет ни у кого: его получит программа по коду
    shop.sync_key_hash = None
    shop.sync_key_set_at = None
    db.commit()

    StaffService(db, account.id).ensure_owner(phone)
    if paid_until is not None:
        billing.record_payment(db, account, 0, until=paid_until,
                               comment='Срок при заведении')
    tenancy.forget_hosts()

    return account, shop, issue_code(db, shop, staff_id)


def add_point(db, account, name, staff_id=None):
    name = re.sub(r'\s+', ' ', name or '').strip()
    if not name:
        raise OnboardingError('Впишите название точки')
    shop, _key = tenancy.add_shop(db, account, name[:200])
    shop.sync_key_hash = None
    shop.sync_key_set_at = None
    db.commit()
    return shop, issue_code(db, shop, staff_id)


def point_out(db, shop):
    """Точка для списка: на связи, давно нет или ждёт подключения."""
    row = active_code(db, shop)
    if shop.last_sync_at is None:
        state, title = 'waiting', 'Ждёт подключения'
    elif shop_now() - shop.last_sync_at < timedelta(hours=1):
        state, title = 'online', 'На связи'
    else:
        state, title = 'offline', 'Нет связи'
    return {
        'id': shop.id, 'name': shop.name, 'slug': shop.slug,
        'is_active': shop.is_active,
        'state': state, 'state_title': title,
        'last_sync_at': shop.last_sync_at.isoformat() if shop.last_sync_at else None,
        'code': code_out(db, shop, row),
    }


def account_out(db, account):
    status = billing.state(account)
    places = addresses(db, account)
    return {
        'id': account.id, 'name': account.name, 'slug': account.slug,
        'is_active': account.is_active,
        'is_home': (tenancy.home_account(db) or account).id == account.id,
        'billing': {
            'state': status['state'], 'title': status['title'],
            'paid_until': status['paid_until'].isoformat() if status['paid_until'] else None,
            'days_left': status['days_left'],
            'reason': status.get('reason'),
        },
        'lk_url': places.get(ROLE_LK),
        'admin_url': places.get(ROLE_ADMIN),
        'owners': [format_phone(person.phone) for person in owners(db, account)],
        'shops': [point_out(db, shop) for shop in sorted(account.shops, key=lambda s: s.id)],
        'payments': [{
            'amount': payment.amount,
            'paid_at': payment.paid_at.isoformat(),
            'period_to': payment.period_to.isoformat() if payment.period_to else None,
            'comment': payment.comment,
        } for payment in account.payments[:10]],
    }


# ----------------------------------------------------------------------
# Программа для скачивания
# ----------------------------------------------------------------------
#
# Файл в 40 МБ одним запросом не пролезает: nginx пускает до 10 МБ.
# Дашборд режет его на куски по 4 МБ, сервер складывает их по порядку
# и только целиком, проверив, кладёт на место прежней версии.

def _dir():
    return settings.DOWNLOAD_DIR


def program_path():
    return os.path.join(_dir(), PROGRAM_FILE)


def program_info():
    path = program_path()
    if not os.path.isfile(path):
        return {'exists': False}
    meta = {}
    try:
        with open(path + '.json', encoding='utf-8') as file:
            meta = json.load(file)
    except (OSError, ValueError):
        pass
    return {
        'exists': True,
        'size': os.path.getsize(path),
        'uploaded_at': meta.get('uploaded_at'),
        'sha256': meta.get('sha256'),
    }


_UPLOAD_RE = re.compile(r'^[0-9a-f]{32}$')


def _part_path(upload_id):
    if not _UPLOAD_RE.match(upload_id or ''):
        raise OnboardingError('Загрузка не найдена, начните заново')
    return os.path.join(_dir(), f'.upload-{upload_id}')


def start_upload():
    os.makedirs(_dir(), exist_ok=True)
    # Брошенные загрузки старше суток — мусор
    limit = shop_now().timestamp() - 86400
    for name in os.listdir(_dir()):
        if name.startswith('.upload-'):
            path = os.path.join(_dir(), name)
            try:
                if os.path.getmtime(path) < limit:
                    os.remove(path)
            except OSError:
                pass
    upload_id = secrets.token_hex(16)
    open(_part_path(upload_id), 'wb').close()
    return upload_id


def add_part(upload_id, offset, data):
    path = _part_path(upload_id)
    if not os.path.isfile(path):
        raise OnboardingError('Загрузка не найдена, начните заново')
    if len(data) > PART_MAX_BYTES:
        raise OnboardingError('Кусок файла больше 4 МБ')
    size = os.path.getsize(path)
    if offset != size:
        # Кусок пришёл второй раз или потерялся предыдущий: дашборд
        # продолжит с того места, которое назовём
        raise OnboardingError(f'Ожидался кусок с {size}')
    if size + len(data) > PROGRAM_MAX_BYTES:
        raise OnboardingError('Файл больше 200 МБ — это не программа цеха')
    with open(path, 'ab') as file:
        file.write(data)
    return size + len(data)


def finish_upload(upload_id, size):
    path = _part_path(upload_id)
    if not os.path.isfile(path):
        raise OnboardingError('Загрузка не найдена, начните заново')
    if os.path.getsize(path) != size:
        os.remove(path)
        raise OnboardingError('Файл дошёл не целиком, загрузите заново')

    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        head = file.read(2)
        file.seek(0)
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    # Программа Windows начинается с «MZ»: так случайно выбранная
    # картинка или архив не подменят программу у всех новых точек
    if head != b'MZ':
        os.remove(path)
        raise OnboardingError('Это не программа Windows (.exe)')

    os.replace(path, program_path())
    with open(program_path() + '.json', 'w', encoding='utf-8') as file:
        json.dump({'uploaded_at': shop_now().isoformat(),
                   'sha256': digest.hexdigest()}, file)
    return program_info()
