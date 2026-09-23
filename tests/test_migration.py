"""
Миграция рабочей базы: старая схема с дублями приводится в порядок.

Проверяется на базе, собранной так, как её собирала прежняя версия
программы: без cars.client_id, с задвоенными машинами и клиентами.
"""
import _setup
from _setup import check, finish

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

# Отдельная папка: миграция кладёт рядом с базой папку backups
WORK_DIR = os.path.join(tempfile.gettempdir(), 'tire_shop_test_migration')
shutil.rmtree(WORK_DIR, ignore_errors=True)
os.makedirs(WORK_DIR)
DB_PATH = os.path.join(WORK_DIR, 'tire_shop.db')
os.environ['DATABASE_URL'] = f'sqlite:///{DB_PATH}'

from config import init_db

init_db()

# --- Откатываем схему к тому виду, что был до правок ------------------
conn = sqlite3.connect(DB_PATH)
conn.execute("DROP TABLE cars")
conn.execute("""CREATE TABLE cars (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    license_plate VARCHAR(50) NOT NULL UNIQUE,
    vehicle_type VARCHAR(20),
    wheel_diameter VARCHAR(10))""")
conn.execute("DROP TABLE clients")
conn.execute("""CREATE TABLE clients (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    client_number VARCHAR(50),
    name VARCHAR(200),
    phone VARCHAR(50))""")
conn.execute("DROP TABLE shifts")
conn.execute("""CREATE TABLE shifts (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    start_time DATETIME,
    end_time DATETIME,
    status VARCHAR(20),
    total_salary FLOAT)""")

# --- Наполняем так, как это делала прежняя программа -------------------
for car_id, plate in [
    (1, 'А123ВВ777'),   # эталон
    (2, 'а123вв777'),   # он же в нижнем регистре
    (3, 'A123BB777'),   # он же латиницей
    (4, 'К900ОР99'),
    (5, ' К900ОР99 '),  # он же с пробелами
    (6, 'Н555НН50'),
]:
    conn.execute("INSERT INTO cars (id, license_plate, vehicle_type, wheel_diameter) "
                 "VALUES (?,?,?,?)", (car_id, plate, 'car', 'R16'))

for client_id, name, phone in [
    (1, 'Андрей', '+7 (909) 901-89-31'),
    (2, 'Андрей', '89099018931'),             # он же
    (3, None, '9099018931'),                  # он же, без имени
    (4, 'Хранение (Шины с дисками)', None),   # служебная запись
    (5, 'Пётр', '79161234567'),
]:
    conn.execute("INSERT INTO clients (id, client_number, name, phone) VALUES (?,?,?,?)",
                 (client_id, None, name, phone))

