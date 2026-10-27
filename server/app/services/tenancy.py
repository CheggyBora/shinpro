"""
Кто пришёл: точка, аккаунт и первая настройка сервера.

Всё, что сервер отдаёт или принимает, принадлежит какой-то точке или
какому-то аккаунту. Определяется это не из запроса, а из того, чем
человек или программа доказали, кто они:

    программа цеха  →  ключ обмена  →  точка  →  аккаунт
    сотрудник       →  токен        →  аккаунт
    клиент          →  токен        →  аккаунт
    страница записи →  адрес /z/имя →  точка  →  аккаунт

Подставить чужой номер в запрос бесполезно: сервер берёт точку из
ключа, а не из тела запроса.
"""
import hashlib
import hmac
import os
import re
import secrets
import time
from contextvars import ContextVar

from app.config import settings
from app.models import Account, Shop, AccountDomain
from app.models.account import (ROLE_LK, ROLE_ADMIN, ROLE_SETUP, KIND_OWN,
                                DOMAIN_WAITING)
from app.utils import now as shop_now


def hash_key(key):
    """
    Отпечаток ключа обмена.

    В базе лежит он, а не сам ключ: украв базу сервера, чужие ключи от
    всех цехов сразу не получишь. Соль не нужна — ключ длинный и
    случайный, перебирать его по словарю нечего.
    """
    return hashlib.sha256((key or '').encode('utf-8')).hexdigest()


def generate_key():
    """Новый ключ обмена. Показывается один раз, при создании точки."""
    return secrets.token_urlsafe(32)


def make_slug(name, taken=()):
    """
    Короткое имя для адреса: «Шиномонтаж «РИФ»» -> «shinomontazh-rif».

    Кириллица переводится в латиницу: адрес попадает в SMS и в
    переписку, и там кириллица превращается в проценты.
    """
    table = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e',
        'ё': 'e', 'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k',
        'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'c',
        'ч': 'ch', 'ш': 'sh', 'щ': 'sch', 'ъ': '', 'ы': 'y', 'ь': '',
        'э': 'e', 'ю': 'yu', 'я': 'ya',
    }

    result = ''.join(table.get(char, char) for char in (name or '').lower())
    result = re.sub(r'[^a-z0-9]+', '-', result).strip('-')[:48]

    if not result:
        result = 'shop'

    # Имя занято — добавляем номер, а не отказываем: две точки могут
    # называться одинаково, и это нормально
    base, number = result, 2
    while result in taken or not _slug_fits_address(result):
        result = f'{base}-{number}'
        number += 1

    return result


# Имена, которые не может получить организация: lk.rif-service.ru и
# admin.rif-service.ru — свои адреса сервера, остальные просто служебные
RESERVED_LABELS = {'lk', 'admin', 'www', 'api', 'mail', 'smtp', 'ftp',
                   'ns1', 'ns2', 'static', 'cdn', 'd', 'z', 'setup'}
ADMIN_SUFFIX = '-admin'


def _slug_fits_address(slug):
    """
    Годится ли имя для адреса организации: koleso -> koleso.rif-service.ru.

    «-admin» в конце занято под дашборд: у «x» дашборд x-admin, и
    организация «x admin» получила бы чужой адрес.
    """
    return slug not in RESERVED_LABELS and not slug.endswith(ADMIN_SUFFIX)


def taken_slugs(db):
    return {value for (value,) in db.query(Shop.slug).all()} | \
           {value for (value,) in db.query(Account.slug).all()}


def shop_by_sync_key(db, key):
    """Точка, предъявившая этот ключ. None — ключ никому не принадлежит."""
    if not key:
        return None

    shop = db.query(Shop).filter(
        Shop.sync_key_hash == hash_key(key)).first()

    if shop is None or not shop.is_active:
        return None

    if shop.account is not None and not shop.account.is_active:
        return None

    return shop


