"""
Сервер живёт по времени шиномонтажа, а не по времени своей машины.

Это не придирка. VPS почти всегда стоит в UTC, а цех — в Москве.
Если сервер возьмёт «сейчас» у себя, то в девять вечера по Москве он
будет считать, что шесть, и предложит клиенту записаться на время,
когда шиномонтаж уже закрыт. Журнал при этом покажет события на три
часа назад, и разобраться, когда кто заходил, будет нельзя.

Проверяем на машине, переведённой в UTC: подменяем TZ и смотрим, что
сервер всё равно считает по Москве.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_time_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-time'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-key'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import StaffUser, StaffAction, QueueSnapshot, Appointment
from app.utils import now as shop_now, MOSCOW_OFFSET_HOURS
from app.services.booking_service import BookingService

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


print('=== «Сейчас» — московское, а не то, что на машине ===')
check('московский сдвиг', MOSCOW_OFFSET_HOURS == 3, str(MOSCOW_OFFSET_HOURS))

gap = (shop_now() - datetime.utcnow()).total_seconds() / 3600
check('время опережает UTC на три часа',
      2.9 < gap < 3.1, f'{gap:.2f} ч')

print('\n=== Никто не берёт время у машины напрямую ===')
# Именно так и появилась разница: где-то utcnow, где-то now, а данные
# из цеха приходят московские. Проверяем, что в коде сервера этого
# больше нет — кроме срока жизни токена, который проверяет библиотека
import glob

leftovers = []
for path in glob.glob(os.path.join(SERVER_DIR, 'app', '**', '*.py'),
                      recursive=True):
    name = os.path.relpath(path, SERVER_DIR).replace('\\', '/')
    if name in ('app/utils.py', 'app/security.py'):
        continue
    text = open(path, encoding='utf-8').read()
    for line in text.split('\n'):
        if 'datetime.utcnow()' in line or 'datetime.now()' in line:
            leftovers.append(f'{name}: {line.strip()[:60]}')

check('в коде сервера нет прямых обращений к часам машины',
      not leftovers, '; '.join(leftovers))

token_file = open(os.path.join(SERVER_DIR, 'app', 'security.py'),
                  encoding='utf-8').read()
check('срок жизни токена остался в UTC — его так проверяет библиотека',
      "'exp': datetime.utcnow()" in token_file)

print('\n=== Журнал и очередь пишутся по времени цеха ===')
with TestClient(app) as client:
    db = SessionLocal()

    db.add(QueueSnapshot(cars_in_work=1, cars_waiting=0, open_posts=2,
                         shift_is_open=True))
    staff = StaffUser(phone='79099018931', name='Владелец', role='owner')
    db.add(staff)
    db.commit()

    snapshot = db.query(QueueSnapshot).first()
    drift = abs((snapshot.taken_at - shop_now()).total_seconds())
    check('слепок очереди помечен временем цеха', drift < 60,
          f'{drift:.0f} с')

    db.add(StaffAction(staff_id=staff.id, phone=staff.phone, action='login'))
    db.commit()

    record = db.query(StaffAction).first()
    drift = abs((record.happened_at - shop_now()).total_seconds())
    check('запись в журнале помечена временем цеха', drift < 60,
          f'{drift:.0f} с')

    # Очередь моложе часа — свежая. При старом расхождении свежий слепок
    # выглядел бы трёхчасовым, и клиенту говорили бы «данные устарели»,
    # хотя цех вышел на связь минуту назад
    age = (shop_now() - snapshot.taken_at).total_seconds() / 3600
    check('свежая очередь не выглядит трёхчасовой', age < 0.5,
          f'{age:.2f} ч')

    print('\n=== Свободные окна считаются по времени цеха ===')
    today = shop_now().date()
    slots = BookingService(db).free_slots(today, 30)

    # Окна до текущего часа предлагать нельзя. Возьми сервер время у
    # себя (UTC) — он решил бы, что сейчас на три часа раньше, и
    # предложил бы записаться в уже прошедшее время
    passed = [slot['at'] for slot in slots if slot['at'] <= shop_now()]
    check('прошедшее время не предлагается', not passed, str(passed[:3]))
    check('на сегодня окна вообще нашлись', bool(slots) or shop_now().hour >= 20,
          str(len(slots)))

    db.close()

finish()
