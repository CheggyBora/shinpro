"""
Обновление программы на рабочей базе.

В цеху стоит старая версия и работает с живой базой: там клиенты,
наряды, деньги, комплекты на хранении. Новая версия дорабатывает эту
же базу при первом запуске — добавляет колонки, размечает прайс,
заводит дополнения к покраске, проставляет сроки хранения.

Проверяем ровно то, чего стоит бояться: **не потеряется ли при этом
хоть что-нибудь**. Отдельной синхронизации между версиями нет и не
нужно — файл базы один и тот же, он просто дополняется.

Старую базу собираем честно: берём нынешнюю схему и отнимаем у неё
всё, что появилось позже, — колонки и таблицу. Получается ровно то,
что лежит на компьютере в цеху.
"""
import sqlite3
import sys

import _setup  # noqa: F401
from _setup import use_temp_db, check, finish

DB_PATH = use_temp_db('upgrade')

from config import init_db, SessionLocal, DATABASE_URL
from models import (Client, Car, Service, WorkOrder, TireStorage, PaintOption,
                    Settings)
from services import OrderService, ClientService, SalaryService
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.tire_storage_service import TireStorageService
from utils import get_moscow_time

# ----------------------------------------------------------------------
# Собираем базу, как она выглядит в цеху: с данными
# ----------------------------------------------------------------------
init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

ShiftService(db).open_shift()
from services import EmployeeService

employees = EmployeeService(db)
employees.register_employee(1)
employees.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.add(Service(name='Балансировка', vehicle_type='car', price_r16=500.0))
db.add(Service(name='Ремонт жгутом', vehicle_type='car', price_r16=800.0))
db.add(Service(name='Правка литого диска', vehicle_type='car', price_r16=2000.0))
db.commit()

orders = OrderService(db)
clients = ClientService(db)

PLATES = ['А123ВВ777', 'В456СС178', 'Е789КК750']
for index, plate in enumerate(PLATES):
    order = orders.create_order(plate, 'R16', 'car',
                                client_name=f'Клиент {index + 1}',
                                client_phone=f'7909901893{index}')
    for service in db.query(Service).limit(2).all():
        orders.add_service_to_order(order.id, service.id)
    SalaryService(db).process_payment(order.id, 'cash',
                                      orders.calculate_total(order.id))

db.add(TireStorage(car_number='А123ВВ777', storage_type='Шины с дисками',
                   diameter='R17', brand='Nokian', wheel_type='Литые',
                   price=5000.0, status='stored',
                   accepted_date=get_moscow_time()))
db.commit()

was = {
    'клиентов': db.query(Client).count(),
    'машин': db.query(Car).count(),
    'нарядов': db.query(WorkOrder).count(),
    'услуг': db.query(Service).count(),
    'комплектов': db.query(TireStorage).count(),
}
money_before = sum(o.total_amount or 0 for o in db.query(WorkOrder).all())
db.close()

print('=== Собрана база, как в цеху ===')
for name, count in was.items():
    print(f'  {name}: {count}')
check('данные на месте', all(was.values()), str(was))

# ----------------------------------------------------------------------
# Откатываем схему к прежней версии
# ----------------------------------------------------------------------
print()
print('=== Отнимаем всё, чего в старой версии не было ===')

raw = sqlite3.connect(DB_PATH)
raw.execute('ALTER TABLE services DROP COLUMN is_extra')
raw.execute('ALTER TABLE tire_storage DROP COLUMN expires_at')
raw.execute('DROP TABLE paint_options')
raw.execute("DELETE FROM settings WHERE key IN "
            "('services_classified', 'storage_deadlines_filled', "
            "'storage_months', 'storage_warn_days', 'storage_lead_days', "
            "'season_autumn_at', 'season_spring_at', "
            "'season_reminders_enabled')")
raw.commit()

columns = [row[1] for row in raw.execute('PRAGMA table_info(services)')]
check('колонки вида услуги больше нет', 'is_extra' not in columns)
tables = [row[0] for row in
          raw.execute("SELECT name FROM sqlite_master WHERE type='table'")]
check('таблицы покраски больше нет', 'paint_options' not in tables)
raw.close()

# ----------------------------------------------------------------------
# Запускаем новую версию: ровно то, что делает программа при старте
# ----------------------------------------------------------------------
print()
print('=== Запускаем новую версию ===')
init_db()

db = SessionLocal()
now = {
    'клиентов': db.query(Client).count(),
    'машин': db.query(Car).count(),
    'нарядов': db.query(WorkOrder).count(),
    'услуг': db.query(Service).count(),
    'комплектов': db.query(TireStorage).count(),
}

print()
print('=== Ничего не потерялось ===')
for name in was:
    check(f'{name}: было {was[name]}, стало {now[name]}',
          was[name] == now[name])

money_after = sum(o.total_amount or 0 for o in db.query(WorkOrder).all())
check('суммы нарядов не изменились', money_before == money_after,
      f'{money_before} против {money_after}')

print()
print('=== Новое появилось ===')
settings = SettingsService(db)

extra = db.query(Service).filter(Service.is_extra.is_(True)).all()
main = db.query(Service).filter(Service.is_extra.is_(False)).all()
check('прайс разметился', bool(extra) and bool(main),
      f'основных {len(main)}, допов {len(extra)}')
check('шиномонтаж и баланс — основные',
      {row.name for row in main} == {'Шиномонтаж', 'Балансировка'},
      str(sorted(row.name for row in main)))
check('ремонт и правка — допродажи',
      {row.name for row in extra} == {'Ремонт жгутом', 'Правка литого диска'},
      str(sorted(row.name for row in extra)))

check('дополнения к покраске завелись',
      db.query(PaintOption).count() >= 6,
      str(db.query(PaintOption).count()))
check('срок хранения задан', settings.get_int('storage_months') == 6,
      str(settings.get_int('storage_months')))
check('срок выдачи со склада задан',
      settings.get_int('storage_lead_days') == 2,
      str(settings.get_int('storage_lead_days')))

stored = db.query(TireStorage).first()
check('комплекту проставлен срок', stored.expires_at is not None,
      str(stored.expires_at))

print()
print('=== Второй запуск ничего не ломает ===')
db.close()
init_db()
db = SessionLocal()

again = {
    'клиентов': db.query(Client).count(),
    'нарядов': db.query(WorkOrder).count(),
    'услуг': db.query(Service).count(),
}
check('данные те же', all(again[k] == was[k] for k in again), str(again))
check('дополнения к покраске не задвоились',
      db.query(PaintOption).count() < 12,
      str(db.query(PaintOption).count()))

db.close()
finish()