def create_account(db, name, shop_name=None, key=None, slug=None):
    """
    Завести аккаунт с первой точкой. Возвращает (аккаунт, точка, ключ).

    Ключ возвращается открытым один раз: в базе остаётся только
    отпечаток, и показать ключ второй раз сервер не сможет.
    """
    taken = taken_slugs(db)

    # slug — короткое имя, выбранное в «Заказчиках» (проверено там):
    # занимаем его до точки, чтобы точка «Колесо» не получила то же имя
    account = Account(name=name, slug=slug or make_slug(name, taken))
    db.add(account)
    db.flush()

    taken.add(account.slug)
    shop_name = shop_name or name
    key = key or generate_key()

    shop = Shop(account_id=account.id, name=shop_name,
                slug=make_slug(shop_name, taken),
                sync_key_hash=hash_key(key),
                sync_key_set_at=shop_now())
    db.add(shop)
    db.commit()
    db.refresh(account)
    db.refresh(shop)

    return account, shop, key


def add_shop(db, account, name, key=None):
    """Добавить точку существующему аккаунту."""
    key = key or generate_key()

    shop = Shop(account_id=account.id, name=name,
                slug=make_slug(name, taken_slugs(db)),
                sync_key_hash=hash_key(key),
                sync_key_set_at=shop_now())
    db.add(shop)
    db.commit()
    db.refresh(shop)

    return shop, key


def bootstrap(db):
    """
    Первая точка при запуске сервера.

    Пока точек нет, а в настройках задан ключ обмена, заводим аккаунт и
    одну точку с этим ключом. Так сервер, поднятый по инструкции из
    README, сразу готов принимать цех — без консоли и SQL.

    Когда точки уже есть, не делаем ничего: ключ из настроек больше не
    главнее базы.
    """
    if db.query(Shop).count():
        return None

    if not settings.SYNC_KEY:
        return None

    name = settings.SHOP_NAME or 'Шиномонтаж'
    account, shop, _key = create_account(db, name, name, key=settings.SYNC_KEY)
    return shop


def only_shop(db, account_id=None):
    """
    Единственная точка, если она одна.

    Нужно там, где точку неоткуда взять: публичная страница записи без
    имени в адресе. Когда точек несколько, возвращаем None — пусть
    вызывающий спросит, о какой речь, а не гадает.

    account_id — точки только этой организации: на её адресе «одна
    точка» значит одна у неё, а не на всём сервере.
    """
    query = db.query(Shop).filter(Shop.is_active.is_(True))
    if account_id is not None:
        query = query.filter(Shop.account_id == account_id)
    shops = query.limit(2).all()
    return shops[0] if len(shops) == 1 else None


def page_shop(db, wanted=None, host=None):
    """
    Точка, о которой открыта страница: из адреса /z/имя или, если имени
    нет, единственная точка организации, на чей адрес зашли.

    Точку другой организации на чужом адресе не отдаём.
    """
    by_host = account_of_host(db, current_host() if host is None else host)

    if wanted:
        shop = shop_by_slug(db, wanted)
        if shop is not None and by_host is not None and shop.account_id != by_host:
            return None
        return shop

    return only_shop(db, by_host)


def shop_by_slug(db, slug):
    if not slug:
        return None

    shop = db.query(Shop).filter(Shop.slug == slug,
                                 Shop.is_active.is_(True)).first()
    if shop is None:
        # По имени аккаунта тоже пускаем: у сети из одной точки имена
        # совпадают, и человек наберёт то, которое помнит
        account = db.query(Account).filter(Account.slug == slug).first()
        if account is not None and account.shops:
            shop = next((row for row in account.shops if row.is_active), None)

    return shop


def shops_of(db, account_id):
    """Работающие точки аккаунта — то, из чего выбирает клиент."""
    if account_id is None:
        return []

    return db.query(Shop).filter(
        Shop.account_id == account_id,
        Shop.is_active.is_(True)).order_by(Shop.id).all()


