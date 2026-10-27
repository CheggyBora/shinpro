"""
Режим «Без постов — только запись» — базовый (решение владельца 28.10.2026).

Онлайн-запись ставится на N машин в час (1–3), к постам не привязана.
Машина приезжает — мастера принимают, работают в общий котёл. Наряд из
записи — сразу с клиентом, диаметром и комплектом, но без поста.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('no_posts_mode')

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from services import EmployeeService
from services.appointment_service import AppointmentService, hourly_booking
from services.live_queue_service import LiveQueueService
from services.settings_service import SettingsService
from services.shift_service import ShiftService
from services.sync_service import SyncService
from services import directions

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

queue = LiveQueueService(db)
print('=== По умолчанию — без постов, общий котёл ===')
check('режим по умолчанию — «Без постов»', queue.mode() == 'off' and queue.no_posts())
check('очередь не работает', not queue.enabled())
check('запись — по часам', hourly_booking(db))
check('мастера на наряд не выбираются — общий котёл', not directions.tire_assign(db))

print('\n=== Запись: N машин в час ===')
appointments = AppointmentService(db)
day = (datetime.now() + timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
appointments.create(day, duration_minutes=30, client_name='Иван', client_phone='79160000001',
                    license_plate='А111АА77')
free, busy, total = appointments.check_capacity(day + timedelta(minutes=30), 30)
check('1 машина в час: в 10:30 места нет', not free and total == 1, f'{free} {busy} {total}')
free, busy, total = appointments.check_capacity(day + timedelta(hours=1), 60)
check('в 11:00 место есть', free, f'{free} {busy} {total}')
SettingsService(db).set('booking_posts', '2')
free, _busy, total = appointments.check_capacity(day + timedelta(minutes=30), 30)
check('2 машины в час: в 10:30 место есть', free and total == 2, f'{free} {total}')
SettingsService(db).set('booking_posts', '1')

print('\n=== Наряд из записи — без поста ===')
ShiftService(db).open_shift(open_posts=2)
EmployeeService(db).register_employee(1, name='Сергей')
EmployeeService(db).start_shift(1)
today = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
booked = appointments.create(today, duration_minutes=30, client_name='Ольга',
                             client_phone='79160000002', license_plate='В222ВВ77',
                             wheels_assembled=True)
booked.wheel_diameter = 'R16'
db.commit()
order = queue.open_booking_order(booked)
check('наряд с клиентом и диаметром', order.client is not None and order.wheel_diameter == 'R16')
check('пост не поставлен', order.post_number is None, str(order.post_number))

print('\n=== Серверу: запись по часам, без прогноза постов ===')
sync = SyncService(db)
settings = sync._collect_settings()
check('серверу — booking_mode hourly', settings.get('booking_mode') == 'hourly')
check('прогноза «пост освободится через…» нет', sync._collect_queue().get('free_in_minutes') is None)

print('\n=== Посты и очередь включили — всё как раньше ===')
queue.set_mode('on')
check('режим постов', not queue.no_posts() and queue.enabled() and not hourly_booking(db))
check('серверу — booking_mode posts', SyncService(db)._collect_settings().get('booking_mode') == 'posts')
other = appointments.create(today + timedelta(minutes=10), duration_minutes=30, client_name='Пётр',
                            client_phone='79160000003', license_plate='Е333ЕЕ77',
                            wheels_assembled=True)
other.wheel_diameter = 'R15'
db.commit()
order = queue.open_booking_order(other)
check('с постами — наряд из записи встаёт на свободный пост', order.post_number is not None)

db.close()
finish()
