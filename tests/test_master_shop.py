"""
Кабинет мастера со стороны цеха (решение владельца 27.10.2026).

Цех отдаёт серверу то, без чего у мастера нет кабинета: ПИН сотрудников,
кто мастер в каком наряде, состав работ и прайс. Обратно забирает
«Начал» / «Готово» с телефона и ответы клиентов на предложения мастеров:
согласие ставит услугу в наряд, «позвоните» и молчание — окно приёмщику.

Проверяем по-настоящему: сервер на своём порту, программа ходит в него
по сети, как в бою.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('master_shop')

import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import timedelta

SYNC_KEY = 'test-sync-master-shop'

_server_db = os.path.join(tempfile.gettempdir(), 'tire_master_shop_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-master-shop-0123456789abcdef'
os.environ['SERVER_SYNC_KEY'] = SYNC_KEY
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = ''

SERVER_DIR = os.path.join(_setup.PROJECT_DIR, 'server')
sys.path.insert(0, SERVER_DIR)

from config import init_db, SessionLocal
from models import Service, WorkOrder
from services import OrderService, EmployeeService
from services.auth_service import AuthService
from services.employee_service import phone_pin_hash
from services.settings_service import SettingsService
from services.shift_service import ShiftService
from services.sync_service import SyncService


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


PORT = free_port()
BASE_URL = f'http://127.0.0.1:{PORT}'


def start_server():
    import uvicorn
    from app.main import app as server_app

    server = uvicorn.Server(uvicorn.Config(server_app, host='127.0.0.1', port=PORT,
                                           log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            with urllib.request.urlopen(f'{BASE_URL}/health', timeout=1):
                return server
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('Сервер не поднялся')


init_db()
server = start_server()

from app.database import SessionLocal as ServerSession
from app.models import (MasterEvent, OpenOrder, ShopEmployee, ShopService, Shop,
                        WorkOffer, Client as SrvClient)
from app.services import master as srv_master

db = SessionLocal()
SettingsService(db).ensure_defaults()
ShiftService(db).open_shift(open_posts=2)
employees = EmployeeService(db)
employees.register_employee(1, name='Сергей')
employees.register_employee(2, name='Алексей')
employees.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0, price_r17=1200.0))
db.add(Service(name='Замена вентиля', vehicle_type='car', price_r16=200.0))
db.commit()
tire_service = db.query(Service).filter(Service.name == 'Шиномонтаж').first()
valve = db.query(Service).filter(Service.name == 'Замена вентиля').first()

orders = OrderService(db)
order = orders.create_order('А123ВВ777', 'R16', 'car', client_name='Иван',
                            client_phone='79160000001')
orders.add_service_to_order(order.id, tire_service.id)
db.commit()

sync = SyncService(db)
sync.save_settings(BASE_URL, SYNC_KEY, enabled=True)

print('=== ПИН для телефона ставит приёмщик по админскому PIN ===')
admin = SettingsService(db).get('admin_pin') or '0000'
try:
    employees.set_phone_pin(1, '4827', 'неверный')
    check('чужой админский PIN — отказ', False)
except ValueError as e:
    check('чужой админский PIN — отказ', 'PIN' in str(e), str(e))
for simple in ('1111', '1234', '12a4'):
    try:
        employees.set_phone_pin(1, simple, admin)
        check(f'простой ПИН {simple} не принят', False)
    except ValueError:
        check(f'простой ПИН {simple} не принят', True)
if not AuthService(db).verify_pin(admin):
    check('админский PIN по умолчанию известен тесту', False, admin)
employees.set_phone_pin(1, '4827', admin)
check('ПИН задан отпечатком, сам ПИН не хранится',
      db.query(type(employees.get_all_employees()[0])).get(1).phone_pin_hash == phone_pin_hash('4827'))

print('\n=== Обмен: ПИН, мастера наряда и прайс ===')
result = sync.run_once()
srv = ServerSession()
shop = srv.query(Shop).first()
sergey = srv.query(ShopEmployee).filter(ShopEmployee.local_id == 1).first()
check('ПИН на сервере — тот же отпечаток', sergey.pin_hash == phone_pin_hash('4827'))
alexey = srv.query(ShopEmployee).filter(ShopEmployee.local_id == 2).first()
check('у кого ПИН нет — пусто', alexey.pin_hash is None)
open_order = srv.query(OpenOrder).filter(OpenOrder.local_id == order.id).first()
check('открытый наряд с мастерами и составом',
      open_order is not None and open_order.master_ids() == [1]
      and 'Шиномонтаж' in (open_order.services or '') and open_order.wheel_diameter == 'R16'
      and open_order.client_name == 'Иван', str(open_order and open_order.__dict__)[:300])
prices = {row.name: row.prices for row in srv.query(ShopService).all()}
check('прайс по радиусам', '"R16": 200.0' in prices.get('Замена вентиля', '')
      and '"R17": 1200.0' in prices.get('Шиномонтаж', ''), str(prices))
offerable = {item['name']: item['price'] for item in srv_master.offerable(srv, shop, open_order)}
check('мастер предложит по цене R16', offerable == {'Шиномонтаж': 1000, 'Замена вентиля': 200},
      str(offerable))

print('\n=== Выключатель заработка ===')
SettingsService(db).set('master_salary_visible', '1')
sync.run_once()
srv.expire_all()
check('владелец включил — сервер знает', srv_master.salary_visible(srv, shop))

print('\n=== Мастер нажал «Начал» и «Готово» ===')
srv.add(MasterEvent(shop_id=shop.id, order_local_id=order.id, kind='start',
                    employee_local_id=1, author='Сергей'))
srv.commit()
answer = sync.master_exchange()
db.expire_all()
started = db.query(WorkOrder).get(order.id)
check('цех начал работу сам', started.started_at is not None and answer['changed']
      and order.id in answer['orders'], str(answer))
srv.add(MasterEvent(shop_id=shop.id, order_local_id=order.id, kind='done',
                    employee_local_id=1, author='Сергей', told=True))
srv.commit()
sync.master_exchange()
db.expire_all()
done = db.query(WorkOrder).get(order.id)
check('и закончил, клиенту второй раз не говорить',
      done.finished_at is not None and done.client_told_at is not None)
srv.expire_all()
check('события забраны', srv.query(MasterEvent).filter(MasterEvent.taken_at.is_(None)).count() == 0)

print('\n=== Клиент согласился на работу ===')
srv_client = srv.query(SrvClient).first()


def offer(state, kind_minutes=0, items=None):
    row = WorkOffer(shop_id=shop.id, client_id=srv_client.id, order_local_id=order.id,
                    license_plate='А123ВВ777', token=os.urandom(8).hex(),
                    items=items or f'[{{"local_id": {valve.id}, "name": "Замена вентиля", "price": 200}}]',
                    total=200, author='Сергей', employee_local_id=1, state=state)
    if state != 'pending':
        row.answered_at = row.created_at
    srv.add(row)
    srv.commit()
    if kind_minutes:
        row.created_at = row.created_at - timedelta(minutes=kind_minutes)
        srv.commit()
    return row


offer('yes')
answer = sync.master_exchange()
db.expire_all()
names = [item.service.name for item in orders.get_order_items(order.id)]
check('услуга сама встала в наряд', 'Замена вентиля' in names, str(names))
check('приёмщику окно «Клиент согласен»',
      answer['notes'] and answer['notes'][0][0] == 'Клиент согласен'
      and 'Добавлено в наряд: Замена вентиля' in answer['notes'][0][1], str(answer['notes']))

offer('call')
answer = sync.master_exchange()
check('«Позвоните мне» — окно с телефоном',
      answer['notes'][0][0] == 'Клиент просит позвонить' and '79160000001' in answer['notes'][0][1],
      str(answer['notes']))

offer('pending', kind_minutes=11)
answer = sync.master_exchange()
check('молчит 10 минут — окно «позвоните»',
      answer['notes'][0][0] == 'Клиент молчит', str(answer['notes']))
check('второй раз не всплывает', sync.master_exchange()['notes'] == [])

offer('yes', items='[{"local_id": 99999, "name": "Нет такой", "price": 1}]')
answer = sync.master_exchange()
check('услуги нет в прайсе — «добавьте вручную», а не тишина',
      'Добавьте вручную' in answer['notes'][0][1], str(answer['notes']))

print('\n=== ПИН сняли — на сервере тоже ===')
employees.set_phone_pin(1, '', admin)
sync.run_once()
srv.expire_all()
check('сервер знает, что ПИН снят',
      srv.query(ShopEmployee).filter(ShopEmployee.local_id == 1).first().pin_hash is None)

srv.close()
db.close()
server.should_exit = True
finish()
