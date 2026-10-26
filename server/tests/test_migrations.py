"""
Миграции держат базу в соответствии с моделями.

Раньше таблицы создавались на месте, при запуске: на пустой базе это
работает, а на боевой новая колонка просто не появляется — и запросы
начинают падать после первого же обновления. Теперь каждая правка
схемы записана шагом, и база проходит их по порядку.

Здесь проверяется главное свойство: пройдя все шаги, база выглядит
ровно так, как описано в моделях. Если кто-то поправил модель и забыл
про миграцию, этот тест скажет об этом здесь, а не на сервере в цеху.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_migrations_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-migrations'

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app.database import Base, engine, init_db
import app.models  # noqa: F401 — регистрирует таблицы

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


def alembic_config():
    config = Config(os.path.join(SERVER_DIR, 'alembic.ini'))
    config.set_main_option('script_location',
                           os.path.join(SERVER_DIR, 'migrations'))
    config.set_main_option('sqlalchemy.url', os.environ['SERVER_DATABASE_URL'])
    config.attributes['configure_logger'] = False
    return config


print('=== Пустая база проходит все шаги ===')
init_db()

inspector = inspect(engine)
tables = set(inspector.get_table_names())

check('таблицы созданы', len(tables) > 10, str(len(tables)))
check('есть точки и аккаунты', {'shops', 'accounts'} <= tables)
check('есть наряды и начисления', {'visits', 'salary_accruals'} <= tables)
check('есть персонал дашборда', 'staff_users' in tables)
check('alembic отметил версию базы', 'alembic_version' in tables)
# Онлайн-очередь «из дома» убрана шагом 3c6b1e9a7d42: таблица её
# талонов на свежей базе появиться не должна
check('талонов старой онлайн-очереди нет', 'queue_tickets' not in tables)
# Календарь задач и контрагенты — шаг 7b4e2c9d1f05
check('есть календарь задач и контрагенты',
      {'tasks', 'counterparties'} <= tables)
# Мойка — свой слой календаря, шаг c4d8a2f6e1b3
for table in ('tasks', 'counterparties'):
    columns = {column['name']: column for column in inspector.get_columns(table)}
    direction = columns.get('direction')
    check(f'у {table} есть направление', direction is not None
          and not direction['nullable']
          and 'tire' in str(direction.get('default')),
          str(direction))
# Запись на мойку — шаг e7a3b5c9d2f4: направление и класс машины
columns = {column['name']: column
           for column in inspector.get_columns('appointments')}
direction = columns.get('direction')
check('у записи есть направление', direction is not None
      and not direction['nullable']
      and 'tire' in str(direction.get('default')), str(direction))
check('у записи есть класс машины для мойки',
      'wash_class' in columns and columns['wash_class']['nullable'])
# Склад — шаг a6f2c8e4b1d7: снимок остатков из цеха
check('есть склад', 'stock_items' in tables)
columns = {column['name']: column
           for column in inspector.get_columns('stock_items')}
check('у позиции склада все поля',
      {'shop_id', 'uid', 'name', 'direction', 'kind', 'unit', 'quantity',
       'min_quantity', 'price', 'purchase_price', 'updated_at'} <= set(columns),
      str(sorted(columns)))
check('закупка у позиции необязательна',
      columns.get('purchase_price', {}).get('nullable') is True)
uniques = [set(item['column_names'])
           for item in inspector.get_unique_constraints('stock_items')]
check('uid позиции уникален внутри точки', {'shop_id', 'uid'} in uniques,
      str(uniques))
# Мойка на дашборде — шаг b3e9d1f7a2c5: направление у наряда, позиции
# и начисления, у позиции — мойщик, у наряда — класс машины
for table, name in (('visits', 'directions'), ('visit_items', 'direction'),
                    ('salary_accruals', 'direction')):
    columns = {column['name']: column for column in inspector.get_columns(table)}
    direction = columns.get(name)
    check(f'у {table} есть {name}', direction is not None
          and not direction['nullable']
          and 'tire' in str(direction.get('default')), str(direction))
columns = {column['name']: column for column in inspector.get_columns('visits')}
check('у наряда есть класс машины для мойки',
      'wash_class' in columns and columns['wash_class']['nullable'])
columns = {column['name']: column
           for column in inspector.get_columns('visit_items')}
check('у позиции есть мойщик',
      'employee_local_id' in columns
      and columns['employee_local_id']['nullable'])

print('\n=== Схема совпадает с моделями ===')
# Тот же расчёт, что делает autogenerate: если он находит отличия,
# значит модель поменяли, а шаг миграции написать забыли
with engine.connect() as connection:
    context = MigrationContext.configure(
        connection, opts={'compare_type': True})
    differences = compare_metadata(context, Base.metadata)

# Индексы, которые SQLite показывает по-своему, в расчёт не берём:
# нас интересуют таблицы и колонки
meaningful = [item for item in differences
              if not (isinstance(item, tuple) and item
                      and 'index' in str(item[0]))]

check('расхождений между базой и моделями нет', not meaningful,
      '; '.join(str(item)[:120] for item in meaningful[:3]))

print('\n=== Шаги ходят в обе стороны ===')
config = alembic_config()

command.downgrade(config, 'base')
inspector = inspect(engine)
after_downgrade = set(inspector.get_table_names()) - {'alembic_version'}
check('откат убирает таблицы', not after_downgrade, str(after_downgrade))

command.upgrade(config, 'head')
inspector = inspect(engine)
check('повторный проход возвращает схему',
      {'shops', 'visits', 'staff_users'} <= set(inspector.get_table_names()))

print('\n=== Старые наряды после шага мойки — шиномонтаж ===')
from sqlalchemy import text

command.downgrade(config, 'a6f2c8e4b1d7')
with engine.begin() as connection:
    connection.execute(text(
        "INSERT INTO visits (id, visited_at, total_amount, is_warranty, "
        "consumables_amount, salary_base, general_discount, rim_discount, "
        "auto_discount, refunded_amount, is_deleted, planned_minutes) "
        "VALUES (1, '2026-10-01 12:00:00', 1000, 0, 0, 0, 0, 0, 0, 0, 0, 0)"))
    connection.execute(text(
        "INSERT INTO visit_items (id, visit_id, service_name, quantity, "
        "unit_price, discount_percent, total, consumable_cost, is_goods, "
        "is_extra) VALUES (1, 1, 'Шиномонтаж', 4, 250, 0, 1000, 0, 0, 0)"))
    connection.execute(text(
        "INSERT INTO salary_accruals (id, visit_id, employee_local_id, amount) "
        "VALUES (1, 1, 1, 400)"))
command.upgrade(config, 'head')
with engine.connect() as connection:
    old = (connection.execute(text('SELECT directions FROM visits')).scalar(),
           connection.execute(text('SELECT direction FROM visit_items')).scalar(),
           connection.execute(text(
               'SELECT direction FROM salary_accruals')).scalar())
check('наряд, позиция и начисление до шага стали шиномонтажом',
      old == ('tire', 'tire', 'tire'), str(old))
with engine.begin() as connection:
    for table in ('salary_accruals', 'visit_items', 'visits'):
        connection.execute(text(f'DELETE FROM {table}'))

print('\n=== Повторный запуск ничего не ломает ===')
init_db()
init_db()
inspector = inspect(engine)
check('таблицы на месте после трёх запусков',
      {'shops', 'visits'} <= set(inspector.get_table_names()))

finish()
