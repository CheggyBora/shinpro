"""
Запись на мойку в цеху (docs/booking_wash.md) — без сервера, своей базой.

  · запись на мойку не занимает пост шиномонтажа и наоборот;
  · у мойки свои посты под запись и своя длительность;
  · «Запись» в режиме «Мойка» показывает только мойку, живой очереди нет;
  · «Приехал» по записи на мойку открывает наряд мойки с классом;
  · живая очередь шиномонтажа записи мойки не видит.
"""
import _setup
from _setup import use_temp_db, check, finish

import os
from datetime import datetime, timedelta

use_temp_db('booking_wash_shop')
os.chdir(_setup.PROJECT_DIR)
shown = _setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Appointment, WorkOrder
from services import EmployeeService, directions
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.appointment_service import AppointmentService
from services import booking_gateway
from utils import get_moscow_time, as_naive

init_db()
db = SessionLocal()
directions.set_enabled(db, True, True)
settings = SettingsService(db)
settings.set('wash_booking_posts', '1')
settings.set('wash_booking_minutes', '40')
service = AppointmentService(db)
day = as_naive(get_moscow_time()).date() + timedelta(days=1)
at = datetime(day.year, day.month, day.day, 12, 0)

print('=== Занятость раздельная ===')
service.set_posts_for_day(day, 1)
service.create(at, 60, license_plate='А100АА77', client_phone='79160000001')
free, busy, posts = service.check_capacity(at, 30, direction='wash')
check('шиномонтаж занят — мойка свободна', free and busy == 0 and posts == 1, f'{free} {busy} {posts}')
service.create(at, 40, license_plate='К555КК77', client_phone='79160000002',
               direction='wash', wash_class='crossover')
free, busy, posts = service.check_capacity(at, 30, direction='wash')
check('второй на мойку в то же время — нельзя (1 пост)', not free and busy == 1)
free, _b, _p = service.check_capacity(at + timedelta(hours=2), 30, direction='tire')
check('шиномонтаж через два часа — свободно', free)
check('лента мойки — только мойка',
      [a.license_plate for a, _c in service.layout_day(day, direction='wash')] == ['К555КК77'])
check('лента шиномонтажа — без мойки',
      [a.license_plate for a, _c in service.layout_day(day, direction='tire')] == ['А100АА77'])

print()
print('=== Шлюз записи: направление с переключателя ===')
booking_gateway.CURRENT_DIRECTION = 'wash'
gateway = booking_gateway.get_booking(db)
state = gateway.load_day(day)
check('посты мойки под запись — из настроек', state['posts'] == 1)
check('длительность мойки — из настроек', booking_gateway.wash_duration(db) == 40)
booking_gateway.CURRENT_DIRECTION = 'tire'

print()
print('=== Живая очередь не видит мойку ===')
today_wash = service.create(as_naive(get_moscow_time()).replace(second=0, microsecond=0),
                            40, license_plate='Р200РР77', client_phone='79160000003',
                            direction='wash', wash_class='sedan')
from services.live_queue_service import LiveQueueService
seen = [a.license_plate for a in LiveQueueService(db)._today_bookings()]
check('записи мойки в очереди шиномонтажа нет', 'Р200РР77' not in seen, str(seen))
db.close()

print()
print('=== В окне: «Запись» в режиме «Мойка» и «Приехал» ===')
import tkinter as tk
import ui.appointment_dialogs as dialogs_module
shown = _setup.silence_dialogs(dialogs_module)
from ui import MainWindow
root = tk.Tk()
root.withdraw()
app = MainWindow(root)
ShiftService(app.db).open_shift(open_posts=2)
EmployeeService(app.db).register_employee(1)
EmployeeService(app.db).start_shift(1)
app.set_mode('wash')
root.update()
tab = app.appointments_tab
check('запись в режиме мойки', tab.direction == 'wash' and tab.booking.direction == 'wash')
check('живая очередь у мойки спрятана', tab.tabs.tab(tab.queue.frame, 'state') == 'hidden')
check('строки постов по дням нет', not tab.posts_row.winfo_manager())

from ui.appointment_dialogs import AppointmentDialog, AppointmentDetailsDialog
dialog = AppointmentDialog(root, app.db, when=at + timedelta(hours=3))
check('окно записи — мойка', dialog.direction == 'wash')
dialog.plate_entry.insert(0, 'М777ММ77')
dialog.phone_entry.insert(0, '79160000009')
dialog.save()
check('без класса не записать', any('класс' in (t or '').lower() for _k, _ti, t in shown))
dialog.wash_class_var.set('Джип')
dialog.save()
made = app.db.query(Appointment).filter(Appointment.license_plate == 'М777ММ77').first()
check('записали на мойку с классом', made is not None and made.direction == 'wash'
      and made.wash_class == 'jeep' and made.duration_minutes == 40)

details = AppointmentDetailsDialog(root, app.db, today_wash.id, orders_tab=app.orders_tab)
details.mark_arrived()
order = app.db.query(WorkOrder).order_by(WorkOrder.id.desc()).first()
check('«Приехал» — наряд мойки', order is not None and order.directions == 'wash'
      and order.wash_class == 'sedan' and order.wash_post_number == 1)
app.set_mode('tire')
check('вернулись — живая очередь снова есть', tab.tabs.tab(tab.queue.frame, 'state') == 'normal')
root.destroy()
finish()
