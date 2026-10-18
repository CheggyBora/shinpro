"""
Живая очередь по QR: страница у въезда и обмен с цехом.

  · без связи с цехом место по QR не даём — человек ждал бы в очереди,
    которую никто не видит;
  · место лежит в куке: обновил страницу — он на своём месте;
  · одна машина — одно место, чужой телефон не снимет и не займёт его;
  · цех забирает новые места и присылает место, время и пост;
  · позвали — вошедшему в кабинет уходит сообщение, на странице — пост
    и схема;
  · диаметр из онлайн-записи доходит до цеха.
"""
import os
import sys
import tempfile
from datetime import timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_live_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-live'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-live'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Appointment, Client, Shop
from app.models.live import LiveTicket
from app.security import create_token
from app.utils import now as shop_now
import app.api.live as live_api

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


told = []


def fake_send(db, client, account, kind, text, about=None, about_id=None):
    told.append((client.phone, text))
    return 'telegram'


live_api.notices.send_now = fake_send

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
FORM = {'license_plate': 'а123вв777', 'phone': '+7 909 901-89-31',
        'wheel_diameter': 'R16', 'wheels_assembled': True}

with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    slug = shop.slug
    account_id, shop_id = shop.account_id, shop.id
    shop.last_sync_at = None
    db.commit()
    db.close()
    q = f'?shop={slug}'

    print('=== Страницы открываются ===')
    page = http.get(f'/z/{slug}/q')
    check('страница очереди', page.status_code == 200 and 'Встать в очередь' in page.text)
    scene = http.get('/parking')
    check('схема площадки', scene.status_code == 200 and 'THREE' in scene.text)

    print()
    print('=== Цех без связи — по QR не встать ===')
    state = http.get('/live/state' + q).json()
    check('страница знает, что связи нет', state['online'] is False, str(state))
    refused = http.post('/live/join' + q, json=FORM)
    check('отказ', refused.status_code == 503, str(refused.status_code))
    check('сказано идти к приёмщику', 'приёмщик' in refused.json()['detail'])

    # Цех вышел на связь
    http.post('/sync/live', headers=KEY, json={'entries': []})

    print()
    print('=== Встать в очередь ===')
    joined = http.post('/live/join' + q, json=FORM)
    check('принято', joined.status_code == 200, joined.text)
    check('номер приведён к виду', joined.json()['license_plate'] == 'А123ВВ777')
    check('кука с местом', 'tire_live' in joined.cookies or 'tire_live' in http.cookies)
    check('цех ещё не видел', joined.json()['seen_by_shop'] is False)

    mine = http.get('/live/state' + q).json()['ticket']
    check('обновил страницу — место на месте', mine and mine['license_plate'] == 'А123ВВ777', str(mine))

    again = http.post('/live/join' + q, json=FORM)
    db = SessionLocal()
    count = db.query(LiveTicket).count()
    db.close()
    check('тот же номер и телефон — то же место', again.status_code == 200 and count == 1, str(count))

    stranger = TestClient(app)
    other = stranger.post('/live/join' + q, json=dict(FORM, phone='79160000000'))
    check('с чужим телефоном — отказ', other.status_code == 409, str(other.status_code))
    check('чужой не видит чужое место',
          stranger.get('/live/state' + q).json()['ticket'] is None)

    print()
    print('=== Вошедший в кабинет ===')
    db = SessionLocal()
    owner = Client(account_id=account_id, phone='79160000001', name='Пётр',
                   telegram_chat_id='555')
    db.add(owner)
    db.commit()
    token = create_token(owner.id)
    db.close()
    cabinet = TestClient(app)
    auth = {'Authorization': f'Bearer {token}'}
    st = cabinet.get('/live/state' + q, headers=auth).json()
    check('страница знает, что он вошёл', st['signed_in'] and st['phone'] == '79160000001', str(st))
    vip = cabinet.post('/live/join' + q, headers=auth,
                       json={'license_plate': 'К900ОР99', 'wheel_diameter': 'R17',
                             'wheels_assembled': False})
    check('встал без телефона в форме — взят из кабинета', vip.status_code == 200, vip.text)

    print()
    print('=== Цех забирает новые места ===')
    answer = http.post('/sync/live', headers=KEY, json={'entries': []}).json()
    plates = sorted(n['license_plate'] for n in answer['new'])
    check('цех получил оба места', plates == ['А123ВВ777', 'К900ОР99'], str(answer))
    first = next(n for n in answer['new'] if n['license_plate'] == 'А123ВВ777')
    check('с диаметром и колёсами', first['wheel_diameter'] == 'R16' and first['wheels_assembled'] is True)
    second = next(n for n in answer['new'] if n['license_plate'] == 'К900ОР99')

    eta = (shop_now() + timedelta(minutes=25)).replace(microsecond=0).isoformat()
    answer = http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'waiting',
         'place': 2, 'eta_at': eta},
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'waiting',
         'place': 1, 'eta_at': eta},
    ]}).json()
    check('второй раз не отдаёт как новые', answer['new'] == [], str(answer))
    mine = http.get('/live/state' + q).json()['ticket']
    check('видно место', mine['place'] == 2 and mine['seen_by_shop'], str(mine))
    check('видно время', mine['eta'] == eta[11:16], str(mine))

    print()
    print('=== Позвали ===')
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'called',
         'place': None, 'post_number': 3},
    ]})
    check('вошедшему ушло сообщение', told and told[-1][0] == '79160000001' and 'пост 3' in told[-1][1], str(told))
    vip_state = cabinet.get('/live/state' + q, headers=auth).json()['ticket']
    check('на странице — пост и схема',
          vip_state['post'] == 3 and vip_state['scene'] == '/parking?client=1#post3', str(vip_state))
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'called', 'post_number': 3},
    ]})
    check('повторный обмен не шлёт второй раз', len(told) == 1, str(told))

    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'called', 'post_number': 2},
    ]})
    check('без входа сообщения нет — только страница', len(told) == 1)
    check('на странице — пост', http.get('/live/state' + q).json()['ticket']['post'] == 2)

    print()
    print('=== Ушёл сам ===')
    left = http.post('/live/leave' + q).json()
    check('принято', left['left'] is True)
    answer = http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'called', 'post_number': 2},
    ]}).json()
    check('цех узнал, что ушёл', first['server_id'] in answer['left'], str(answer))
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'left'},
    ]})
    check('место закрыто — страница предлагает встать снова',
          http.get('/live/state' + q).json()['ticket'] is None)

    print()
    print('=== Обслужили — можно встать ещё раз ===')
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'done'},
    ]})
    done = cabinet.get('/live/state' + q, headers=auth).json()['ticket']
    check('видно «готово»', done and done['state'] == 'done', str(done))
    cabinet.post('/live/leave' + q, headers=auth)
    check('после «ещё раз» место забыто',
          cabinet.get('/live/state' + q, headers=auth).json()['ticket'] is None)

    print()
    print('=== Чужой ключ обмена ===')
    bad = http.post('/sync/live', headers={'X-Sync-Key': 'wrong'}, json={'entries': []})
    check('отказ', bad.status_code in (401, 403), str(bad.status_code))

    print()
    print('=== Диаметр из записи доходит до цеха ===')
    db = SessionLocal()
    at = (shop_now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    db.add(Appointment(shop_id=shop_id, scheduled_at=at, duration_minutes=30,
                       license_plate='В001ВВ77', wheels_assembled=True,
                       wheel_diameter='R18', status='scheduled'))
    db.commit()
    db.close()
    day = http.get(f'/sync/appointments?day={at.date().isoformat()}', headers=KEY).json()
    row = next(a for a in day['appointments'] if a['license_plate'] == 'В001ВВ77')
    check('диаметр в обмене', row.get('wheel_diameter') == 'R18', str(row))
    check('колёса в обмене', row.get('wheels_assembled') is True, str(row))

finish()