class ShopNeeded(Exception):
    """
    У аккаунта несколько точек, а в запросе не сказано, о какой речь.

    Отдельный тип, чтобы приложение показало выбор точки, а не ошибку:
    человек ничего не сделал неправильно.
    """


def shop_for(db, account_id, wanted=None):
    """
    Точка, о которой идёт речь в запросе клиента.

    wanted — имя или номер точки из запроса. Чужую точку подставить
    нельзя: берём только из точек своего аккаунта.
    """
    shops = shops_of(db, account_id)
    if not shops:
        return None

    if wanted not in (None, ''):
        for shop in shops:
            if str(shop.id) == str(wanted) or shop.slug == str(wanted):
                return shop
        raise ShopNeeded('Такой точки нет')

    if len(shops) == 1:
        return shops[0]

    raise ShopNeeded('Выберите, в какую точку')


def key_matches_legacy(key):
    """
    Совпадает ли ключ с тем, что задан в настройках сервера.

    Нужно на время перехода: сервер уже знает про точки, но в цеху
    остался ключ из переменной окружения.
    """
    if not settings.SYNC_KEY or not key:
        return False
    return hmac.compare_digest(key, settings.SYNC_KEY)


def account_for(db, wanted=None, host=None):
    """
    Аккаунт, о котором идёт речь в запросе.

    wanted — короткое имя точки или сети из заголовка X-Shop. host —
    адрес, на который зашли: у каждой организации свой (koleso.rif-
    service.ru, zapis.koleso.ru), и по нему ясно, чей это кабинет.

    Пусто и аккаунт на сервере один — берём его: заставлять единственный
    шиномонтаж всюду писать своё имя незачем.

    Пусто, адрес не наш и аккаунтов несколько — отказываем. Угадывать,
    в чей кабинет человек хотел войти, нельзя ни в коем случае.
    """
    by_host = account_of_host(db, current_host() if host is None else host)

    if wanted:
        shop = shop_by_slug(db, wanted)
        if shop is not None:
            found = shop.account_id
        else:
            account = db.query(Account).filter(Account.slug == wanted).first()
            if account is None:
                raise ShopNeeded('Такого шиномонтажа нет')
            found = account.id

        # На адресе «Колеса» точку «РИФа» не открываем: страница
        # показала бы чужое название под своим логотипом
        if by_host is not None and found != by_host:
            raise ShopNeeded('Такого шиномонтажа нет')
        return found

    if by_host is not None:
        return by_host

    accounts = db.query(Account).filter(
        Account.is_active.is_(True)).limit(2).all()

    if len(accounts) == 1:
        return accounts[0].id
    if not accounts:
        return None

    raise ShopNeeded('Укажите, какой шиномонтаж')

# ----------------------------------------------------------------------
# Удаление
# ----------------------------------------------------------------------

def shop_contents(db, shop):
    """Что лежит в точке. Нужно, чтобы показать это перед удалением."""
    from app.models import (Appointment, BookingDay, QueueSnapshot,
                            SalaryPayout, ShopEmployee, ShopSetting,
                            ShopShift, StoredSet, Visit, OrderPhoto,
                            MasterDevice, CashOrder)

    counts = {}
    for title, model in (('нарядов', Visit),
                         ('записей', Appointment),
                         ('комплектов', StoredSet),
                         ('смен', ShopShift),
                         ('мастеров', ShopEmployee),
                         ('выплат', SalaryPayout),
                         ('дней записи', BookingDay),
                         ('снимков очереди', QueueSnapshot),
                         ('фото', OrderPhoto),
                         ('телефонов мастеров', MasterDevice),
                         ('кассовых ордеров', CashOrder),
                         ('настроек', ShopSetting)):
        counts[title] = db.query(model).filter(
            model.shop_id == shop.id).count()

    return counts


