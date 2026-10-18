"""
Живая очередь целиком: телефон у въезда → сервер → цех → обратно.

Настоящий сервер (FastAPI) и программа цеха в одном прогоне: обмен
идёт тем же кодом, что в работе, только без сети.

  · место по QR попадает в цех и получает номер и время;
  · цех позвал — на телефоне пост и схема;
  · наряд открыт и оплачен — на телефоне «на посту», потом «готово»;
  · человек ушёл сам — цех убирает его из очереди.
"""
import _setup
from _setup import use_temp_db, check, finish

import os
import sys
import tempfile

use_temp_db('live_queue_sync')
os.chdir(_setup.PROJECT_DIR)

# --- сервер ----------------------------------------------------------
_server_db = os.path.join(tempfile.gettempdir(), 'tire_live_sync_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-live-sync'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-live-sync'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
sys.path.insert(0, os.path.join(_setup.PROJECT_DIR, 'server'))

from fastapi.testclient import TestClient
from app.main import app as server_app
from app.database import SessionLocal as ServerSession
from app.models import Shop

# --- цех -------------------------------------------------------------
from config import init_db, SessionLocal
from models import Service
from models.live_queue import WAITING, CALLED, SERVING, DONE, LEFT
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.sync_service import SyncService, SyncError
from services.live_queue_service import LiveQueueService

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

with TestClient(server_app) as server:
    sdb = ServerSession()
    slug = sdb.query(Shop).first().slug
    sdb.close()
    q = f'?shop={slug}'

    def call(method, path, payload=None):
        answer = server.request(method, path, json=payload, headers=KEY)
        if answer.status_code >= 400:
            raise SyncError(answer.text)
        return answer.json()

    init_db()
    db = SessionLocal()
    for name in ('Съем+Установка', 'Мойка', 'Балансировка', 'Шиномонтаж'):
        db.add(Service(name=name, vehicle_type='car', price_r16=1000))
    db.commit()
    ShiftService(db).open_shift(open_posts=3)
    EmployeeService(db).register_employee(1)
    EmployeeService(db).start_shift(1)

    sync = SyncService(db)
    sync._call = call
    queue = LiveQueueService(db)

    print('=== Цех на связи — по QR можно встать ===')
    sync.live_exchange()
    phone = TestClient(server_app)
    joined = phone.post('/live/join' + q, json={
        'license_plate': 'А123ВВ777', 'phone': '79099018931',
        'wheel_diameter': 'R16', 'wheels_assembled': False})
    check('встал по QR', joined.status_code == 200, joined.text)

    print()
    print('=== Цех забрал место ===')
    added = sync.live_exchange()
    check('пришло одно место', added == 1, str(added))
    entry = queue.find_active('А123ВВ777')
    check('в очереди цеха', entry is not None and entry.source == 'qr')
    check('с диаметром и колёсами', entry.wheel_diameter == 'R16' and entry.wheels_assembled is False)
    mine = phone.get('/live/state' + q).json()['ticket']
    check('на телефоне — цех принял и место 1', mine['seen_by_shop'] and mine['place'] == 1, str(mine))
    check('и примерное время', bool(mine['eta']), str(mine))

    sync.live_exchange()
    check('повторный обмен не дублирует',
          len([e for e in queue.line() if e.license_plate == 'А123ВВ777']) == 1)

    print()
    print('=== Позвали на пост 2 ===')
    queue.call(entry.id, 2)
    sync.live_exchange()
    mine = phone.get('/live/state' + q).json()['ticket']
    check('на телефоне — пост 2', mine['state'] == 'called' and mine['post'] == 2, str(mine))
    check('и схема со стрелками', mine['scene'] == '/parking?client=1#post2', str(mine))

    print()
    print('=== Подъехал: наряд открыт, потом оплачен ===')
    order = queue.open_order(entry.id)
    sync.live_exchange()
    check('на телефоне — на посту',
          phone.get('/live/state' + q).json()['ticket']['state'] == 'serving')
    names = sorted(i.service.name for i in OrderService(db).get_order_items(order.id))
    check('наряд по пакету «только шины»', 'Шиномонтаж' in names, str(names))
    SalaryService(db).process_payment(order.id, 'cash', OrderService(db).calculate_total(order.id))
    sync.live_exchange()
    check('на телефоне — готово',
          phone.get('/live/state' + q).json()['ticket']['state'] == 'done')

    print()
    print('=== Второй встал и ушёл сам ===')
    other = TestClient(server_app)
    other.post('/live/join' + q, json={'license_plate': 'К900ОР99', 'phone': '79160000002',
                                       'wheel_diameter': 'R17', 'wheels_assembled': True})
    sync.live_exchange()
    second = queue.find_active('К900ОР99')
    check('попал в цех', second is not None)
    other.post('/live/leave' + q)
    sync.live_exchange()
    db.refresh(second)
    check('цех убрал его из очереди', second.status == LEFT, second.status)

    print()
    print('=== Приёмщик сам поставил машину, потом человек встал по QR ===')
    manual = queue.add('Е555КХ77', '79160000003', 'R15', True, source='shop')
    third = TestClient(server_app)
    third.post('/live/join' + q, json={'license_plate': 'Е555КХ77', 'phone': '79160000003',
                                       'wheel_diameter': 'R15', 'wheels_assembled': True})
    sync.live_exchange()
    same = [e for e in queue.line() if e.license_plate == 'Е555КХ77']
    check('одно место, не два', len(same) == 1, str(same))
    db.refresh(manual)
    check('связано с местом на сервере', manual.server_id is not None)
    check('телефон видит своё место',
          third.get('/live/state' + q).json()['ticket']['seen_by_shop'])

    db.close()

finish()
