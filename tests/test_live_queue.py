"""
Живая очередь и раздача постов (docs/live_queue.md).

Проверяем то, ради чего всё затевалось:

  · одна машина — одно место; тот же номер с тем же телефоном
    возвращает на своё место, с чужим — отказ;
  · пост из очереди не отдаётся, если он понадобится записи:
    запись раз в час, запас на допы;
  · наряд из очереди открывается сразу заполненным: номер, телефон,
    диаметр, пост и услуги за комплект по колёсам;
  · оплата освобождает пост и закрывает место;
  · позвали и не подъехал — в конец, второй раз — выбывает.
"""
import _setup
from _setup import use_temp_db, check, finish

import os
from datetime import datetime, timedelta

use_temp_db('live_queue')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from models import Service, Appointment, WorkOrder, Car, Client
from models.live_queue import WAITING, CALLED, SERVING, DONE, LEFT
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.live_queue_service import LiveQueueService, QueueError
from utils import as_naive, get_moscow_time

init_db()
db = SessionLocal()

for name, minutes in (('Съем+Установка', 20), ('Мойка', 10),
                      ('Балансировка', 15), ('Шиномонтаж', 15)):
    db.add(Service(name=name, vehicle_type='car', price_r16=1000,
                   duration_minutes=minutes))
db.commit()
SettingsService(db).set('order_base_minutes', '10')

ShiftService(db).open_shift(open_posts=3)
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)

queue = LiveQueueService(db)
orders = OrderService(db)

print('=== Встать в очередь ===')
a = queue.add('а123вв777', '+7 909 901-89-31', 'R16', True, source='qr')
check('номер приведён к виду', a.license_plate == 'А123ВВ777', a.license_plate)
check('телефон приведён к виду', a.phone == '79099018931', a.phone)
check('ждёт', a.status == WAITING)
again = queue.add('А123ВВ777', '89099018931')
check('тот же номер и телефон — то же место', again.id == a.id)
try:
    queue.add('А123ВВ777', '79160000000')
    check('с чужим телефоном — отказ', False)
except QueueError as e:
    check('с чужим телефоном — отказ', 'другим телефоном' in str(e), str(e))
try:
    queue.add('К900ОР99', '79160000000', 'R30', True)
    check('диаметр вне списка — отказ', False)
except QueueError:
    check('диаметр вне списка — отказ', True)

# Знакомая машина: диаметр и колёса из карточки
db.add(Car(license_plate='Е555КХ77', vehicle_type='car', wheel_diameter='R18',
           wheels_assembled=False))
db.commit()
known = queue.add('Е555КХ77', '79160000001')
check('диаметр из карточки', known.wheel_diameter == 'R18', known.wheel_diameter)
check('колёса из карточки', known.wheels_assembled is False)

print()
print('=== Состав наряда и время ===')
check('в сборе — съём, мойка, баланс',
      queue.kit(True) == ['Съем+Установка', 'Мойка', 'Балансировка'], str(queue.kit(True)))
check('только шины — плюс шиномонтаж', 'Шиномонтаж' in queue.kit(False))
check('не указано — пусто', queue.kit(None) == [])
# Пакеты: на дисках полчаса, только шины час — плюс запас 20
check('на дисках: 30 + запас = 50 минут', queue.expected_minutes(a) == 50,
      str(queue.expected_minutes(a)))
check('только шины: 60 + запас = 80 минут', queue.expected_minutes(known) == 80,
      str(queue.expected_minutes(known)))

print()
print('=== Записей нет — свободные посты отдаются очереди ===')
now = as_naive(get_moscow_time())
plan = queue.suggestion(now)
check('три свободных поста', [p['post'] for p in plan] == [1, 2, 3], str(plan))
check('пост 1 — первому', plan[0]['entry'].id == a.id)
check('пост 2 — второму', plan[1]['entry'].id == known.id)
check('пост 3 — некого', plan[2]['entry'] is None and plan[2]['hold_for'] is None)

print()
print('=== Запись на ближайший час держит посты ===')
# Сейчас 09:40, в 10:00 записаны двое. Пост 1 занят до 10:20
# (начат в 09:00, 80 минут), посты 2 и 3 свободны
base = now.replace(hour=9, minute=40, second=0, microsecond=0)
ten = base.replace(hour=10, minute=0)
for plate in ('В001ВВ77', 'В002ВВ77'):
    db.add(Appointment(scheduled_at=ten, duration_minutes=60,
                       license_plate=plate, status='scheduled'))
busy = orders.create_order('С111СС77', 'R16', 'car', create_client=False)
busy.post_number = 1
busy.started_at = base.replace(hour=9, minute=0)
busy.planned_minutes = 80
db.commit()

plan = queue.suggestion(base)
check('свободны посты 2 и 3', [p['post'] for p in plan] == [2, 3], str(plan))
check('никого из очереди не зовём: к 10:00 нужны два поста',
      all(p['entry'] is None for p in plan), str(plan))
check('пост держим под запись на 10:00',
      plan[0]['hold_for'] == ten, str(plan[0]['hold_for']))

# Наряд на посту 1 закончится раньше — в 09:50
busy.planned_minutes = 50
db.commit()
plan = queue.suggestion(base)
check('теперь один пост можно отдать очереди',
      sum(1 for p in plan if p['entry']) == 1, str(plan))
check('и второй держим под запись',
      sum(1 for p in plan if p['entry'] is None and p['hold_for']) == 1, str(plan))

ok, _ = queue.booking_allows(15, 2, base)
check('короткая работа успевает до записи', ok)