def drop_shop(db, shop):
    """
    Удалить точку со всем, что к ней относится.

    Нужно после проверки: тестовую точку заводят, гоняют на ней обмен и
    убирают. Оставлять её нельзя — она будет висеть в выборе точек
    дашборда и путать.

    Клиентов не трогаем: они принадлежат заказчику, а не точке, и
    могли приезжать на обе. Разбираться, чей клиент, здесь нельзя.
    """
    from app.models import (Appointment, BookingDay, QueueSnapshot,
                            SalaryPayout, ShopEmployee, ShopSetting,
                            ShopShift, StockItem, StoredSet, Visit,
                            Task, Counterparty, CashOrder, Arrival,
                            OrderPhoto, MasterDevice, OpenOrder,
                            ShopClient, ShopCar, ConnectCode)
    from app.services.photos import full_path

    # Наряды через объекты, а не одним запросом: у них есть позиции и
    # начисления, и убрать их должен каскад, описанный в модели
    for visit in db.query(Visit).filter(Visit.shop_id == shop.id).all():
        db.delete(visit)
    db.flush()

    # Машины с телефона ссылаются на снимки — их раньше снимков.
    # Телефоны мастеров и открытые наряды: пропуск в удалённую точку
    # оставлять нельзя
    for model in (Appointment, BookingDay, StoredSet, SalaryPayout,
                  ShopEmployee, ShopShift, QueueSnapshot, ShopSetting,
                  StockItem, Task, Counterparty, CashOrder, Arrival,
                  MasterDevice, OpenOrder, ShopClient, ShopCar, ConnectCode):
        db.query(model).filter(model.shop_id == shop.id).delete(
            synchronize_session=False)

    # Снимки: строки сейчас, файлы — после того как база согласилась.
    # Сорвись удаление — файлы остались бы без строк, наоборот хуже
    photos = db.query(OrderPhoto).filter(OrderPhoto.shop_id == shop.id).all()
    files = [full_path(photo) for photo in photos]
    for photo in photos:
        db.delete(photo)

    db.delete(shop)
    db.commit()

    for path in files:
        try:
            os.remove(path)
        except OSError:
            pass        # файла уже нет — тем лучше


def drop_account(db, account):
    """
    Удалить заказчика целиком: точки, клиентов, персонал, уведомления.

    Отдельная команда, а не повторение drop_shop в цикле: у заказчика
    есть своё — клиенты, подписки на уведомления, учётки персонала, —
    и без них в базе остался бы мусор, привязанный к тому, чего нет.
    """
    from app.models import (AccountPayment, Client, Car, Device, LoginCode,
                            Notice, PushSubscription, StaffAction, StaffUser)

    for shop in shops_of(db, account.id):
        drop_shop(db, shop)

    clients = [row.id for row in db.query(Client).filter(
        Client.account_id == account.id).all()]

    if clients:
        # Эти привязаны к человеку
        for model in (PushSubscription, Notice, Car, Device):
            db.query(model).filter(model.client_id.in_(clients)).delete(
                synchronize_session=False)

        db.query(Client).filter(Client.account_id == account.id).delete(
            synchronize_session=False)

    # А коды входа — к заказчику: их запрашивают до того, как человек
    # заведён, и клиента у них может не быть вовсе
    db.query(LoginCode).filter(LoginCode.account_id == account.id).delete(
        synchronize_session=False)

    staff = [row.id for row in db.query(StaffUser).filter(
        StaffUser.account_id == account.id).all()]
    if staff:
        db.query(StaffAction).filter(StaffAction.staff_id.in_(staff)).delete(
            synchronize_session=False)
        db.query(StaffUser).filter(
            StaffUser.account_id == account.id).delete(
            synchronize_session=False)

    db.query(AccountPayment).filter(
        AccountPayment.account_id == account.id).delete(
        synchronize_session=False)

    db.delete(account)
    db.commit()


# ----------------------------------------------------------------------
# Адреса организаций
# ----------------------------------------------------------------------
#
# У каждой организации свой сайт записи и свой дашборд (решение
# владельца 27.10.2026). Сервер один, и чей кабинет открыт, он узнаёт по
# адресу:
#
#     koleso.rif-service.ru        -> запись «Колеса»   (наш поддомен)
#     koleso-admin.rif-service.ru  -> дашборд «Колеса»
#     zapis.koleso.ru              -> запись «Колеса»   (свой домен)
#     lk.rif-service.ru            -> запись того, кто держит сервер

