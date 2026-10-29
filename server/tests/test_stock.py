"""
Склад: снимок из цеха и раздел дашборда (docs/stock.md).

  · снимок полный: обновляем по uid, добавляем новое, чего нет — удаляем;
  · присланное приводится к виду: непонятное направление — шиномонтаж,
    непонятный вид — материал, длинное обрезается, огромное — до предела,
    позиция без uid или названия не принимается;
  · слишком большой снимок отклоняется целиком и ничего не удаляет;
  · выключатель склада ездит в снимке; не прислан — не трогаем;
  · дашборд: сначала минус, потом мало, потом по названию; фильтр по
    направлению; выключенный склад не показывается;
  · чужая точка чужой склад не видит и не затирает;
  · без ключа обмена и без входа — отказ.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_stock_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-41'
ADMIN_PHONE = '+7 916 555-12-41'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-stock'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-stock'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Shop, StockItem
from app.services import shop_settings, tenancy

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" +
          (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


def finish():
    print('-' * 60)
    if _failures:
        print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
        for item in _failures:
            print(f'  - {item}')
        sys.exit(1)
    print('Все проверки пройдены')
    sys.exit(0)


class CodeCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.code = None

    def emit(self, record):
        message = record.getMessage()
        if 'код' in message:
            self.code = message.strip().split()[-1]


catcher = CodeCatcher()
logging.getLogger('tire_server').addHandler(catcher)

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify',
                      json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def item(uid, name, **extra):
    row = {'uid': uid, 'name': name, 'direction': 'tire', 'kind': 'material',
           'unit': 'шт', 'quantity': 10, 'min_quantity': 0, 'price': 100,
           'purchase_price': None, 'updated_at': '2026-10-26T12:00:00'}
    row.update(extra)
    return row


def rows_of(shop_id):
    db = SessionLocal()
    try:
        return {row.uid: row for row in db.query(StockItem).filter(
            StockItem.shop_id == shop_id).all()}
    finally:
        db.close()


def setting(shop_id, key):
    db = SessionLocal()
    try:
        return shop_settings.get(db, key, shop=shop_id)
    finally:
        db.close()


def by_uid(items, uid):
    return next((row for row in items if row['uid'] == uid), None)


with TestClient(app) as http:
    # Входим, пока заказчик один: со вторым вход спрашивает, к кому
    owner = enter(http, OWNER_PHONE, '4832')
    # Админ без права на выручку: склад видит (своя галочка «Склад»),
    # закупку — нет
    added = http.post('/staff/people', headers=owner, json={
        'phone': ADMIN_PHONE, 'name': 'Ольга', 'role': 'admin',
        'permissions': ['orders', 'stock']})
    admin = enter(http, ADMIN_PHONE, '5821')

    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_id, slug = shop.id, shop.slug
    other, other_key = tenancy.add_shop(db, shop.account, 'РИФ на Южной')
    other_id, other_slug = other.id, other.slug
    _, stranger, stranger_key = tenancy.create_account(db, 'Чужой шиномонтаж')
    stranger_id = stranger.id
    db.close()
    OTHER = {'X-Sync-Key': other_key}
    STRANGER = {'X-Sync-Key': stranger_key}

    def send(items, enabled=True, headers=KEY, raw=None):
        body = raw if raw is not None else {'enabled': enabled, 'items': items}
        if raw is None and enabled is None:
            body.pop('enabled')
        answer = http.post('/sync/stock', headers=headers, json=body)
        return answer.status_code, answer.json()

    print('=== Без ключа — отказ ===')
    answer = http.post('/sync/stock', json={'enabled': True, 'items': []})
    check('без ключа обмена — 401', answer.status_code == 401,
          str(answer.status_code))
    answer = http.post('/sync/stock', headers={'X-Sync-Key': 'wrong-key'},
                       json={'enabled': True, 'items': []})
    check('с неверным ключом — 401', answer.status_code == 401)
    check('склад по умолчанию выключен', setting(shop_id, 'stock_enabled') == '0')

    print()
    print('=== Первый снимок ===')
    code, first = send([
        item('u-valve', 'Вентиль черный', kind='goods', quantity=146,
             min_quantity=50, price=60, purchase_price=22),
        item('u-plug', 'Жгут ремонтный', quantity=8, min_quantity=20, price=40),
        item('u-weights', 'Грузики самоклейка', unit='кг', quantity='3,8',
             min_quantity=1, price=900),
        item('u-shampoo', 'Шампунь бесконтактный', direction='wash', unit='л',
             quantity=-0.4, min_quantity=5, price=350),
        item('u-wax', 'Воск горячий', direction='wash', unit='л',
             quantity=6.2, min_quantity=2, price=500),
        item('u-odd', 'Непонятное', direction='garden', kind='секрет',
             unit='коробочка-большая'),
        item('u-huge', 'Я' * 500, quantity=1e15, min_quantity=-5, price='abc'),
        item('', 'Без uid'),
        item('u-noname', '   '),
        item('u-dup', 'Первый вариант', quantity=1),
        item('u-dup', 'Второй вариант', quantity=2),
    ])
    check('снимок принят', code == 200 and first.get('ok') is True, str(first)[:200])
    check('count — сколько позиций легло', first.get('count') == 8,
          str(first.get('count')))
    check('без uid и без названия — не приняты',
          sorted(first.get('rejected', [])) == ['', 'u-noname'],
          str(first.get('rejected')))
    stored = rows_of(shop_id)
    check('в базе восемь позиций', len(stored) == 8, str(sorted(stored)))
    check('непонятное направление — шиномонтаж',
          stored['u-odd'].direction == 'tire')
    check('непонятный вид — материал', stored['u-odd'].kind == 'material')
    check('единица обрезана до 10', len(stored['u-odd'].unit) == 10,
          stored['u-odd'].unit)
    check('длинное название обрезано до 200', len(stored['u-huge'].name) == 200)
    check('огромный остаток — до предела', stored['u-huge'].quantity == 1e9,
          str(stored['u-huge'].quantity))
    check('отрицательный минимум — ноль', stored['u-huge'].min_quantity == 0)
    check('непонятная цена — ноль', stored['u-huge'].price == 0)
    check('«3,8» — число', stored['u-weights'].quantity == 3.8,
          str(stored['u-weights'].quantity))
    check('отрицательный остаток сохранён', stored['u-shampoo'].quantity == -0.4)
    check('закупка необязательна', stored['u-plug'].purchase_price is None
          and stored['u-valve'].purchase_price == 22)
    check('uid дважды — последняя строка', stored['u-dup'].name == 'Второй вариант')
    check('время правки — присланное',
          stored['u-valve'].updated_at.isoformat() == '2026-10-26T12:00:00')
    check('склад включён', setting(shop_id, 'stock_enabled') == '1')
    check('время снимка записано', bool(setting(shop_id, 'stock_snapshot_at')))

    print()
    print('=== Дашборд ===')
    answer = http.get('/dashboard/stock')
    check('без входа — 401', answer.status_code == 401, str(answer.status_code))

    answer = http.get(f'/dashboard/stock?shop={slug}', headers=owner)
    check('остатки отдаются', answer.status_code == 200, answer.text[:200])
    data = answer.json()
    check('склад включён', data['enabled'] is True)
    check('время снимка есть', bool(data['updated_at']), str(data['updated_at']))
    names = [row['name'] for row in data['items']]
    check('сначала минус, потом мало, потом по названию',
          names[:2] == ['Шампунь бесконтактный', 'Жгут ремонтный']
          and names[2:] == sorted(names[2:], key=str.casefold), str(names))
    states = {row['uid']: row['state'] for row in data['items']}
    check('минус — neg', states['u-shampoo'] == 'neg')
    check('меньше минимума — low', states['u-plug'] == 'low')
    check('хватает — ok', states['u-valve'] == 'ok' and states['u-wax'] == 'ok')
    check('минимум ноль и остаток есть — ok', states['u-odd'] == 'ok')
    valve = by_uid(data['items'], 'u-valve')
    check('поля позиции на месте',
          valve['kind'] == 'goods' and valve['unit'] == 'шт'
          and valve['quantity'] == 146 and valve['min_quantity'] == 50
          and valve['price'] == 60 and valve['direction'] == 'tire'
          and valve['shop_id'] == shop_id, str(valve))
    check('владелец видит закупку', valve['purchase_price'] == 22)
    seen = http.get(f'/dashboard/stock?shop={slug}', headers=admin)
    check('админ без выручки видит склад', seen.status_code == 200
          and len(seen.json()['items']) == 8, seen.text[:200])
    check('но не закупку',
          by_uid(seen.json()['items'], 'u-valve')['purchase_price'] is None)

    wash = http.get(f'/dashboard/stock?shop={slug}&direction=wash',
                    headers=owner).json()
    check('фильтр мойки — только мойка',
          {row['uid'] for row in wash['items']} == {'u-shampoo', 'u-wax'},
          str([row['uid'] for row in wash['items']]))
    tire = http.get(f'/dashboard/stock?shop={slug}&direction=tire',
                    headers=owner).json()
    check('фильтр шиномонтажа — без мойки',
          all(row['direction'] == 'tire' for row in tire['items'])
          and len(tire['items']) == 6)
    every = http.get(f'/dashboard/stock?shop={slug}&direction=all',
                     headers=owner).json()
    check('all — всё', len(every['items']) == 8 and every['direction'] == 'all')
    odd = http.get(f'/dashboard/stock?shop={slug}&direction=огород',
                   headers=owner).json()
    check('непонятный фильтр — всё', len(odd['items']) == 8)

    answer = http.get(f'/dashboard/stock?shop={stranger_id}', headers=owner)
    check('точка чужого заказчика — 404', answer.status_code == 404,
          str(answer.status_code))
    answer = http.get('/dashboard/stock?shop=nowhere', headers=owner)
    check('несуществующая точка — 404', answer.status_code == 404)

    shops = {row['id']: row for row in
             http.get('/dashboard/shops', headers=owner).json()}
    check('в списке точек видно, у кого склад',
          shops[shop_id]['stock_enabled'] is True
          and shops[other_id]['stock_enabled'] is False, str(shops)[:300])

    print()
    print('=== Второй снимок заменяет первый ===')
    code, second = send([
        item('u-valve', 'Вентиль черный', kind='goods', quantity=140,
             min_quantity=50, price=65, purchase_price=22),
        item('u-plug', 'Жгут ремонтный', quantity=108, min_quantity=20, price=40,
             updated_at=None),
        item('u-new', 'Грибок 6 мм', quantity=54, min_quantity=20, price=120),
    ])
    check('принят', code == 200 and second['count'] == 3, str(second))
    stored = rows_of(shop_id)
    check('пропавшие удалены', set(stored) == {'u-valve', 'u-plug', 'u-new'},
          str(sorted(stored)))
    check('остаток обновлён', stored['u-valve'].quantity == 140
          and stored['u-valve'].price == 65)
    check('без времени правки — прежнее время остаётся',
          stored['u-plug'].updated_at.isoformat() == '2026-10-26T12:00:00',
          str(stored['u-plug'].updated_at))
    data = http.get(f'/dashboard/stock?shop={slug}', headers=owner).json()
    check('пополнили — больше не мало',
          by_uid(data['items'], 'u-plug')['state'] == 'ok')

    print()
    print('=== Слишком большой снимок ===')
    code, answer = send([item(f'u-{n}', f'Позиция {n}') for n in range(5001)])
    check('отклонён', code == 400, str(code))
    check('и ничего не удалил', len(rows_of(shop_id)) == 3)

    code, answer = send(None, raw={'enabled': True, 'items': 'не список'})
    check('items не список — отказ, а не падение', code in (400, 422), str(code))
    check('и ничего не удалил', len(rows_of(shop_id)) == 3)

    print()
    print('=== Чужие точки ===')
    code, answer = send([item('u-valve', 'Вентиль другой точки', quantity=1)],
                        headers=OTHER)
    check('вторая точка присылает свой склад', code == 200 and answer['count'] == 1)
    check('тот же uid у другой точки — своя позиция',
          rows_of(shop_id)['u-valve'].name == 'Вентиль черный'
          and rows_of(other_id)['u-valve'].name == 'Вентиль другой точки')
    code, answer = send([], headers=STRANGER)
    check('пустой снимок чужого заказчика', code == 200 and answer['count'] == 0)
    check('чужой снимок наш склад не тронул', len(rows_of(shop_id)) == 3)

    both = http.get('/dashboard/stock', headers=owner).json()
    check('без выбора точки — склады всех точек сети',
          {row['shop_id'] for row in both['items']} == {shop_id, other_id}
          and len(both['items']) == 4, str(len(both['items'])))
    check('у позиции подписана точка',
          all(row['shop_name'] for row in both['items']))
    check('чужого заказчика нет',
          all(row['shop_id'] != stranger_id for row in both['items']))

    print()
    print('=== Выключатель ===')
    code, answer = send([item('u-x', 'Позиция')], enabled=None, headers=OTHER)
    check('без enabled снимок принят', code == 200)
    check('и выключатель не тронут', setting(other_id, 'stock_enabled') == '1')

    code, answer = send([item('u-x', 'Позиция')], enabled=False, headers=OTHER)
    check('выключили', setting(other_id, 'stock_enabled') == '0')
    data = http.get(f'/dashboard/stock?shop={other_slug}', headers=owner).json()
    check('выключенный склад не показывается',
          data['enabled'] is False and data['items'] == []
          and data['updated_at'] is None, str(data))
    both = http.get('/dashboard/stock', headers=owner).json()
    check('по всем точкам — только включённые',
          both['enabled'] is True
          and {row['shop_id'] for row in both['items']} == {shop_id})
    shops = {row['id']: row for row in
             http.get('/dashboard/shops', headers=owner).json()}
    check('в списке точек склад выключен', shops[other_id]['stock_enabled'] is False)

    send([], enabled=False)
    data = http.get('/dashboard/stock', headers=owner).json()
    check('выключен везде — enabled false', data['enabled'] is False
          and data['items'] == [], str(data))

    print()
    print('=== Удаление точки забирает и склад ===')
    db = SessionLocal()
    tenancy.drop_shop(db, db.get(Shop, other_id))
    db.close()
    check('позиций удалённой точки нет', not rows_of(other_id))

finish()
