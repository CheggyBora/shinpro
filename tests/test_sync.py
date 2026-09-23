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

# --------------------------------------------------------------------
print('\n=== Для дашборда: деньги, позиции и начисления ===')
srv = ServerSession()
from app.models import (VisitItem as SrvItem, SalaryAccrual as SrvAccrual,
                        ShopEmployee as SrvEmployee, ShopShift as SrvShift)

visit = srv.query(SrvVisit).filter(SrvVisit.shop_id == order.id).first()
check('расходники доехали', visit.consumables_amount is not None,
      str(visit.consumables_amount))
check('база для зарплаты доехала', visit.salary_base == order.salary_base,
      f'{visit.salary_base} против {order.salary_base}')
check('способ оплаты доехал', visit.payment_method == 'cash',
      str(visit.payment_method))
check('смена наряда доехала', visit.shift_shop_id == order.shift_id,
      str(visit.shift_shop_id))
check('отметка изменения проставлена', visit.changed_at is not None)

lines = srv.query(SrvItem).filter(SrvItem.visit_id == visit.id).all()
check('позиция наряда доехала', len(lines) == 1, str(len(lines)))
check('название услуги на месте', lines[0].service_name == 'Шиномонтаж',
      lines[0].service_name)
# 5% — автоматическая скидка за полные данные клиента. Она уже сидит
# в позиции: сумма наряда складывается из позиций, и вычитать скидку
# второй раз на дашборде не придётся
check('скидка учтена в позиции', lines[0].discount_percent == 5,
      str(lines[0].discount_percent))
check('цена позиции со скидкой', lines[0].total == 950.0, str(lines[0].total))
check('сумма наряда — сумма позиций', visit.total_amount == lines[0].total,
      f'{visit.total_amount} против {lines[0].total}')

accruals = srv.query(SrvAccrual).filter(SrvAccrual.visit_id == visit.id).all()
check('начисление доехало', len(accruals) == 1, str(len(accruals)))
check('начислено 40% от базы 950', accruals[0].amount == 380.0,
      str(accruals[0].amount))
check('начисление привязано к мастеру', accruals[0].employee_shop_id == 1)

check('сотрудник доехал', srv.query(SrvEmployee).count() >= 1)
check('смена доехала', srv.query(SrvShift).count() >= 1)
srv.close()

print('\n=== Имя сотрудника доезжает и показывается в начислениях ===')
employees.set_name(1, 'Игорь')
sync.run_once()
srv = ServerSession()
row = srv.query(SrvEmployee).filter(SrvEmployee.shop_id == 1).first()
check('имя на сервере', row.name == 'Игорь', str(row.name))
check('подпись с именем и номером', row.title == 'Игорь (№1)', row.title)
srv.close()

print('\n=== Повторная присылка не плодит позиции ===')
sync.run_once()
sync.run_once()
srv = ServerSession()
visit = srv.query(SrvVisit).filter(SrvVisit.shop_id == order.id).first()
check('позиция по-прежнему одна',
      srv.query(SrvItem).filter(SrvItem.visit_id == visit.id).count() == 1)
check('начисление по-прежнему одно',
      srv.query(SrvAccrual).filter(SrvAccrual.visit_id == visit.id).count() == 1)
srv.close()

print('\n=== Старые наряды второй раз не отправляются ===')
srv = ServerSession()
until = srv.query(SrvVisit).filter(SrvVisit.shop_id == order.id).first().changed_at
srv.close()
check('сервер знает, докуда у него всё есть', until is not None, str(until))

state = sync.test_connection()
check('отметка отдаётся цеху', state.get('visits_changed_until') is not None,
      str(state.get('visits_changed_until')))

from datetime import datetime as _dt
# Отметка с нахлёстом в час — наряд оплачен только что и попадёт в посылку.
# А вот наряд недельной давности уже нет: ради этого всё и затевалось
week_ago = _dt.now() - timedelta(days=7)
old_order = orders.create_order('С555СС77', 'R16', 'car')
orders.add_service_to_order(old_order.id, service_row.id)
SalaryService(db).process_payment(old_order.id, 'cash',
                                  orders.calculate_total(old_order.id))
db.query(WorkOrder).filter(WorkOrder.id == old_order.id).update(
    {'paid_at': week_ago})
db.commit()

portion = sync.collect_push(changed_since=_dt.now() - timedelta(hours=2))
sent_ids = [item['shop_id'] for item in portion['visits']]
check('недельный наряд не поехал', old_order.id not in sent_ids, str(sent_ids))
check('свежий наряд поехал', order.id in sent_ids, str(sent_ids))

everything = sync.collect_push()
check('без отметки уходит вся история',
      old_order.id in [item['shop_id'] for item in everything['visits']])

