"""
Посты и часы записи меняют с двух сторон. Кто позже — тот и прав.

Приёмщик меняет их в цеху, под ПИНом: он видит, кто сегодня работает.
Владелец — из дашборда: в цеху он не сидит, а выключить запись может
понадобиться немедленно. Значит, два источника правды на одну
настройку, и спор надо решать правилом, а не тем, кто чаще выходит
на связь.

Правило простое: прав тот, кто поставил позже. Проверяем, что оно
работает в обе стороны, и что обмен не выигрывает спор тем, что
присылает все настройки целиком каждые десять минут.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_settings_race.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-31'
OWNER_PIN = '4831'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-race'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-race'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE

import logging
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Shop
from app.services import shop_settings
from app.utils import now as shop_now

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


def enter(client, phone, pin):
    client.post('/staff/code', json={'phone': phone})
    token = client.post('/staff/verify',
                        json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = client.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def push(client, values, stamps):
    """Обмен из цеха: настройки и время, когда их там поменяли."""
    return client.post('/sync/push', headers=KEY, json={
        'settings': values,
        'settings_changed_at': {key: when.isoformat()
                                for key, when in stamps.items()},
    }).json()


def stored(key):
    db = SessionLocal()
    try:
        shop = db.query(Shop).first()
        return shop_settings.get(db, key, shop=shop)
    finally:
        db.close()


with TestClient(app) as client:
    owner = enter(client, OWNER_PHONE, OWNER_PIN)

    NOW = shop_now()
    LONG_AGO = NOW - timedelta(hours=3)

    print('=== Цех прислал свои настройки — приняли ===')
    answer = push(client, {'booking_posts': '2', 'booking_opens_at': '08:00'},
                  {'booking_posts': LONG_AGO, 'booking_opens_at': LONG_AGO})
    check('приняли обе', answer['settings'] == 2, str(answer))
    check('возвращать нечего', answer['from_server'] == [], str(answer))
    check('посты записались', stored('booking_posts') == '2',
          str(stored('booking_posts')))

    print()
    print('=== Тот же обмен ещё раз метку не двигает ===')
    # Иначе цех выигрывал бы любой спор просто тем, что выходит на
    # связь каждые десять минут
    db = SessionLocal()
    shop = db.query(Shop).first()
    before = shop_settings.updated_at(db, 'booking_posts', shop=shop)
    db.close()

    push(client, {'booking_posts': '2'}, {'booking_posts': shop_now()})

    db = SessionLocal()
    shop = db.query(Shop).first()
    after = shop_settings.updated_at(db, 'booking_posts', shop=shop)
    db.close()

    check('время правки осталось прежним', before == after,
          f'{before} против {after}')

    print()
    print('=== Новая точка принимает запись с самого начала ===')
    # Выключенная запись закрывает точку для клиентов. Приходить к
    # этому по умолчанию нельзя: включают запись не для того, чтобы
    # потом искать, где её включить
    view = client.get('/dashboard/booking-settings', headers=owner).json()
    check('приём включён', view['booking_enabled'] is True, str(view))

    db = SessionLocal()
    shop = db.query(Shop).first()
    check('и у самой точки тоже', shop.booking_enabled is True,
          str(shop.booking_enabled))
    db.close()

    print()
    print('=== Непонятное значение запись не выключает ===')
    # Старая версия программы, пустая настройка, сбой при чтении — что
    # угодно. Выключение бывает только осознанным
    for value in ('', 'да', 'ага', 'None'):
        push(client, {'booking_enabled': value},
             {'booking_enabled': shop_now()})
        db = SessionLocal()
        shop = db.query(Shop).first()
        on = shop.booking_enabled
        db.close()
        check(f'«{value}» не выключило', on is True, str(on))

    for value in ('0', 'false', 'нет'):
        push(client, {'booking_enabled': value},
             {'booking_enabled': shop_now()})
        db = SessionLocal()
        shop = db.query(Shop).first()
        off = shop.booking_enabled
        db.close()
        check(f'«{value}» выключило', off is False, str(off))

    push(client, {'booking_enabled': '1'}, {'booking_enabled': shop_now()})

    print()
    print('=== Владелец поменял из дашборда ===')
    saved = client.put('/dashboard/booking-settings', headers=owner,
                       json={'booking_posts': 3, 'booking_enabled': False})
    check('приняли', saved.status_code == 200, str(saved.json()))
    check('посты стали тремя', stored('booking_posts') == '3',
          str(stored('booking_posts')))

    db = SessionLocal()
    shop = db.query(Shop).first()
    check('и у самой точки запись выключена',
          shop.booking_enabled is False, str(shop.booking_enabled))
    check('значит, в кабинете её не показываем',
          shop.takes_bookings is False, str(shop.takes_bookings))
    db.close()

    print()
    print('=== Обмен эту правку не затирает ===')
    answer = push(client, {'booking_posts': '2', 'booking_enabled': '1'},
                  {'booking_posts': LONG_AGO, 'booking_enabled': LONG_AGO})

    check('посты остались дашбордными', stored('booking_posts') == '3',
          str(stored('booking_posts')))
    check('и выключатель тоже', stored('booking_enabled') == '0',
          str(stored('booking_enabled')))

    back = {row['key']: row['value'] for row in answer['from_server']}
    check('цеху вернули оба значения',
          back == {'booking_posts': '3', 'booking_enabled': '0'}, str(back))
    check('со временем правки',
          all(row.get('changed_at') for row in answer['from_server']),
          str(answer['from_server']))

    print()
    print('=== А новую правку из цеха принимаем ===')
    # Приёмщик поменял посты уже после владельца: он стоит в цеху и
    # видит, кто сегодня работает
    answer = push(client, {'booking_posts': '1'},
                  {'booking_posts': shop_now() + timedelta(seconds=1)})
    check('посты стали цеховыми', stored('booking_posts') == '1',
          str(stored('booking_posts')))
    check('возвращать нечего', answer['from_server'] == [], str(answer))

    print()
    print('=== Старая версия программы работает как раньше ===')
    # Метки она не присылает: спорить нечем, принимаем присланное
    client.post('/sync/push', headers=KEY,
                json={'settings': {'booking_posts': '2'}})
    check('приняли без разбора', stored('booking_posts') == '2',
          str(stored('booking_posts')))

    print()
    print('=== Часы проверяются, а не записываются как попало ===')
    bad = client.put('/dashboard/booking-settings', headers=owner,
                     json={'booking_opens_at': '25:70'})
    check('время не из этого мира отклонено', bad.status_code == 400,
          str(bad.json()))

    bad = client.put('/dashboard/booking-settings', headers=owner,
                     json={'booking_opens_at': 'вечером'})
    check('словами тоже нельзя', bad.status_code == 400, str(bad.json()))

    backwards = client.put('/dashboard/booking-settings', headers=owner,
                           json={'booking_opens_at': '20:00',
                                 'booking_closes_at': '09:00'})
    check('закрытие раньше открытия отклонено',
          backwards.status_code == 400, str(backwards.json()))
    check('и сказано, почему',
          'раньше открытия' in backwards.json()['detail'],
          backwards.json()['detail'])
    check('ничего не записалось', stored('booking_opens_at') == '08:00',
          str(stored('booking_opens_at')))

    print()
    print('=== Полночь понимается как конец суток ===')
    ok = client.put('/dashboard/booking-settings', headers=owner,
                    json={'booking_opens_at': '07:00',
                          'booking_closes_at': '24:00'})
    check('приняли', ok.status_code == 200, str(ok.json()))
    check('записалось', stored('booking_closes_at') == '24:00',
          str(stored('booking_closes_at')))

    print()
    print('=== Посты за пределами здравого смысла подрезаются ===')
    client.put('/dashboard/booking-settings', headers=owner,
               json={'booking_posts': 99})
    check('не больше трёх', stored('booking_posts') == '3',
          str(stored('booking_posts')))

    client.put('/dashboard/booking-settings', headers=owner,
               json={'booking_posts': 0})
    check('и не меньше одного', stored('booking_posts') == '1',
          str(stored('booking_posts')))

    print()
    print('=== Что показываем на экране ===')
    view = client.get('/dashboard/booking-settings', headers=owner).json()
    check('посты числом', view['booking_posts'] == 1, str(view))
    check('выключатель признаком', view['booking_enabled'] is False, str(view))
    check('часы строками', view['booking_opens_at'] == '07:00', str(view))
    check('видно, когда меняли', bool(view['changed_at']['booking_posts']),
          str(view['changed_at']))
    check('и какая это точка', bool(view['shop']['name']), str(view['shop']))

finish()