for order_id, car_id, client_id in [
    (1, 1, 1), (2, 2, 2), (3, 3, 3), (4, 4, 1), (5, 5, 2), (6, 6, 5), (7, 1, 4),
]:
    conn.execute("""INSERT INTO work_orders
        (id, car_id, client_id, wheel_diameter, vehicle_type, status, total_amount,
         paid_at, created_at, is_deleted, auto_discount, general_discount, rim_discount)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, car_id, client_id, 'R16', 'car', 'paid', 1000.0,
         '2026-07-01 10:00:00', '2026-07-01 10:00:00', 0, 0, 0, 0))

conn.execute("""INSERT INTO tire_storage (id, car_number, storage_type, diameter, price, status)
                VALUES (1, 'a123bb777', 'Шины с дисками', 'R16', 5000.0, 'stored')""")

# Смена, записанная по всемирному времени, как это делала прежняя версия:
# наряд оплачен в 13:00 по местным часам, а смена «началась» в 10:00 по UTC
conn.execute("""INSERT INTO shifts (id, start_time, status, total_salary)
                VALUES (1, '2026-07-01 10:00:00', 'closed', 0.0)""")
conn.commit()

orders_before = conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0]
conn.close()

MIGRATION = os.path.join(_setup.PROJECT_DIR, 'migrate_clients_and_plates.py')
env = dict(os.environ, PYTHONIOENCODING='utf-8')


def run_migration(*args):
    return subprocess.run([sys.executable, MIGRATION, *args], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          env=env, cwd=WORK_DIR)


def counts():
    c = sqlite3.connect(DB_PATH)
    try:
        return (c.execute("SELECT COUNT(*) FROM cars").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM clients").fetchone()[0])
    finally:
        c.close()


print('=== Предпросмотр ничего не меняет ===')
run_migration('--dry-run')
check('база после предпросмотра не тронута', counts() == (6, 5), str(counts()))

print('\n=== Применение миграции ===')
result = run_migration()
check('миграция отработала без ошибки', result.returncode == 0, result.stderr[-300:])
check('резервная копия создана',
      os.path.isdir(os.path.join(WORK_DIR, 'backups'))
      and len(os.listdir(os.path.join(WORK_DIR, 'backups'))) == 1)

conn = sqlite3.connect(DB_PATH)
plates = [r[0] for r in conn.execute("SELECT license_plate FROM cars ORDER BY license_plate")]
names = [r[0] for r in conn.execute("SELECT name FROM clients ORDER BY id")]
phones = [r[0] for r in conn.execute("SELECT phone FROM clients ORDER BY id")]

check('задвоенные машины склеены: 6 -> 3', len(plates) == 3, str(plates))
check('номера в едином виде', plates == ['А123ВВ777', 'К900ОР99', 'Н555НН50'], str(plates))
check('дубли клиентов убраны: 5 -> 2', len(names) == 2, str(names))
check('служебная запись «Хранение» удалена',
      not any(n and 'Хранение' in n for n in names), str(names))
check('телефоны в едином виде',
      all(p is None or p.startswith('7') for p in phones), str(phones))

check('ни один наряд не потерян',
      conn.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0] == orders_before)
check('нет нарядов с несуществующей машиной',
      conn.execute("SELECT COUNT(*) FROM work_orders wo "
                   "WHERE NOT EXISTS (SELECT 1 FROM cars c WHERE c.id = wo.car_id)"
                   ).fetchone()[0] == 0)
check('нет нарядов с несуществующим клиентом',
      conn.execute("SELECT COUNT(*) FROM work_orders wo WHERE wo.client_id IS NOT NULL "
                   "AND NOT EXISTS (SELECT 1 FROM clients c WHERE c.id = wo.client_id)"
                   ).fetchone()[0] == 0)
check('машины закреплены за клиентами',
      conn.execute("SELECT COUNT(*) FROM cars WHERE client_id IS NOT NULL").fetchone()[0] == 3)


def has_column(table, column):
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


check('добавлена колонка постов в смене', has_column('shifts', 'open_posts'))
check('добавлен признак «колёса в сборе»', has_column('cars', 'wheels_assembled'))
check('добавлена себестоимость расходников', has_column('services', 'consumable_cost'))
check('добавлено время выполнения услуги', has_column('services', 'duration_minutes'))
check('добавлен снимок себестоимости в позиции',
      has_column('work_order_items', 'consumable_cost'))
for col in ('planned_minutes', 'started_at', 'finished_at', 'paused_at',
            'paused_minutes', 'consumables_amount', 'salary_base'):
    check(f'добавлена колонка work_orders.{col}', has_column('work_orders', col))

check('старым нарядам проставлена база для ЗП',
      conn.execute("SELECT COUNT(*) FROM work_orders "
                   "WHERE status='paid' AND salary_base = total_amount").fetchone()[0] > 0)
check('«колёса в сборе» предзаполнены по хранению',
      conn.execute("SELECT wheels_assembled FROM cars "
                   "WHERE license_plate='А123ВВ777'").fetchone()[0] == 1)
check('номер в хранении шин нормализован',
      conn.execute("SELECT car_number FROM tire_storage WHERE id = 1").fetchone()[0] == 'А123ВВ777')
conn.close()

print('\n=== Даты переведены в местное время ===')
conn = sqlite3.connect(DB_PATH)
shift_start = conn.execute("SELECT start_time FROM shifts WHERE id = 1").fetchone()[0]
order_created = conn.execute("SELECT created_at FROM work_orders WHERE id = 1").fetchone()[0]
marker = conn.execute(
    "SELECT value FROM settings WHERE key = 'migration_utc_shift_done'").fetchone()
conn.close()
check('начало смены сдвинуто на 3 часа', shift_start.startswith('2026-07-01 13:00'),
      shift_start)
check('дата создания наряда сдвинута', order_created.startswith('2026-07-01 13:00'),
      order_created)
check('отметка о выполнении сохранена', marker is not None)

print('\n=== Повторный запуск безопасен ===')
result = run_migration()
check('база не изменилась', counts() == (3, 2), str(counts()))

conn = sqlite3.connect(DB_PATH)
shift_start_again = conn.execute("SELECT start_time FROM shifts WHERE id = 1").fetchone()[0]
conn.close()
check('даты НЕ сдвинулись повторно', shift_start_again == shift_start,
      f'{shift_start} -> {shift_start_again}')
check('сообщает, что менять нечего',
      'Изменений не потребовалось' in (result.stdout or ''), (result.stdout or '')[-200:])

print('\n=== Программа работает с мигрированной базой ===')
from config import SessionLocal
from services import ClientService

db = SessionLocal()
client_service = ClientService(db)
andrey = client_service.find_by_phone('+7 909 901-89-31')
check('клиент находится по телефону', andrey is not None)
if andrey:
    cars = {c.license_plate for c in client_service.get_client_cars(andrey.id)}
    check('обе машины закреплены за клиентом', cars == {'А123ВВ777', 'К900ОР99'}, str(cars))
    check('история клиента собрана',
          len(client_service.get_client_orders(andrey.id)) >= 5,
          f'нарядов: {len(client_service.get_client_orders(andrey.id))}')
check('машина находится по латинскому написанию',
      client_service.find_by_plate('a123bb777') is not None)
db.close()

finish()