print('\n=== Возврат досылается, хотя наряд старый ===')
db.query(WorkOrder).filter(WorkOrder.id == old_order.id).update(
    {'refunded_amount': 500.0, 'refunded_at': _dt.now(),
     'refund_type': 'refund', 'refund_reason': 'Клиент вернул колесо'})
db.commit()

portion = sync.collect_push(changed_since=_dt.now() - timedelta(hours=2))
returned = [item for item in portion['visits'] if item['shop_id'] == old_order.id]
check('наряд с возвратом уехал заново', len(returned) == 1, str(len(returned)))
check('сумма возврата в посылке', returned[0]['refunded_amount'] == 500.0)

sync.run_once()
srv = ServerSession()
refunded = srv.query(SrvVisit).filter(SrvVisit.shop_id == old_order.id).first()
check('возврат виден на сервере', refunded.refunded_amount == 500.0,
      str(refunded.refunded_amount))
check('причина возврата на месте', 'колесо' in (refunded.refund_reason or ''))
srv.close()

print('\n=== Удалённый наряд помечен и скрыт от клиента ===')
db.query(WorkOrder).filter(WorkOrder.id == old_order.id).update(
    {'is_deleted': True, 'deleted_at': _dt.now(),
     'deleted_reason': 'Ошибка приёмщика'})
db.commit()
sync.run_once()

srv = ServerSession()
deleted = srv.query(SrvVisit).filter(SrvVisit.shop_id == old_order.id).first()
check('на сервере наряд помечен удалённым', deleted.is_deleted is True)
check('а сам не пропал — след остался', deleted.total_amount > 0)
srv.close()

# --------------------------------------------------------------------
print('\n=== Выплата зарплаты: из цеха наверх ===')
from services import PayoutService
from models import METHOD_CASH, METHOD_CARD, SalaryPayout

payouts = PayoutService(db)
paid = payouts.pay(1, 100, METHOD_CASH, pin='0000', allow_advance=True)
sync.run_once()

srv = ServerSession()
from app.models import SalaryPayout as SrvPayout, PENDING as SRV_PENDING

up = srv.query(SrvPayout).filter(SrvPayout.shop_id == paid.id).first()
check('выплата уехала на сервер', up is not None)
check('сумма совпала', up and up.amount == 100.0, str(up.amount if up else None))
check('способ — наличные', up and up.method == 'cash')
check('видно, что выдали в цеху', up and up.source == 'shop')
srv.close()

print('\n=== Владелец отметил перевод на карту ===')
srv = ServerSession()
from app.services.dashboard_service import DashboardService
from app.models import ShopEmployee as SrvEmployee

# Сотрудник на сервере появляется при обмене — он уже там
check('сотрудник известен серверу',
      srv.query(SrvEmployee).filter(SrvEmployee.shop_id == 1).first() is not None)

card = DashboardService(srv).pay_to_card(1, 250, 'за сентябрь')
check('выплата создана на сервере', card.id is not None)
check('помечена как ждущая цеха', card.sync_state == SRV_PENDING)
check('способ — карта', card.method == 'card')

balances = {row['employee_shop_id']: row
            for row in DashboardService(srv).salary_balances()}
check('в остатке на сервере перевод уже учтён',
      balances[1]['waiting'] == 250.0, str(balances[1]))
srv.close()

print('\n=== Цех забирает перевод при обмене ===')
result = sync.run_once()
check('выплата спустилась', result['new_payouts'] == 1,
      str(result['new_payouts']))

local = db.query(SalaryPayout).filter(
    SalaryPayout.server_id == card.id).first()
check('в базе цеха появилась запись', local is not None)
check('сумма та же', local and local.amount == 250.0,
      str(local.amount if local else None))
check('способ — карта', local and local.method == METHOD_CARD)
check('видно, что отметил владелец', local and local.source == 'dashboard')

print('\n=== Повторно та же выплата не придёт ===')
result = sync.run_once()
check('второй раз не спустилась', result['new_payouts'] == 0,
      str(result['new_payouts']))
check('и второй записи не появилось',
      db.query(SalaryPayout).filter(
          SalaryPayout.server_id == card.id).count() == 1)

srv = ServerSession()
taken = srv.query(SrvPayout).filter(SrvPayout.id == card.id).first()
check('сервер знает, что цех её забрал', taken.sync_state == 'taken',
      str(taken.sync_state))
check('и знает её номер в цеху', taken.shop_id == local.id,
      f'{taken.shop_id} против {local.id}')
srv.close()

print('\n=== Отметка времени последнего обмена ===')
last = sync.last_success()
check('время обмена записано', last is not None, str(last))
check('оно свежее', (datetime.now() - last).total_seconds() < 120, str(last))

db.close()
finish()
