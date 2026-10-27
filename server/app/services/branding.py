"""
Как организацию видят её клиенты: название, логотип, цвет кнопок.

У каждой организации свои (решение владельца 27.10.2026): клиент
«Колеса» на странице записи, в кабинете и на экране очереди не должен
увидеть ничего от «РИФа». Задаёт это владелец организации в дашборде,
раздел «Оформление».

Логотип того, кто держит сервер, по-прежнему может лежать файлом
(SERVER_LOGO_PATH или web/logo.jpg) — но отдаётся только его
организации. Чужой организации без своего логотипа лучше без картинки,
чем с чужой.
"""
import io
import os
import re

from app.utils import now as shop_now

# Цвет кнопок по умолчанию — тот, что был на странице записи всегда
DEFAULT_COLOR = '#2563eb'
_COLOR_RE = re.compile(r'^#[0-9a-f]{6}$')

# Фото с телефона весит 3–8 МБ, логотип после ужатия — десятки КБ
LOGO_MAX_BYTES = 8 * 1024 * 1024
LOGO_SIDE = 512

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web')


class BrandError(ValueError):
    """Не подходит. Текст — для человека."""


def brand_name(db, account, shop=None):
    """
    Название на странице: заданное в «Оформлении», иначе — точки, на
    странице которой человек, иначе — организации.
    """
    if account is not None and account.brand_name:
        return account.brand_name
    if shop is not None:
        from app.services import shop_settings
        return shop_settings.title(db, shop)
    return account.name if account is not None else ''


def brand_color(account):
    color = (account.brand_color or '').lower() if account is not None else ''
    return color if _COLOR_RE.match(color) else DEFAULT_COLOR


def has_logo(db, account):
    if account is None:
        return False
    if account.logo:
        return True
    return _is_home(db, account) and _home_logo_path() is not None


def brand_of(db, account, shop=None):
    """Всё, что нужно странице, одним ответом."""
    version = ''
    if account is not None and account.logo_at:
        version = account.logo_at.strftime('%Y%m%d%H%M%S')
    return {
        'name': brand_name(db, account, shop),
        'color': brand_color(account),
        'has_logo': has_logo(db, account),
        'logo_version': version,
    }


def set_brand(db, account, name=None, color=None):
    if name is not None:
        name = ' '.join(str(name).split())[:200]
        account.brand_name = name or None
    if color is not None:
        color = str(color).strip().lower()
        if color and not _COLOR_RE.match(color):
            raise BrandError('Цвет нужен в виде #2563eb')
        account.brand_color = color or None
    db.commit()
    return account


def set_logo(db, account, data):
    """
    Сохранить логотип. Любую картинку приводим к квадрату PNG 512×512 с
    прозрачными полями: так она одинаково встанет и в шапку страницы, и
    значком на экран телефона, а в базе займёт десятки килобайт.
    """
    if not data:
        raise BrandError('Пустой файл')
    if len(data) > LOGO_MAX_BYTES:
        raise BrandError('Картинка слишком большая — нужна до 8 МБ')

    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        raise BrandError('Это не картинка. Нужен JPG или PNG')

    image = ImageOps.exif_transpose(image).convert('RGBA')
    image.thumbnail((LOGO_SIDE, LOGO_SIDE))
    square = Image.new('RGBA', (LOGO_SIDE, LOGO_SIDE), (255, 255, 255, 0))
    square.paste(image, ((LOGO_SIDE - image.width) // 2,
                         (LOGO_SIDE - image.height) // 2), image)

    out = io.BytesIO()
    square.save(out, format='PNG', optimize=True)

    account.logo = out.getvalue()
    account.logo_type = 'image/png'
    account.logo_at = shop_now()
    db.commit()
    return account


def clear_logo(db, account):
    account.logo = None
    account.logo_type = None
    account.logo_at = shop_now()
    db.commit()


def logo_of(db, account):
    """(байты, тип) логотипа организации или None."""
    if account is None:
        return None
    if account.logo:
        return account.logo, account.logo_type or 'image/png'
    if _is_home(db, account):
        path = _home_logo_path()
        if path is not None:
            with open(path, 'rb') as handle:
                return handle.read(), 'image/jpeg'
    return None


def _is_home(db, account):
    from app.services import tenancy
    home = tenancy.home_account(db)
    return home is not None and home.id == account.id


def _home_logo_path():
    path = os.environ.get('SERVER_LOGO_PATH') or os.path.join(WEB_DIR, 'logo.jpg')
    return path if os.path.exists(path) else None


def parking_scene(row, post):
    """
    Ссылка на 3D-схему площадки со стрелкой до поста — или None.

    Схема нарисована с площадки «РИФа»: его здание, его вывеска. Клиенту
    другой организации показать её — значит отправить его на чужой
    двор, поэтому только своим точкам того, кто держит сервер. row —
    талон очереди или запись: что угодно с shop_id из базы.
    """
    if not post or row is None or not getattr(row, 'shop_id', None):
        return None
    from sqlalchemy.orm import object_session
    from app.models import Shop

    db = object_session(row)
    if db is None:
        return None
    shop = db.get(Shop, row.shop_id)
    if shop is None or shop.account is None or not _is_home(db, shop.account):
        return None
    return f'/parking?client=1#post{post}'


def page_account(db, shop_slug=None):
    """
    Чья страница открыта: по точке из адреса, иначе по адресу сайта,
    иначе — единственная организация на сервере. (организация, точка)
    """
    from app.models import Account
    from app.services import tenancy

    shop = tenancy.page_shop(db, shop_slug)
    if shop is not None:
        return shop.account, shop
    if shop_slug:
        return None, None
    try:
        account_id = tenancy.account_for(db)
    except tenancy.ShopNeeded:
        return None, None
    if account_id is None:
        return None, None
    return db.get(Account, account_id), None
