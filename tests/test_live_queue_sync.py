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
    queue.set_mode('on')       # не зависеть от даты прогона

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

    print()
    print('=== Запись: «Я на месте» с телефона → цех → вызов ===')
    from datetime import date, timedelta as _td
    from app.models import Appointment as ServerAppointment, Client as ServerClient
    from app.security import create_token
    from app.utils import now as server_now
    from services.booking_api import BookingApi

    sdb = ServerSession()
    shop_row = sdb.query(Shop).first()
    person = ServerClient(account_id=shop_row.account_id, phone='79160000900', name='Анна')
    sdb.add(person)
    sdb.commit()
    visit = ServerAppointment(shop_id=shop_row.id, client_id=person.id,
                              scheduled_at=(server_now() + _td(minutes=20)).replace(second=0, microsecond=0),
                              duration_minutes=30, license_plate='Р888РР77', client_phone='79160000900',
                              wheels_assembled=True, wheel_diameter='R18', status='scheduled')
    sdb.add(visit)
    sdb.commit()
    visit_id = visit.id
    auth = {'Authorization': 'Bearer ' + create_token(person.id)}
    sdb.close()

    anna = TestClient(server_app)
    pressed = anna.post(f'/booking/{visit_id}/here', headers=auth)
    check('нажала «Я на месте»', pressed.status_code == 200, pressed.text)

    api = BookingApi(db)
    api._call = call
    api.get_day(date.today())
    waiting = queue.bookings_on_site()
    check('цех видит её на месте', [a.license_plate for a in waiting] == ['Р888РР77'],
          str([a.license_plate for a in waiting]))
    plan = queue.suggestion()
    first = plan[0]
    check('первый свободный пост — ей', first.get('booking') is not None, str(first))

    import services.booking_api as booking_api_module
    real_call = booking_api_module.BookingApi._call
    booking_api_module.BookingApi._call = lambda self, method, path, payload=None: call(method, path, payload)
    try:
        problem = queue.call_booking(waiting[0], first['post'])
    finally:
        booking_api_module.BookingApi._call = real_call
    check('позвали без ошибок', problem is None, str(problem))
    mine = next(a for a in anna.get('/booking/my', headers=auth).json() if a['id'] == visit_id)
    check('в кабинете — пост и схема', mine['called_post'] == first['post'] and mine['scene'],
          str(mine))

    print()
    print('=== Табличка с QR и перевыпуск ===')
    import tempfile as _tmp
    from services.queue_poster_service import QueuePosterService, PosterError
    import services.sync_service as sync_module
    real_sync_call = sync_module.SyncService._call
    real_enabled = sync_module.SyncService.is_enabled
    real_url = sync_module.SyncService.get_url
    sync_module.SyncService._call = lambda self, method, path, payload=None: call(method, path, payload)
    sync_module.SyncService.is_enabled = lambda self: True
    sync_module.SyncService.get_url = lambda self: 'https://lk.example'
    try:
        poster = QueuePosterService(db)
        poster.out_dir = _tmp.mkdtemp()
        first_url = poster.url()
        check('ссылка с ключом точки', first_url.startswith(f'https://lk.example/z/{slug}/q?k='), first_url)
        check('повторно — та же', poster.url() == first_url)
        pdf = poster.make(first_url, 'РИФ')
        with open(pdf, 'rb') as f:
            head = f.read(5)
        check('табличка — PDF', head == b'%PDF-' and os.path.getsize(pdf) > 2000, str(os.path.getsize(pdf)))

        old_key = first_url.split('k=')[1]
        stranger = TestClient(server_app)
        state = stranger.get('/live/state' + q + '&k=' + old_key).json()
        check('по табличке можно встать', state['qr_ok'] is True, str(state))

        new_url = poster.url(reissue=True)
        new_key = new_url.split('k=')[1]
        check('перевыпустили — новый ключ', new_key != old_key, new_url)
        check('и запомнили', poster.cached_url() == new_url)
        state = stranger.get('/live/state' + q + '&k=' + old_key).json()
        check('старая табличка — «устарел»', state['qr_ok'] is False, str(state))
        refused = stranger.post('/live/join' + q + '&k=' + old_key, json={
            'license_plate': 'К100КК77', 'phone': '79160000123',
            'wheel_diameter': 'R16', 'wheels_assembled': True})
        check('встать по старой нельзя', refused.status_code == 403, refused.text)
        ok = stranger.post('/live/join' + q + '&k=' + new_key, json={
            'license_plate': 'К100КК77', 'phone': '79160000123',
            'wheel_diameter': 'R16', 'wheels_assembled': True})
        check('по новой — можно', ok.status_code == 200, ok.text)

        # Связи нет — печатаем последнюю, а перевыпустить нельзя
        def offline(self, method, path, payload=None):
            raise SyncError('нет сети')
        sync_module.SyncService._call = offline
        check('без связи — прежняя ссылка', poster.url() == new_url)
        try:
            poster.url(reissue=True)
            check('без связи не перевыпустить', False)
        except PosterError:
            check('без связи не перевыпустить', True)
    finally:
        sync_module.SyncService._call = real_sync_call
        sync_module.SyncService.is_enabled = real_enabled
        sync_module.SyncService.get_url = real_url

    db.close()

finish()
