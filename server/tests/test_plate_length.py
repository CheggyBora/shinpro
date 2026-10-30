"""
Номер машины на сервере не короче, чем в программе цеха.

В цеху номер — до 50 знаков, на сервере было 20. PostgreSQL длинный
номер не принимал, и обмен точки падал с ошибкой 500 целиком — с ним не
доезжал и ключ звонков (30.10.2026). SQLite длину не проверяет, поэтому
обычные тесты этого не видели: сверяем сами колонки.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_plate_length_test.db')
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-plate-length-0123456789ab'

from app.database import Base
import app.models  # noqa: F401 — все таблицы в Base

SHOP_PLATE_LENGTH = 50
_failures = []

for table in Base.metadata.sorted_tables:
    for column in table.columns:
        if column.name not in ('license_plate', 'plate'):
            continue
        length = getattr(column.type, 'length', None)
        ok = length is None or length >= SHOP_PLATE_LENGTH
        print(f"[{'PASS' if ok else 'FAIL'}] {table.name}.{column.name}: {length}")
        if not ok:
            _failures.append(table.name)

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
