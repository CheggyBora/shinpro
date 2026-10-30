"""
Обмен не падает от длинных строк (30.10.2026).

Номер машины в 21 знак ронял весь обмен точки ошибкой 500: на сервере
колонка была короче, чем в цеху, — и вместе с ним не доезжал ключ
звонков. SQLite длину не проверяет, боевой PostgreSQL — проверяет,
поэтому обычные тесты этого не видели.

Здесь программа цеха с настоящими данными — наряд, касса, хранение,
выплата, запись, — где КАЖДОЕ текстовое поле заполнено до предела,
отдаёт всё серверу. Проверяем, что:
  · сервер принял обмен целиком;
  · ни одна строка в базе сервера не длиннее своей колонки — то есть
    на PostgreSQL ошибки не было бы;
  · ключ звонков доехал.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('sync_long_values')

import os
import sys
import tempfile

_server_db = os.path.join(tempfile.gettempdir(), 'tire_sync_long_values_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-sync-long-values-0123456'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
sys.path.insert(0, os.path.join(_setup.PROJECT_DIR, 'server'))

os.chdir(_setup.PROJECT_DIR)
shown = _setup.silence_dialogs()

from sqlalchemy import String, Text, inspect as sa_inspect, text

from config import init_db, SessionLocal, Base as ShopBase
from init_data import initialize_data
from models import Employee, TireStorage, METHOD_CASH
from services import PayoutService
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.cash_service import CashService
from services.settings_service import SettingsService
from services.sync_service import SyncService
from models.cash import KIND_OUT

init_db()
initialize_data()
db = SessionLocal()

# --- Настоящие данные: смена, мастер, наряд, касса -------------------
ShiftService(db).open_shift(cash_start='1000')
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()
orders = OrderService(db)
order = orders.create_order('А100АА77', 'R16', 'car', client_name='Иван',
                             client_phone='+79001234567')
orders.add_service_to_order(order.id, 1)
order.recommendations = 'Заменить колодки'
db.commit()
SalaryService(db).process_payment(order.id, 'mixed', orders.calculate_total(order.id), 100)
CashService(db).create(KIND_OUT, 'Прочее', 50, note='заметка')
db.add(TireStorage(car_number='А100АА77', storage_type='Шины с дисками', diameter='R17',
                   brand='Nokian', wheel_type='Литые', price=5000.0, status='stored'))
db.commit()
PayoutService(db).pay(1, 100, METHOD_CASH, pin='0000', allow_advance=True,
                      comment='аванс')
settings = SettingsService(db)
settings.set('call_token', 'KEY-FROM-FLASHCALL')
settings.set('call_provider', 'flashcall')

# --- Каждое текстовое поле — до предела --------------------------------
# Служебные коды (способ оплаты, статус, направление) остаются как были:
# их сервер разбирает, а не хранит как есть. Проверяем именно длину
KEEP = {'payment_method', 'status', 'directions', 'kind', 'method', 'uid', 'role',
        'vehicle_type', 'wheel_diameter', 'refund_type', 'call_token', 'call_provider',
        'key', 'source', 'direction', 'wash_class', 'category', 'unit'}
filled = 0
with SessionLocal() as raw:
    for table in ShopBase.metadata.sorted_tables:
        for column in table.columns:
            if not isinstance(column.type, (String, Text)) or column.name in KEEP \
                    or column.primary_key or column.foreign_keys:
                continue
            limit = getattr(column.type, 'length', None) or 600
            # Разное у каждой строки — уникальные колонки не споткнутся
            raw.execute(text(
                f'UPDATE {table.name} SET {column.name} = '
                f"substr(CAST(rowid AS TEXT) || :fill, 1, :limit) "
                f'WHERE {column.name} IS NOT NULL'),
                {'fill': 'Ж' * limit, 'limit': limit})
            filled += 1
    raw.commit()
check('текстовых полей заполнено до предела', filled > 50, str(filled))

# --- Сервер ------------------------------------------------------------
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal as ServerSession, Base as ServerBase
from app.services import tenancy, callcheck
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.database import _fit_strings

# Страховку сервера (обрезать длинное, а не падать) снимаем: проверяем,
# что колонки сами вмещают всё, что шлёт цех. Страховка — отдельно, ниже
event.remove(Session, 'before_flush', _fit_strings)

# Сервер поднимает свою базу при запуске — заходим в него сразу
http = TestClient(app)
http.__enter__()
server_db = ServerSession()
account, shop, sync_key = tenancy.create_account(server_db, 'Шиномонтаж «РИФ»')

payload = SyncService(SessionLocal()).collect_push()
import json
from services.sync_service import _encode
body = json.loads(json.dumps(payload, ensure_ascii=False, default=_encode))

answer = http.post('/sync/push', headers={'X-Sync-Key': sync_key}, json=body)
check('сервер принял обмен', answer.status_code == 200,
      f'{answer.status_code} {answer.text[:300]}')

server_db.expire_all()
too_long = []
for table in ServerBase.metadata.sorted_tables:
    columns = [c for c in table.columns
               if isinstance(c.type, String) and getattr(c.type, 'length', None)]
    if not columns:
        continue
    for row in server_db.execute(text(f'SELECT {", ".join(c.name for c in columns)} '
                                      f'FROM {table.name}')):
        for column, value in zip(columns, row):
            if isinstance(value, str) and len(value) > column.type.length:
                too_long.append(f'{table.name}.{column.name}: {len(value)} > {column.type.length}')
check('ни одна строка не длиннее колонки (PostgreSQL принял бы)', not too_long,
      '; '.join(sorted(set(too_long))[:10]))
check('ключ звонков доехал', callcheck.available(server_db, shop))

print('\n=== Страховка: длиннее колонки — обрезать, а не падать ===')
event.listen(Session, 'before_flush', _fit_strings)
from app.models import Car
car = server_db.query(Car).first()
car.license_plate = 'Ж' * 80
server_db.commit()
server_db.refresh(car)
check('обрезано до длины колонки', car.license_plate == 'Ж' * 50, str(len(car.license_plate)))
server_db.close()
http.__exit__(None, None, None)

finish()
