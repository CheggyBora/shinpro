"""
Вызов комплекта со склада и «колёса приехали» (решение владельца 13.11.2026).

  · за сколько суток — настройка; отсчёт со следующего дня: 13-го при
    двух сутках — с 16-го, при сутках — с 15-го;
  · цех нажал «Приехало» — клиенту «колёса приехали, ждём вас <дата
    записи>»; один раз; старая программа без поля — ничего не меняет.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_storage_arrival_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-storage-arrival-01'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-arrival'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Appointment, Client, Notice, Shop, StoredSet, KIND_ARRIVED
from app.services import shop_settings
from app.services.booking_service import BookingService
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def arrived():
    db = SessionLocal()
    try:
        return db.query(Notice).filter(Notice.kind == KIND_ARRIVED).all()
    finally:
        db.close()


with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    print('=== С какого дня запись с комплектом ===')
    the_13th = datetime(2026, 11, 13, 10, 0)
    shop_settings.set_value(db, 'storage_lead_days', '2', shop=shop)
    check('13-е, за двое суток — с 16-го',
          BookingService(db, shop).storage_ready_from(the_13th) == the_13th.date() + timedelta(days=3))
    shop_settings.set_value(db, 'storage_lead_days', '1', shop=shop)
    check('13-е, за сутки — с 15-го',
          BookingService(db, shop).storage_ready_from(the_13th) == the_13th.date() + timedelta(days=2))
    shop_settings.set_value(db, 'storage_lead_days', '0', shop=shop)
    check('0 — без ограничения', BookingService(db, shop).storage_ready_from(the_13th) is None)
    db.close()

    print('\n=== Колёса приехали ===')
    accepted = (shop_now() - timedelta(days=90)).isoformat()
    http.post('/sync/push', headers=KEY, json={
        'clients': [{'local_id': 1, 'name': 'Пётр', 'phone': '+79005554433'}],
        'cars': [{'local_id': 1, 'license_plate': 'А123ВВ777', 'client_local_id': 1}],
        'storage': [{'local_id': 7, 'client_local_id': 1, 'license_plate': 'А123ВВ777',
                     'storage_type': 'Шины на дисках', 'diameter': 'R17', 'brand': 'Nokian',
                     'accepted_at': accepted, 'status': 'stored'}]})
    db = SessionLocal()
    client = db.query(Client).first()
    stored = db.query(StoredSet).first()
    when = (shop_now() + timedelta(days=3)).replace(hour=10, minute=30, second=0, microsecond=0)
    db.add(Appointment(shop_id=stored.shop_id, client_id=client.id, scheduled_at=when,
                       duration_minutes=60, license_plate='А123ВВ777', status='scheduled', source='app'))
    db.commit()
    db.close()

    item = {'local_id': 7, 'client_local_id': 1, 'license_plate': 'А123ВВ777',
            'storage_type': 'Шины на дисках', 'diameter': 'R17', 'brand': 'Nokian',
            'accepted_at': accepted, 'status': 'stored'}
    http.post('/sync/push', headers=KEY, json={'storage': [item]})
    check('пока не приехало — сообщений нет', not arrived())
    http.post('/sync/push', headers=KEY, json={'storage': [{**item, 'arrived_at': shop_now().isoformat()}]})
    rows = arrived()
    check('«Приехало» — клиенту «колёса приехали» с датой записи',
          len(rows) == 1 and 'Колёса приехали' in rows[0].text
          and f'{when:%d.%m} в 10:30' in rows[0].text, str([r.text for r in rows]))
    http.post('/sync/push', headers=KEY, json={'storage': [{**item, 'arrived_at': shop_now().isoformat()}]})
    check('повторный обмен — не дубль', len(arrived()) == 1)
    http.post('/sync/push', headers=KEY, json={'storage': [item]})
    db = SessionLocal()
    check('старая программа без поля — отметку не стирает',
          db.query(StoredSet).first().arrived_at is not None)
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
