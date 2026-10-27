"""
Запись без постов: «N машин в час» (решение владельца 28.10.2026).

Базовый режим шиномонтажа — постов нет, машина просто приезжает, мастера
принимают и работают в общий котёл. Онлайн-запись ставится на N машин в
час (1–3), физически к постам не привязана: считаем записи этого часа, а
не наложения по длительности.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_hourly_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-hourly-0123456789abcdef'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-hourly'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Appointment, Shop
from app.services import shop_settings
from app.services.booking_service import BookingService
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

with TestClient(app) as http:
    http.post('/sync/push', headers=KEY, json={'settings': {
        'booking_posts': '1', 'booking_slot_step': '30', 'booking_opens_at': '09:00',
        'booking_closes_at': '21:00', 'booking_minutes_assembled': '30',
        'booking_minutes_tires': '60', 'booking_minutes_unknown': '60'}})

    db = SessionLocal()
    shop = db.query(Shop).first()
    day = (shop_now() + timedelta(days=2)).date()
    ten = datetime.combine(day, datetime.min.time()).replace(hour=10)
    db.add(Appointment(shop_id=shop.id, scheduled_at=ten, duration_minutes=30,
                       license_plate='А111АА77', status='scheduled'))
    db.commit()

    def free_at(service, duration=30):
        return {slot['at'].strftime('%H:%M') for slot in service.free_slots(day, duration)}

    print('=== По постам (как было): наложения по длительности ===')
    service = BookingService(db, shop)
    check('режим постов — пока цех не сказал «без постов»', not service.hourly())
    slots = free_at(service)
    check('1 пост, запись 10:00 на 30 минут: 10:00 занято, 10:30 свободно',
          '10:00' not in slots and '10:30' in slots, str(sorted(slots))[:200])

    print('\n=== Без постов: N машин в час ===')
    http.post('/sync/push', headers=KEY, json={'settings': {'booking_mode': 'hourly'}})
    db.expire_all()
    service = BookingService(db, shop)
    check('цех сказал «без постов» — считаем по часам', service.hourly())
    slots = free_at(service)
    check('1 машина в час: весь час 10 занят — и 10:00, и 10:30',
          '10:00' not in slots and '10:30' not in slots, str(sorted(slots))[:200])
    check('11:00 свободно', '11:00' in slots)
    check('запись в 10:30 не пройдёт', not service._slot_is_free(ten + timedelta(minutes=30), 30, 1))
    check('а в 11:00 — пройдёт, хотя длинная запись 10:00 и задела бы',
          service._slot_is_free(ten + timedelta(hours=1), 60, 1))

    shop_settings.set_value(db, 'booking_posts', '2', shop=shop)
    db.commit()
    service = BookingService(db, BookingService(db, shop).shop)
    check('2 машины в час: в 10:30 ещё место есть', '10:30' in free_at(service))

    wash = BookingService(db, shop, direction='wash')
    check('мойку режим не трогает — у неё свои посты', not wash.hourly())

    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
