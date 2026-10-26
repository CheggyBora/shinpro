"""
Склад точки: снимок из цеха и вид для дашборда (docs/stock.md).

Цех присылает остатки целиком, когда они поменялись. Снимок заменяет
прошлый: позиция, которой в нём нет, удалена в цеху — значит, и здесь
её быть не должно. Сравнивать правки по времени, как у задач, незачем:
склад правят только в цеху.
"""
import math

from app.models import StockItem
from app.models.stock import TIRE, DIRECTIONS, MATERIAL, KINDS
from app.services import shop_settings
from app.services.tasks import parse_moment
from app.utils import now as shop_now

# Больше позиций в одном снимке не принимаем. Обрезать снимок нельзя —
# всё, что не влезло, было бы удалено как пропавшее в цеху, — поэтому
# слишком большой снимок отклоняется целиком
MAX_ITEMS = 5000

# Больше этого остаток, минимум или цена не бывают. Огромное число —
# сбой в цеху, и показывать его владельцу как правду нельзя
MAX_NUMBER = 1e9

DEFAULT_UNIT = 'шт'

# Состояния позиции — в этом порядке их и показываем: сначала то, что
# требует внимания
NEG = 'neg'
LOW = 'low'
OK = 'ok'
STATE_ORDER = {NEG: 0, LOW: 1, OK: 2}

# Фильтр дашборда «Направление: Все»
ALL = 'all'


class StockError(Exception):
    """Снимок принять нельзя. Текст — для журнала цеха."""


def _text(value, limit):
    if value is None:
        return ''
    return str(value).strip()[:limit]


def _number(value, low=-MAX_NUMBER, default=0.0):
    """
    Число из присланного. Непонятное — default, слишком большое —
    до предела. «1,5» тоже число: так пишут в цеху.
    """
    if value is None or value == '':
        return default
    try:
        number = float(str(value).replace(',', '.').replace(' ', ''))
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return round(max(low, min(MAX_NUMBER, number)), 3)


def parse_direction(value):
    """Непонятное направление — шиномонтаж: всё, что было до мойки."""
    value = str(value or '').strip().lower()
    return value if value in DIRECTIONS else TIRE


def parse_kind(value):
    """
    Непонятный вид — материал. Товар продаётся в наряде; позиция,
    которую по ошибке посчитали товаром, всплыла бы в прайсе.
    """
    value = str(value or '').strip().lower()
    return value if value in KINDS else MATERIAL


def parse_direction_filter(value):
    """tire, wash — фильтр; пусто, all и непонятное — без фильтра."""
    value = str(value or '').strip().lower()
    return value if value in DIRECTIONS else None


def clean_item(item):
    """
    Позиция снимка в поля таблицы. None — позицию принять нельзя:
    без uid её не узнать в следующем снимке, без названия — не показать.
    """
    if not isinstance(item, dict):
        return None
    uid = _text(item.get('uid'), 40)
    name = _text(item.get('name'), 200)
    if not uid or not name:
        return None

    purchase = item.get('purchase_price')
    return {
        'uid': uid,
        'name': name,
        'direction': parse_direction(item.get('direction')),
        'kind': parse_kind(item.get('kind')),
        'unit': _text(item.get('unit'), 10) or DEFAULT_UNIT,
        'quantity': _number(item.get('quantity')),
        'min_quantity': _number(item.get('min_quantity'), low=0),
        'price': _number(item.get('price'), low=0),
        'purchase_price': (None if purchase is None or purchase == ''
                           else _number(purchase, low=0, default=None)),
        'updated_at': parse_moment(item.get('updated_at')),
    }


def replace_snapshot(db, shop, payload, now=None):
    """
    Принять снимок склада точки: обновить по uid, добавить новое,
    удалить то, чего в снимке нет. Возвращает, сколько позиций лежит
    и какие uid не приняты.
    """
    now = (now or shop_now()).replace(microsecond=0)
    items = payload.get('items') or []
    if not isinstance(items, list):
        raise StockError('items — список позиций')
    if len(items) > MAX_ITEMS:
        raise StockError(f'Слишком большой снимок: больше {MAX_ITEMS} позиций')

    fresh, rejected = {}, []
    for item in items:
        fields = clean_item(item)
        if fields is None:
            uid = item.get('uid') if isinstance(item, dict) else None
            rejected.append(str(uid) if uid else '')
            continue
        # Один uid дважды — берём последнюю строку: в базе он один
        fresh[fields['uid']] = fields

    rows = {row.uid: row for row in db.query(StockItem).filter(
        StockItem.shop_id == shop.id).all()}

    for uid, row in rows.items():
        if uid not in fresh:
            db.delete(row)

    for uid, fields in fresh.items():
        row = rows.get(uid)
        if row is None:
            row = StockItem(shop_id=shop.id, uid=uid)
            db.add(row)
        for key, value in fields.items():
            if key == 'updated_at':
                value = value or row.updated_at or now
            setattr(row, key, value)

    enabled = payload.get('enabled')
    if enabled is not None:
        flag = enabled if isinstance(enabled, bool) else shop_settings.is_on(enabled)
        shop_settings.set_value(db, 'stock_enabled', '1' if flag else '0',
                                commit=False, shop=shop)
    shop_settings.set_value(db, 'stock_snapshot_at',
                            now.isoformat(timespec='seconds'),
                            commit=False, shop=shop)
    db.commit()
    return len(fresh), rejected


def state(row):
    """neg — ушло в минус, low — меньше минимума, ok — хватает."""
    if row.quantity < 0:
        return NEG
    if row.quantity < (row.min_quantity or 0):
        return LOW
    return OK


def to_dict(row, with_purchase=True):
    return {
        'uid': row.uid,
        'name': row.name,
        'direction': row.direction,
        'kind': row.kind,
        'unit': row.unit,
        'quantity': row.quantity,
        'min_quantity': row.min_quantity,
        'price': row.price,
        'purchase_price': row.purchase_price if with_purchase else None,
        'updated_at': (row.updated_at.isoformat(timespec='seconds')
                       if row.updated_at else None),
        'state': state(row),
    }


def snapshot_at(db, shop):
    """Когда снимок склада точки доехал сюда. None — ещё не приезжал."""
    return parse_moment(shop_settings.get(db, 'stock_snapshot_at', '',
                                          shop=shop) or None)


def items_for(db, shop_ids, direction=None):
    """Позиции точек: сначала минус, потом мало, потом по названию."""
    if not shop_ids:
        return []
    query = db.query(StockItem).filter(StockItem.shop_id.in_(shop_ids))
    if direction:
        query = query.filter(StockItem.direction == direction)
    rows = query.all()
    rows.sort(key=lambda row: (STATE_ORDER[state(row)],
                               row.name.casefold(), row.shop_id, row.uid))
    return rows
