"""
Одно время — одна машина. Кто бы ни записывал.

Записи живут здесь, на сервере, в одном экземпляре: и цех, и кабинет
читают и пишут сюда же. Значит, занять одно окно дважды нельзя — но
только если проверка стоит на всех путях, а не на одном.

Клиенту из интернета отказываем молча и твёрдо: он бокса не видит и
решать за цех не может. Приёмщику — отказываем с вопросом: он видит,
что происходит в боксе, и может записать сверх постов осознанно. Чего
не должно быть — так это молчаливой записи сверх постов: клиент
приедет на своё время и найдёт там чужую машину.

Проверяем оба пути: и создание, и перенос.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_overbook_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-overbook'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-overbook'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from datetime import datetime, timedelta, date

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.utils import now as shop_now
from app.models import BookingDay, Appointment, Shop
from app.api import public

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


TOMORROW = date.today() + timedelta(days=1)


def at(hour, minute=0):
    return datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, hour, minute)


def relax():
    """Сбросить счётчик частых обращений: он общий на весь прогон."""
    public._recent.clear()


with TestClient(app) as client:
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop.last_sync_at = shop_now()
    db.add(BookingDay(shop_id=shop.id, day=TOMORROW, posts=1,
                      opens_at='09:00', closes_at='18:00'))
    db.commit()
    shop_id = shop.id
    db.close()

    KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

    print('=== Приёмщик записал на 10:00, пост один ===')
    made = client.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': at(10).isoformat(),
        'duration_minutes': 40,
        'license_plate': 'А123ВВ777'})
    check('записали', made.status_code == 200, str(made.json()))
    first = made.json()
    check('время было свободно', first['was_free'] is True, str(first))

    print()
    print('=== Клиенту из интернета это время больше не отдают ===')
    days = client.get('/public/days').json()
    tomorrow = [d for d in days if d['day'] == TOMORROW.isoformat()][0]
    taken = [slot for slot in tomorrow['slots']
             if slot['at'].endswith('10:00:00')]
    check('окна 10:00 в списке нет', taken == [], str(taken))

    relax()
    rejected = client.post('/public/book', json={
        'at': at(10).isoformat(),
        'license_plate': 'К900ОР99',
        'client_phone': '79161234567'})
    check('и напрямую не записаться', rejected.status_code == 409,
          str(rejected.json()))

    print()
    print('=== Приёмщику отказывают, пока он не настоял ===')
    second = client.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': at(10, 15).isoformat(),
        'duration_minutes': 40,
        'license_plate': 'Т111ТТ77'})
    check('отказ, а не молчаливая запись', second.status_code == 409,
          str(second.json()))
    check('сказано, в чём дело',
          'заняты' in second.json()['detail'], second.json()['detail'])

    db = SessionLocal()
    check('лишней записи не завелось',
          db.query(Appointment).count() == 1,
          str(db.query(Appointment).count()))
    db.close()

    print()
    print('=== Настоял — записали, но сказали, что было занято ===')
    forced = client.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': at(10, 15).isoformat(),
        'duration_minutes': 40,
        'license_plate': 'Т111ТТ77',
        'force': True})
    check('записали', forced.status_code == 200, str(forced.json()))
    check('и честно сказали, что было занято',
          forced.json()['was_free'] is False, str(forced.json()))

    print()
    print('=== Перенос на занятое время — так же ===')
    third = client.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': at(14).isoformat(),
        'duration_minutes': 40,
        'license_plate': 'Х555ХХ99'}).json()

    moved = client.patch(f"/sync/appointments/{third['id']}", headers=KEY,
                         json={'scheduled_at': at(10).isoformat()})
    check('перенос на занятое отклонён', moved.status_code == 409,
          str(moved.json()))

    db = SessionLocal()
    row = db.query(Appointment).filter(Appointment.id == third['id']).first()
    check('запись осталась на своём времени', row.scheduled_at == at(14),
          str(row.scheduled_at))
    db.close()

    forced_move = client.patch(f"/sync/appointments/{third['id']}", headers=KEY,
                               json={'scheduled_at': at(10).isoformat(),
                                     'force': True})
    check('с ведома приёмщика — переносим',
          forced_move.status_code == 200, str(forced_move.json()))

    print()
    print('=== Сдвиг не упирается в самого себя ===')
    # Один пост, на 16:00 запись одна. Двигаем её на четверть часа:
    # если считать её же занятостью, перенос стал бы невозможен
    db = SessionLocal()
    alone = Appointment(shop_id=shop_id, scheduled_at=at(16),
                        duration_minutes=40, license_plate='О777ОО77',
                        status='scheduled')
    db.add(alone)
    db.commit()
    alone_id = alone.id
    db.close()

    nudged = client.patch(f"/sync/appointments/{alone_id}", headers=KEY,
                          json={'scheduled_at': at(16, 15).isoformat()})
    check('своя же запись не мешает', nudged.status_code == 200,
          str(nudged.json()))

    print()
    print('=== Отмена и приезд проверкой не ломаются ===')
    arrived = client.patch(f"/sync/appointments/{alone_id}", headers=KEY,
                           json={'status': 'arrived'})
    check('«приехал» проходит', arrived.status_code == 200, str(arrived.json()))

    cancelled = client.patch(f"/sync/appointments/{alone_id}", headers=KEY,
                             json={'status': 'cancelled'})
    check('отмена проходит', cancelled.status_code == 200,
          str(cancelled.json()))

    print()
    print('=== Отменённая запись пост освобождает ===')
    relax()
    freed = client.post('/public/book', json={
        'at': at(16, 15).isoformat(),
        'license_plate': 'Н888НН77',
        'client_phone': '79160000001'})
    check('на освободившееся время клиент записался',
          freed.status_code == 200, str(freed.json()))

finish()