# Адрес текущего запроса. Ставит прослойка в main.py: передавать его
# через каждую функцию, которой нужна точка, значило бы протащить его в
# два десятка мест и где-нибудь забыть
REQUEST_HOST = ContextVar('request_host', default='')


def current_host():
    return REQUEST_HOST.get()


_HOST_RE = re.compile(
    r'^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$')

# Адрес -> (аккаунт, роль) на минуту. Спрашивается на каждом входе и
# каждой странице записи, а адреса меняются раз в месяцы
_host_cache = {}
_HOST_CACHE_SECONDS = 60


def clean_host(host):
    """«Koleso.Rif-Service.ru:443» -> «koleso.rif-service.ru». Мусор — пусто."""
    name = (host or '').strip().lower()
    if name.startswith('['):
        return ''
    name = name.split(':', 1)[0].rstrip('.')
    return name if _HOST_RE.match(name) else ''


def our_names(account):
    """Наши адреса организации: запись и дашборд. Пусто — домен сервера не задан."""
    base = settings.PLATFORM_DOMAIN
    if not base or not account.slug or not _slug_fits_address(account.slug):
        return {}
    return {ROLE_LK: f'{account.slug}.{base}',
            ROLE_ADMIN: f'{account.slug}{ADMIN_SUFFIX}.{base}'}


def home_account(db):
    """Организация того, кто держит сервер: ей принадлежат lk. и admin."""
    slug = os.environ.get('SERVER_HOME_ACCOUNT', '').strip()
    query = db.query(Account)
    if slug:
        return query.filter(Account.slug == slug).first()
    return query.order_by(Account.id).first()


def host_target(db, host):
    """
    Чей это адрес и для чего: (аккаунт, роль). Не наш адрес — (None, None).

    Роль: ROLE_LK — запись и кабинет клиента, ROLE_ADMIN — дашборд.
    """
    name = clean_host(host)
    if not name:
        return None, None

    cached = _host_cache.get(name)
    if cached and time.monotonic() - cached[0] < _HOST_CACHE_SECONDS:
        return cached[1]

    result = _host_target(db, name)
    _host_cache[name] = (time.monotonic(), result)
    return result


def setup_host():
    """
    Адрес страницы скачивания программы: setup.rif-service.ru. Общий на
    сервер, не организации: скачивают по коду, а код и говорит, чья точка.
    """
    base = settings.PLATFORM_DOMAIN
    return f'setup.{base}' if base else None


def _host_target(db, name):
    if name == setup_host():
        account = home_account(db)
        return (account.id, ROLE_SETUP) if account is not None else (None, None)

    row = db.query(AccountDomain).filter(AccountDomain.name == name).first()
    if row is not None:
        return row.account_id, row.role

    if name in settings.HOME_HOSTS:
        account = home_account(db)
        if account is None:
            return None, None
        # Дашборд — тот из домашних адресов, что начинается с admin.
        role = ROLE_ADMIN if name.startswith('admin.') else ROLE_LK
        return account.id, role

    base = settings.PLATFORM_DOMAIN
    if base and name.endswith('.' + base):
        label = name[:-len(base) - 1]
        if '.' not in label:
            role = ROLE_LK
            if label.endswith(ADMIN_SUFFIX):
                label, role = label[:-len(ADMIN_SUFFIX)], ROLE_ADMIN
            if _slug_fits_address(label):
                account = db.query(Account).filter(Account.slug == label).first()
                if account is not None:
                    return account.id, role

    return None, None


def account_of_host(db, host):
    return host_target(db, host)[0]


def forget_hosts():
    """Сбросить запомненные адреса: после правки адресов в дашборде."""
    _host_cache.clear()