# Прикидка времени не обещает раньше записи: второму в очереди пост
# достанется только после записанных на 10:00
times = queue.estimates(base)
check('первому — сейчас, пост свободен', times[a.id] == base, str(times))
check('второму — не раньше, чем запись на 10:00 встанет',
      times[known.id] >= ten, str(times))

# Запись обслужена — посты свободны
for row in db.query(Appointment).all():
    row.status = 'arrived'
busy.status = 'paid'
busy.paid_at = get_moscow_time()
db.commit()

print()
print('=== Позвать и открыть наряд ===')
called = queue.call(a.id, 2)
check('позван на пост 2', called.status == CALLED and called.post_number == 2)
states = {s['post']: s['state'] for s in queue.posts()}
check('пост 2 — едет к нему', states[2] == 'called', str(states))
try:
    queue.call(known.id, 2)
    check('на занятый пост не позвать', False)
except QueueError as e:
    check('на занятый пост не позвать', 'занят' in str(e), str(e))

order = queue.open_order(a.id)
check('наряд на посту 2', order.post_number == 2, str(order.post_number))
check('номер машины', order.car.license_plate == 'А123ВВ777')
check('телефон клиента', order.client and order.client.phone == '79099018931')
check('диаметр', order.wheel_diameter == 'R16')
names = sorted(i.service.name for i in orders.get_order_items(order.id))
check('услуги за комплект: съём, мойка, баланс',
      names == ['Балансировка', 'Мойка', 'Съем+Установка'], str(names))
check('по одной — за комплект',
      all(i.quantity == 1 for i in orders.get_order_items(order.id)))
check('наряд помнит пакет — 30 минут', order.package_minutes == 30)
check('план не меньше пакета',
      orders.calculate_planned_minutes(order.id) >= 30)
# Без длительностей в прайсе план всё равно — время пакета
for service in db.query(Service).all():
    service.duration_minutes = 0
SettingsService(db).set('order_base_minutes', '0')
db.commit()
check('прайс без длительностей — план по пакету',
      orders.calculate_planned_minutes(order.id) == 30,
      str(orders.calculate_planned_minutes(order.id)))
db.refresh(a)
check('место — машина на посту', a.status == SERVING)
check('пост 2 занят нарядом',
      {s['post']: s['state'] for s in queue.posts()}[2] == 'busy')

SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))
db.refresh(a)
check('оплата закрыла место', a.status == DONE)
check('пост 2 снова свободен',
      {s['post']: s['state'] for s in queue.posts()}[2] == 'free')

print()
print('=== Позвали — не подъехал ===')
third = queue.add('Х333ХХ77', '79160000003', 'R15', True)
queue.call(known.id, 1)
expired = queue.expire_calls(as_naive(get_moscow_time()) + timedelta(minutes=6))
check('через 6 минут вызов сгорел', [e.id for e in expired] == [known.id])
db.refresh(known)
check('в конец очереди', known.status == WAITING and known.misses == 1)
check('теперь первым ждёт другой', queue.waiting()[0].id == third.id,
      str([e.license_plate for e in queue.waiting()]))
queue.call(known.id, 1)
queue.missed(known.id)
db.refresh(known)
check('второй пропуск — выбывает', known.status == LEFT)

print()
print('=== Примерное время ===')
fourth = queue.add('У444УУ77', '79160000004', 'R16', True)
times = queue.estimates()
check('у каждого ждущего есть время', set(times) == {third.id, fourth.id}, str(times))

queue.leave(third.id)
db.refresh(third)
check('ушёл — убран', third.status == LEFT)

db.close()

print()
print('=== Раздел «Живая очередь» в цеху ===')
import tkinter as tk
import ui.live_queue_panel as panel_module
import ui.orders_tab

_setup.silence_dialogs(panel_module, ui.orders_tab)
from ui import MainWindow

root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
panel = app.appointments_tab.queue
check('вкладка называется «Живая очередь»',
      any('Живая очередь' in app.appointments_tab.tabs.tab(t, 'text')
          for t in app.appointments_tab.tabs.tabs()))

ui_queue = panel.service
fresh = ui_queue.add('М777ММ77', '79160000007', 'R17', False, source='qr')
panel.load()
rows = [panel.tree.item(r)['values'] for r in panel.tree.get_children()]
plates = [str(r[1]) for r in rows]
check('в списке видна машина', 'М777ММ77' in plates, str(plates))
mine = next(r for r in rows if str(r[1]) == 'М777ММ77')
check('колёса и диаметр видны', 'R17' in [str(v) for v in mine] and 'только шины' in mine, str(mine))
check('видно, что встал по QR', 'по QR' in mine, str(mine))

post_titles = [w.cget('text') for box in panel.posts_frame.winfo_children()
               for w in box.winfo_children() if isinstance(w, tk.Label)]
check('посты нарисованы', any(t.startswith('Пост 1') for t in post_titles), str(post_titles))

panel._call(fresh.id, 3)
panel.tree.selection_set(str(fresh.id))
opened = []
panel.on_order_opened = lambda: opened.append(True)
panel.open_order()
root.update()
check('наряд открылся во вкладке «Наряды»',
      any(o.post_number == 3 for o in [w.order for w in app.orders_tab.active_orders.values()]),
      str([(o, w.order.post_number) for o, w in app.orders_tab.active_orders.items()]))
check('главное окно переключили на наряды', opened == [True])
order = next(w.order for w in app.orders_tab.active_orders.values() if w.order.post_number == 3)
names = sorted(i.service.name for i in OrderService(app.db).get_order_items(order.id))
check('в наряде шиномонтаж — только шины',
      names == ['Балансировка', 'Мойка', 'Съем+Установка', 'Шиномонтаж'], str(names))

root.destroy()
finish()
