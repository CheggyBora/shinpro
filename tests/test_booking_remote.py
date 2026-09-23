"""
Записи через сервер: второй режим работы программы.

Сервер не настроен — записи лежат в своей базе, интернет не нужен.
Сервер настроен — записи переезжают на него целиком, и оба, приёмщик
и клиент из приложения, работают с одной и той же записью.

Здесь проверяется именно второй режим, включая то, ради чего он затеян:
без интернета записать нельзя, но видеть записанных — можно.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('booking_remote')

import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta

SYNC_KEY = 'test-remote-key'

_server_db = os.path.join(tempfile.gettempdir(), 'tire_remote_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret'
os.environ['SERVER_SYNC_KEY'] = SYNC_KEY
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

sys.path.insert(0, os.path.join(_setup.PROJECT_DIR, 'server'))

from config import init_db, SessionLocal
from models import Appointment
from services.settings_service import SettingsService
from services.sync_service import SyncService
from services.booking_gateway import get_booking, LocalBooking, RemoteBooking
from services.booking_api import Offline


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


PORT = free_port()
BASE_URL = f'http://127.0.0.1:{PORT}'


def start_server():
    import uvicorn
    from app.main import app as server_app

    config = uvicorn.Config(server_app, host='127.0.0.1', port=PORT,
                            log_level='error')
    thread = threading.Thread(target=uvicorn.Server(config).run, daemon=True)
    thread.start()

    for _ in range(100):
        try:
            with urllib.request.urlopen(f'{BASE_URL}/health', timeout=1):
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('Сервер не поднялся')


start_server()

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

TOMORROW = (datetime.now() + timedelta(days=1)).date()


def at(hour, minute=0):
    return datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, hour, minute)


print('=== Сервер не настроен — работаем со своей базой ===')
booking = get_booking(db)
check('выбран местный режим', isinstance(booking, LocalBooking))
check('и он не удалённый', booking.is_remote is False)

local_id = booking.create(scheduled_at=at(9), duration_minutes=60,
                          license_plate='М777ММ199', client_name='Местный')
check('запись создана без интернета', local_id is not None)
check('она лежит в своей базе',
      db.query(Appointment).filter(Appointment.id == local_id).first() is not None)

state = booking.load_day(TOMORROW)
check('день собран', len(state['placed']) == 1, str(len(state['placed'])))
check('своя база всегда «на связи»', state['online'] is True)

print('\n=== Включаем сервер ===')
SyncService(db).save_settings(BASE_URL, SYNC_KEY, enabled=True)
booking = get_booking(db)
check('режим переключился на сервер', isinstance(booking, RemoteBooking))
check('и он удалённый', booking.is_remote is True)

print('\n=== Посты задаются на сервере ===')
booking.set_posts_for_days(TOMORROW, 1, 2)
check('на завтра два поста', booking.get_posts_for_day(TOMORROW) == 2,
      str(booking.get_posts_for_day(TOMORROW)))

posts_map = booking.get_posts_map(TOMORROW, 3)
check('карта постов получена', posts_map[TOMORROW] == 2, str(posts_map))

print('\n=== Запись уходит на сервер ===')
server_id = booking.create(scheduled_at=at(10), duration_minutes=40,
                           license_plate='а123вв777', client_name='Андрей',
                           client_phone='8 909 901-89-31',
                           wheels_assembled=True)
check('сервер вернул номер записи', server_id is not None, str(server_id))

state = booking.load_day(TOMORROW)
check('связь есть', state['online'] is True)
check('запись видна', len(state['placed']) == 1, str(len(state['placed'])))

row, column = state['placed'][0]
check('номер нормализован', row.license_plate == 'А123ВВ777', row.license_plate)
check('имя на месте', row.client_name == 'Андрей', str(row.client_name))
check('телефон нормализован', row.client_phone == '79099018931',
      str(row.client_phone))
check('колонка посчитана сервером', column == 0, str(column))
check('ключ — номер на сервере', booking.key_of(row) == server_id,
      f'{booking.key_of(row)} против {server_id}')

print('\n=== Местная запись на сервер не переехала ===')
check('на сервере только своя запись', len(state['placed']) == 1)

print('\n=== Пересечение уходит во второй пост ===')
booking.create(scheduled_at=at(10, 20), duration_minutes=40,
               license_plate='К900ОР99')
state = booking.load_day(TOMORROW)
columns = sorted(column for _, column in state['placed'])
check('колонки разные', columns == [0, 1], str(columns))

print('\n=== Сверх постов запись всё равно принимается ===')
booking.create(scheduled_at=at(10, 30), duration_minutes=40,
               license_plate='Т111ТТ77')
state = booking.load_day(TOMORROW)
columns = sorted(column for _, column in state['placed'])
check('третья вынесена за сетку', columns == [0, 1, 2], str(columns))
check('но она не потеряна', len(state['placed']) == 3)

print('\n=== Отметки и отмена идут на сервер ===')
booking.mark_arrived(server_id)
state = booking.load_day(TOMORROW)
arrived = [row for row, _ in state['placed'] if row.server_id == server_id][0]
check('отмечено «приехал»', arrived.status == 'arrived', arrived.status)

booking.cancel(server_id)
state = booking.load_day(TOMORROW)
cancelled = [row for row, _ in state['placed'] if row.server_id == server_id][0]
check('запись отменена', cancelled.status == 'cancelled', cancelled.status)

print('\n=== Клиент из приложения записался — приёмщик видит сразу ===')
from app.database import SessionLocal as ServerSession
from app.models import Appointment as SrvAppointment

srv = ServerSession()

# Запись принадлежит точке — той, что завелась при запуске сервера
from app.models import Shop as SrvShop
srv_shop = srv.query(SrvShop).first()

srv.add(SrvAppointment(shop_id=srv_shop.id,
                       scheduled_at=at(15), duration_minutes=40,
                       license_plate='Х555ХХ99', client_name='Из приложения',
                       client_phone='79995554433', status='scheduled',
                       source='app'))
srv.commit()
srv.close()

state = booking.load_day(TOMORROW)
from_app = [row for row, _ in state['placed']
            if row.license_plate == 'Х555ХХ99']
check('запись клиента видна без всякого обмена', len(from_app) == 1,
      str(len(from_app)))
check('видно, что она из приложения', from_app[0].source == 'app',
      from_app[0].source)

# --------------------------------------------------------------------
print('\n=== Связь пропала ===')
SyncService(db).save_settings('http://127.0.0.1:1', SYNC_KEY, enabled=True)
booking = get_booking(db)

offline = booking.load_day(TOMORROW)
check('честно сказано, что связи нет', offline['online'] is False, str(offline))
check('но записанные видны из кэша', len(offline['placed']) == 4,
      str(len(offline['placed'])))
check('видно, когда данные получены', offline['fetched_at'] is not None)
check('причина названа', bool(offline['reason']), str(offline['reason']))

print('\n=== Записать без связи нельзя ===')
blocked = False
try:
    booking.create(scheduled_at=at(18), duration_minutes=60,
                   license_plate='Н999НН99')
except Offline:
    blocked = True
check('запись не создалась', blocked)

blocked = False
try:
    booking.cancel(server_id)
except Offline:
    blocked = True
check('отменить тоже нельзя', blocked)

print('\n=== Посты офлайн берутся из кэша ===')
check('на завтра по-прежнему два', booking.get_posts_for_day(TOMORROW) == 2,
      str(booking.get_posts_for_day(TOMORROW)))

print('\n=== Связь вернулась ===')
SyncService(db).save_settings(BASE_URL, SYNC_KEY, enabled=True)
booking = get_booking(db)
back = booking.load_day(TOMORROW)
check('снова на связи', back['online'] is True)
check('записи на месте', len(back['placed']) == 4, str(len(back['placed'])))

new_id = booking.create(scheduled_at=at(18), duration_minutes=60,
                        license_plate='Н999НН99')
check('записывать снова можно', new_id is not None)

print('\n=== Выключили сервер — вернулись к своей базе ===')
SyncService(db).save_settings('', '', enabled=False)
booking = get_booking(db)
check('снова местный режим', isinstance(booking, LocalBooking))
check('старая местная запись на месте',
      db.query(Appointment).filter(Appointment.id == local_id).first() is not None)

db.close()
finish()