class DomainError(ValueError):
    """Адрес не подходит. Текст — для человека."""


def add_domain(db, account, name, role=ROLE_LK):
    """
    Подключить свой домен организации. Работать он начнёт, когда у
    регистратора появится запись на наш сервер и выпустится сертификат —
    это делает tire-domains по таймеру.
    """
    name = (name or '').strip().lower()
    for prefix in ('https://', 'http://'):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = name.split('/', 1)[0].rstrip('.')
    # «запись.колесо.рф» — в том виде, в каком его знает интернет
    try:
        name = name.encode('idna').decode('ascii')
    except UnicodeError:
        raise DomainError('Адрес выглядит неправильно. Пример: zapis.koleso.ru')

    if role not in (ROLE_LK, ROLE_ADMIN):
        raise DomainError('Непонятно, для чего адрес')
    if clean_host(name) != name:
        raise DomainError('Адрес выглядит неправильно. Пример: zapis.koleso.ru')

    base = settings.PLATFORM_DOMAIN
    if name in settings.HOME_HOSTS or (base and (name == base or name.endswith('.' + base))):
        raise DomainError('Это наш адрес, его подключать не нужно')

    taken = db.query(AccountDomain).filter(AccountDomain.name == name).first()
    if taken is not None:
        if taken.account_id == account.id:
            raise DomainError('Этот адрес уже подключён')
        raise DomainError('Этот адрес занят')

    row = AccountDomain(account_id=account.id, name=name, role=role,
                        kind=KIND_OWN, status=DOMAIN_WAITING,
                        note='Ждём запись в настройках домена')
    db.add(row)
    db.commit()
    forget_hosts()
    return row


def remove_domain(db, account, domain_id):
    row = db.query(AccountDomain).filter(
        AccountDomain.id == domain_id,
        AccountDomain.account_id == account.id,
        AccountDomain.kind == KIND_OWN).first()
    if row is None:
        raise DomainError('Такого адреса нет')
    db.delete(row)
    db.commit()
    forget_hosts()


def domains_plan(db):
    """
    Какие адреса должны работать: для tire-domains, который заводит их
    в nginx и выпускает сертификаты. [(имя, роль, свой ли)].

    Наши поддомены — у каждой работающей организации, кроме той, что
    держит сервер: у неё свои lk. и admin.
    """
    plan = []
    # Страница скачивания — правила те же, что у записи (lk.inc)
    if setup_host() and db.query(Account).count():
        plan.append((setup_host(), ROLE_LK, False))
    home = home_account(db) if settings.HOME_HOSTS else None
    accounts = db.query(Account).filter(
        Account.is_active.is_(True)).order_by(Account.id).all()
    for account in accounts:
        if home is None or account.id != home.id:
            for role, name in our_names(account).items():
                plan.append((name, role, False))
        for row in account.domains:
            if row.kind == KIND_OWN:
                plan.append((row.name, row.role, True))
    return plan


def ensure_domain_row(db, name, role):
    """
    Строка для нашего поддомена — чтобы было куда записать, выпущен ли
    сертификат. Чей он, видно и без неё: по имени организации.
    """
    from app.models.account import KIND_OURS

    row = db.query(AccountDomain).filter(AccountDomain.name == name).first()
    if row is not None:
        return row
    account_id, found_role = _host_target(db, name)
    if account_id is None:
        return None
    row = AccountDomain(account_id=account_id, name=name, role=found_role or role,
                        kind=KIND_OURS, status=DOMAIN_WAITING,
                        note='Сертификат выпускается')
    db.add(row)
    db.commit()
    return row


def set_domain_status(db, name, status_value, note=None):
    """Что вышло с адресом — пишет tire-domains, видно в дашборде."""
    row = db.query(AccountDomain).filter(AccountDomain.name == name).first()
    if row is None:
        return None
    row.status = status_value
    row.note = (note or '')[:255] or None
    row.checked_at = shop_now()
    db.commit()
    return row
