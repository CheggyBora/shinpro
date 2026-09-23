"""
Очистка рабочих данных: клиенты и машины уходят, прайс-лист остаётся.

Заводить заново 42 услуги с ценами, себестоимостью и длительностями
после каждой очистки было бы мучением, поэтому справочники не трогаются.
"""
import _setup
from _setup import check, finish

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

WORK_DIR = os.path.join(tempfile.gettempdir(), 'tire_shop_test_clear')
shutil.rmtree(WORK_DIR, ignore_errors=True)
os.makedirs(WORK_DIR)
DB_PATH = os.path.join(WORK_DIR, 'tire_shop.db')
os.environ['DATABASE_URL'] = f'sqlite:///{DB_PATH}'

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Service, Client, Car, WorkOrder, SalaryTransaction, TireStorage, AuditLog
from services import OrderService, SalaryService, EmployeeService, AuditService
from services.shift_service import ShiftService

init_db()
initialize_data()

db = SessionLocal()
ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

# Настраиваем прайс-лист: именно это не должно потеряться
service = db.query(Service).filter(Service.name == 'Шиномонтаж').first()
service.consumable_cost = 55.0
service.duration_minutes = 17
db.commit()

order_service = OrderService(db)
order = order_service.create_order('А123ВВ777', 'R16', 'car',
                                   client_name='Андрей', client_phone='79099018931')
order_service.add_service_to_order(order.id, service.id)
SalaryService(db).process_payment(order.id, 'cash', order_service.calculate_total(order.id))
AuditService(db).log(AuditService.ORDER_DELETE, 'проверочная запись')
db.add(TireStorage(car_number='А123ВВ777', storage_type='Шины с дисками',
                   diameter='R16', price=5000.0, status='stored'))
db.commit()

services_before = db.query(Service).count()
db.close()

SCRIPT = os.path.join(_setup.PROJECT_DIR, 'clear_working_data.py')
env = dict(os.environ, PYTHONIOENCODING='utf-8')


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          env=env, cwd=WORK_DIR)


def counts():
    c = sqlite3.connect(DB_PATH)
    try:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ('clients', 'cars', 'work_orders', 'work_order_items',
                          'salary_transactions', 'tire_storage', 'shifts',
                          'audit_log', 'services', 'settings', 'employees')}
    finally:
        c.close()


before = counts()
print(f'Заполнено: клиентов {before["clients"]}, машин {before["cars"]}, '
      f'нарядов {before["work_orders"]}, услуг {before["services"]}')

print('\n=== Предпросмотр ничего не удаляет ===')
result = run('--dry-run')
check('предпросмотр отработал', result.returncode == 0, result.stderr[-200:])
check('данные на месте', counts() == before)
check('показал, что будет удалено', 'Будет удалено' in result.stdout)
check('показал, что останется', 'Останется без изменений' in result.stdout)

print('\n=== Очистка ===')
result = run('--yes')
check('очистка отработала', result.returncode == 0, result.stderr[-300:])

after = counts()
for table, title in [('clients', 'клиенты'), ('cars', 'машины'),
                     ('work_orders', 'наряды'), ('work_order_items', 'позиции'),
                     ('salary_transactions', 'начисления ЗП'),
                     ('tire_storage', 'хранение'), ('shifts', 'смены'),
                     ('audit_log', 'журнал')]:
    check(f'{title} удалены', after[table] == 0, str(after[table]))

print('\n=== Справочники сохранены ===')
check('прайс-лист на месте', after['services'] == services_before,
      f'{after["services"]} из {services_before}')
check('настройки на месте', after['settings'] > 0, str(after['settings']))
check('сотрудники сохранены', after['employees'] == 1, str(after['employees']))

conn = sqlite3.connect(DB_PATH)
row = conn.execute("SELECT consumable_cost, duration_minutes FROM services "
                   "WHERE name = 'Шиномонтаж' AND vehicle_type = 'car'").fetchone()
conn.close()
check('себестоимость расходников не потеряна', row[0] == 55.0, str(row[0]))
check('длительность услуги не потеряна', row[1] == 17, str(row[1]))

print('\n=== Резервная копия ===')
backups = os.path.join(WORK_DIR, 'backups')
check('копия создана перед удалением',
      os.path.isdir(backups) and len(os.listdir(backups)) == 1,
      str(os.listdir(backups)) if os.path.isdir(backups) else 'папки нет')

conn = sqlite3.connect(os.path.join(backups, os.listdir(backups)[0]))
check('в копии данные сохранились',
      conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 1)
conn.close()

print('\n=== Нумерация начинается заново ===')
from config import SessionLocal as NewSession
db = NewSession()
ShiftService(db).open_shift(open_posts=2)
EmployeeService(db).start_shift(1)
new_order = OrderService(db).create_order('К900ОР99', 'R16', 'car')
check('следующий наряд снова №1', new_order.id == 1, f'получился №{new_order.id}')
db.close()

print('\n=== Повторная очистка на пустой базе ===')
result = run('--yes')
check('на пустой базе не падает', result.returncode == 0, result.stderr[-200:])

finish()
