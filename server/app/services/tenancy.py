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
import re
import secrets

from app.config import settings
from app.models import Account, Shop
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
    while result in taken:
        result = f'{base}-{number}'
        number += 1

    return result


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


def create_account(db, name, shop_name=None, key=None):
    """
    Завести аккаунт с первой точкой. Возвращает (аккаунт, точка, ключ).

    Ключ возвращается открытым один раз: в базе остаётся только
    отпечаток, и показать ключ второй раз сервер не сможет.
    """
    taken = taken_slugs(db)

    account = Account(name=name, slug=make_slug(name, taken))
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


def only_shop(db):
    """
    Единственная точка, если она одна.

    Нужно там, где точку неоткуда взять: публичная страница записи без
    имени в адресе. Когда точек несколько, возвращаем None — пусть
    вызывающий спросит, о какой речь, а не гадает.
    """
    shops = db.query(Shop).filter(Shop.is_active.is_(True)).limit(2).all()
    return shops[0] if len(shops) == 1 else None


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


def account_for(db, wanted=None):
    """
    Аккаунт, о котором идёт речь в запросе.

    wanted — короткое имя точки или сети из заголовка X-Shop. Пусто и
    аккаунт на сервере один — берём его: заставлять единственный
    шиномонтаж всюду писать своё имя незачем.

    Пусто и аккаунтов несколько — отказываем. Угадывать, в чей кабинет
    человек хотел войти, нельзя ни в коем случае.
    """
    if wanted:
        shop = shop_by_slug(db, wanted)
        if shop is not None:
            return shop.account_id

        account = db.query(Account).filter(Account.slug == wanted).first()
        if account is not None:
            return account.id

        raise ShopNeeded('Такого шиномонтажа нет')

    accounts = db.query(Account).filter(
        Account.is_active.is_(True)).limit(2).all()

    if len(accounts) == 1:
        return accounts[0].id
    if not accounts:
        return None

    raise ShopNeeded('Укажите, какой шиномонтаж')
