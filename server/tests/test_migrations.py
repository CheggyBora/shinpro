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

print('\n=== Повторный запуск ничего не ломает ===')
init_db()
init_db()
inspector = inspect(engine)
check('таблицы на месте после трёх запусков',
      {'shops', 'visits'} <= set(inspector.get_table_names()))

finish()
