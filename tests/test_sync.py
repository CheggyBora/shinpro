"""
Копия наверх: что программа цеха отдаёт серверу приложения.

Записи здесь не проверяются: они живут на сервере целиком и
проверяются отдельно, в test_booking_remote.py. Наверх уходит только
то, что клиент смотрит в приложении, — клиенты, машины, история
визитов, хранение и загрузка цеха.

Проверяем по-настоящему: поднимаем сервер на своём порту и заставляем
программу цеха ходить в него по сети, как она будет ходить в бою.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('sync')

import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta

SYNC_KEY = 'test-sync-key'

# Сервер настраиваем ДО импорта: он читает переменные при загрузке
_server_db = os.path.join(tempfile.gettempdir(), 'tire_sync_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret'
os.environ['SERVER_SYNC_KEY'] = SYNC_KEY
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

SERVER_DIR = os.path.join(_setup.PROJECT_DIR, 'server')
sys.path.insert(0, SERVER_DIR)

from config import init_db, SessionLocal
from models import Service, TireStorage, WorkOrder
from services import (OrderService, SalaryService, EmployeeService,
                      ClientService)
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.sync_service import SyncService, SyncError


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


PORT = free_port()
BASE_URL = f'http://127.0.0.1:{PORT}'


def start_server():
    """Поднять сервер в отдельном потоке и дождаться, пока он ответит."""
    import uvicorn
    from app.main import app as server_app

    config = uvicorn.Config(server_app, host='127.0.0.1', port=PORT,
                            log_level='error')
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(100):
        try:
            with urllib.request.urlopen(f'{BASE_URL}/health', timeout=1):
                return server
        except Exception:
            time.sleep(0.1)

    raise RuntimeError('Сервер не поднялся')


print('=== Поднимаем сервер ===')
server = start_server()
check('сервер отвечает', True)

from app.database import SessionLocal as ServerSession
from app.models import (Client as SrvClient, Car as SrvCar,
                        Visit as SrvVisit, StoredSet as SrvStored,
                        QueueSnapshot as SrvQueue, ShopSetting, PENDING)

# --------------------------------------------------------------------
init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

ShiftService(db).open_shift(open_posts=2)
employees = EmployeeService(db)
employees.register_employee(1)
employees.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.commit()

orders = OrderService(db)
clients = ClientService(db)
sync = SyncService(db)

print('\n=== Пока обмен выключен, ничего не происходит ===')
check('обмен выключен', sync.is_enabled() is False)
stopped = False
try:
    sync.run_once()
except SyncError as e:
    stopped = 'выключен' in str(e)
check('обмен не запускается', stopped)

print('\n=== Настройка обмена ===')
sync.save_settings(BASE_URL, SYNC_KEY, enabled=True)
check('обмен включился', sync.is_enabled() is True)
check('адрес сохранён', sync.get_url() == BASE_URL, sync.get_url())

print('\n=== Неверный ключ не пускает ===')
sync.save_settings(BASE_URL, 'wrong-key', enabled=True)
rejected = False
try:
    sync.test_connection()
except SyncError as e:
    rejected = 'отклонил' in str(e)
check('чужой ключ отвергнут', rejected)
sync.save_settings(BASE_URL, SYNC_KEY, enabled=True)

state = sync.test_connection()
check('связь есть', 'clients' in state, str(state))

# --------------------------------------------------------------------
print('\n=== Наверх уходит то, что видит клиент ===')
order = orders.create_order('А123ВВ777', 'R16', 'car',
                            client_name='Андрей', client_phone='79099018931')
service_row = db.query(Service).first()
orders.add_service_to_order(order.id, service_row.id)
order.recommendations = 'Через 5000 км заменить передние колодки'
db.commit()
SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))

db.add(TireStorage(car_number='А123ВВ777', storage_type='Шины с дисками',
                   diameter='R17', brand='Nokian', wheel_type='Литые',
                   price=5000.0, status='stored'))
db.commit()

result = sync.run_once()
check('обмен прошёл', result['sent']['clients'] > 0, str(result['sent']))

srv = ServerSession()
check('клиент ушёл наверх', srv.query(SrvClient).count() >= 1,
      str(srv.query(SrvClient).count()))
check('машина ушла наверх', srv.query(SrvCar).count() >= 1)
check('визит ушёл наверх', srv.query(SrvVisit).count() == 1,
      str(srv.query(SrvVisit).count()))

visit = srv.query(SrvVisit).first()
check('состав работ на месте', 'Шиномонтаж' in (visit.services or ''),
      str(visit.services))
check('рекомендация мастера на месте',
      'колодки' in (visit.recommendations or ''), str(visit.recommendations))
check('сумма визита совпала', visit.total_amount == order.total_amount,
      f'{visit.total_amount} против {order.total_amount}')
check('визит привязан к клиенту', visit.client_id is not None)

check('хранение ушло наверх', srv.query(SrvStored).count() == 1)
stored = srv.query(SrvStored).first()
check('марка шин на месте', stored.brand == 'Nokian')
check('владелец комплекта найден', stored.client_id is not None)

check('очередь ушла', srv.query(SrvQueue).count() > 0)

print('\n=== Настройки цеха ушли наверх ===')
minutes = srv.query(ShopSetting).filter(
    ShopSetting.key == 'booking_minutes_assembled').first()
check('время работ по колёсам передано', minutes is not None,
      str(minutes.value if minutes else None))
name = srv.query(ShopSetting).filter(ShopSetting.key == 'shop_name').first()
check('название шиномонтажа передано', name is not None and bool(name.value),
      str(name.value if name else None))

print('\n=== Записи наверх НЕ уходят ===')
from app.models import Appointment as SrvAppointment
check('обмен записей не касается', srv.query(SrvAppointment).count() == 0,
      str(srv.query(SrvAppointment).count()))

print('\n=== Повторный обмен не плодит дублей ===')
sync.run_once()
check('визит по-прежнему один', srv.query(SrvVisit).count() == 1,
      str(srv.query(SrvVisit).count()))
check('комплект по-прежнему один', srv.query(SrvStored).count() == 1)
srv.close()

# --------------------------------------------------------------------
print('\n=== Заявка на комплект попадает кладовщику ===')
srv = ServerSession()
stored_row = srv.query(SrvStored).first()
stored_row.requested_for = datetime.now() + timedelta(days=2)
stored_row.request_state = PENDING
srv.commit()
stored_shop_id = stored_row.shop_id
srv.close()

result = sync.run_once()
check('заявка спустилась', result['new_storage_requests'] == 1,
      str(result['new_storage_requests']))

local_set = db.query(TireStorage).filter(
    TireStorage.id == stored_shop_id).first()
check('в комментарии комплекта появилась заявка',
      'приложение' in (local_set.comments or ''), str(local_set.comments))

print('\n=== Повторно та же заявка не приходит ===')
result = sync.run_once()
check('второй раз не спустилась', result['new_storage_requests'] == 0,
      str(result['new_storage_requests']))

# --------------------------------------------------------------------
print('\n=== Нет связи — цех работает дальше ===')
sync.save_settings('http://127.0.0.1:1', SYNC_KEY, enabled=True)
failed = False
try:
    sync.run_once()
except SyncError as e:
    failed = 'связи' in str(e).lower() or 'ошибка' in str(e).lower()
check('обмен честно сообщил о сбое', failed)

# Самое важное: цех при этом принимает машины как обычно
offline_order = orders.create_order('О000ОО77', 'R16', 'car')
orders.add_service_to_order(offline_order.id, service_row.id)
SalaryService(db).process_payment(offline_order.id, 'cash',
                                  orders.calculate_total(offline_order.id))
paid = db.query(WorkOrder).filter(WorkOrder.id == offline_order.id).first()
check('наряд создан и оплачен без интернета', paid.status == 'paid', paid.status)
check('чек посчитан', paid.total_amount > 0, str(paid.total_amount))

print('\n=== Связь вернулась — накопленное ушло наверх ===')
sync.save_settings(BASE_URL, SYNC_KEY, enabled=True)
sync.run_once()

srv = ServerSession()
check('наряд, сделанный офлайн, поднялся',
      srv.query(SrvVisit).filter(
          SrvVisit.shop_id == offline_order.id).first() is not None)
srv.close()

print('\n=== Отметка времени последнего обмена ===')
last = sync.last_success()
check('время обмена записано', last is not None, str(last))
check('оно свежее', (datetime.now() - last).total_seconds() < 120, str(last))

db.close()
finish()
