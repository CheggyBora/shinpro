"""
Мойка — второе направление объекта (services/directions.py).

Решения владельца от 26.10.2026:

  · направления включаются в настройках; пока мойка выключена — всё как
    было, переключателя нет;
  · наряд один: при создании отмечают шиномонтаж, мойку или оба, потом
    можно дополнить вторым направлением;
  · цена мойки — по классу машины, класс запоминается за машиной;
  · у мойки свои посты;
  · услуга мойки начисляется тому, кто её делал, по его проценту мойки;
    шиномонтаж — как раньше, мастерам смены по проценту шиномонтажа;
  · пока у мойки не выбран сотрудник, пробить нельзя;
  · выручка в сводке смены делится по строкам.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('wash')
os.chdir(_setup.PROJECT_DIR)
shown = _setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, SalaryTransaction, Employee, Car
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services import directions
from services.wash_posts import WashPosts

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()

print('=== Пока мойка выключена — всё как было ===')
check('работает только шиномонтаж', directions.enabled(db) == ['tire'])
shifts = ShiftService(db)
employees = EmployeeService(db)
orders = OrderService(db)
salary = SalaryService(db)
shifts.open_shift(open_posts=2)
for n in (1, 2):
    employees.register_employee(n)
    employees.start_shift(n)
plain = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
check('наряд — шиномонтаж', plain.directions == 'tire' and plain.wash_post_number is None)

print()
print('=== Включили мойку ===')
directions.set_enabled(db, True, True)
check('работают оба', directions.enabled(db) == ['tire', 'wash'])
wash_services = db.query(Service).filter(Service.direction == 'wash').all()
check('прайс мойки заведён названиями', len(wash_services) == len(directions.WASH_STARTER))
body = next(s for s in wash_services if s.name.startswith('Мойка кузова'))
body.price_sedan, body.price_crossover, body.price_jeep = 700, 900, 1100
salon = next(s for s in wash_services if s.name == 'Уборка салона')
salon.price_crossover = 1200
db.commit()
try:
    directions.set_enabled(db, False, False)
    check('выключить всё нельзя', False)
except ValueError:
    check('выключить всё нельзя', True)

e1 = db.query(Employee).get(1)
e1.salary_percent, e1.wash_percent = 40, 30
e2 = db.query(Employee).get(2)
e2.salary_percent, e2.wash_percent = 40, 25
db.commit()

print()
print('=== Наряд только на мойку ===')
try:
    orders.create_order('К555КК77', '', 'car', create_client=False, directions=['wash'])
    check('без класса — нельзя', False)
except ValueError:
    check('без класса — нельзя', True)
db.rollback()
wash_order = orders.create_order('К555КК77', '', 'car', create_client=False,
                                 directions=['wash'], wash_class='crossover')
check('направление — мойка', wash_order.directions == 'wash')
check('занят пост мойки 1', wash_order.wash_post_number == 1, str(wash_order.wash_post_number))
check('пост шиномонтажа не занят', wash_order.post_number is None)
check('класс запомнился за машиной',
      db.query(Car).filter(Car.license_plate == 'К555КК77').first().wash_class == 'crossover')
item_body = orders.add_service_to_order(wash_order.id, body.id)
item_salon = orders.add_service_to_order(wash_order.id, salon.id)
check('цена — по классу «кроссовер»', item_body.price == 900 and item_salon.price == 1200,
      f'{item_body.price} {item_salon.price}')
check('строка — мойка', item_body.direction == 'wash')
check('на смене двое — сотрудник не выбран сам', item_body.employee_id is None)
check('пробить нельзя, пока не выбран, кто делал',
      salary.unassigned_wash(wash_order.id) == ['Мойка кузова, 2 фазы', 'Уборка салона'])
try:
    salary.process_payment(wash_order.id, 'cash', orders.calculate_total(wash_order.id))
    check('оплата без сотрудника — отказ', False)
except ValueError as e:
    check('оплата без сотрудника — отказ', 'кто делал' in str(e), str(e))
orders.assign_wash(wash_order.id, 1)
orders.set_item_employee(item_salon.id, 2)
people, nobody = salary.preview(wash_order.id)
check('кузов — первому по 30%', people[1]['amount'] == 270.0, str(people.get(1)))
check('салон — второму по 25%', people[2]['amount'] == 300.0, str(people.get(2)))
salary.process_payment(wash_order.id, 'card', orders.calculate_total(wash_order.id))
paid = {t.employee_id: t.amount for t in db.query(SalaryTransaction).filter(
    SalaryTransaction.work_order_id == wash_order.id).all()}
check('начислено по строкам', paid == {1: 270.0, 2: 300.0}, str(paid))
check('пост мойки освободился', WashPosts(db).first_free() == 1)

print()
print('=== Приехал на шиномонтаж — решил помыться ===')
mixed = orders.create_order('М777ММ77', 'R16', 'car', create_client=False)
tire_service = db.query(Service).filter(Service.name == 'Шиномонтаж').first()
orders.add_service_to_order(mixed.id, tire_service.id)
try:
    orders.add_direction(mixed.id, 'wash')
    check('мойка без класса — спросим', False)
except ValueError:
    check('мойка без класса — спросим', True)
db.rollback()
orders.add_direction(mixed.id, 'wash', wash_class='sedan')
db.refresh(mixed)
check('в наряде оба направления', mixed.directions == 'tire,wash')
check('мойка заняла пост', mixed.wash_post_number == 1)
wash_line = orders.add_service_to_order(mixed.id, body.id)
check('мойка седана — 700', wash_line.price == 700)
orders.set_item_employee(wash_line.id, 2)
people, _ = salary.preview(mixed.id)
check('шиномонтаж делят оба по 40%: по 400', people[1]['amount'] == 400.0, str(people.get(1)))
check('второму ещё мойка 25% от 700', people[2]['amount'] == 400.0 + 175.0, str(people.get(2)))
salary.process_payment(mixed.id, 'cash', orders.calculate_total(mixed.id))

print()
print('=== На сервер: начисления по направлениям (дашборд мойки) ===')
from services.sync_service import SyncService


def sent_accruals(order_id):
    visit = next(v for v in SyncService(db)._collect_visits() if v['local_id'] == order_id)
    return sorted((a['employee_local_id'], a['direction'], a['amount']) for a in visit['accruals']), visit


accruals, visit = sent_accruals(mixed.id)
check('строки наряда — со своим направлением',
      sorted(i['direction'] for i in visit['items']) == ['tire', 'wash'])
check('первому — только шиномонтаж, второму — шиномонтаж и мойка отдельно',
      accruals == [(1, 'tire', 400.0), (2, 'tire', 400.0), (2, 'wash', 175.0)], str(accruals))
orders.refund_order(mixed.id, amount=orders.calculate_total(mixed.id) / 2, reason='половина')
accruals, _ = sent_accruals(mixed.id)
wash_back = [a for a in accruals if a[1] == 'wash' and a[2] < 0]
check('откат при возврате делится в той же доле',
      wash_back == [(2, 'wash', -87.5)] and round(sum(a[2] for a in accruals), 2) == 487.5, str(accruals))

print()
print('=== Наряд мойки + шиномонтаж: нужен диаметр ===')
second = orders.create_order('Р200РР77', '', 'car', create_client=False,
                             directions=['wash'], wash_class='jeep')
orders.add_direction(second.id, 'tire', wheel_diameter='R17')
db.refresh(second)
check('диаметр поставлен', second.wheel_diameter == 'R17' and second.directions == 'tire,wash')

print()
print('=== Сводка смены — по направлениям ===')
from services.shift_report_service import ShiftReportService
summary = ShiftReportService(db).build_summary(shifts.get_current_shift())
check('мойка в сводке', summary['by_direction'].get('wash') == 2100 + 700,
      str(summary['by_direction']))
check('шиномонтаж в сводке', summary['by_direction'].get('tire') == 2000, str(summary['by_direction']))
text = ShiftReportService(db).format_summary(summary)
check('строки направлений в тексте', 'мойка: 2800' in text, text)

print()
print('=== Тумблер: мастера шиномонтажа — на наряд ===')
directions.set_tire_assign(db, True)
assigned_order = orders.create_order('Т300ТТ77', 'R16', 'car', create_client=False)
check('мастеров смены в наряд не кладём — их выбирают', assigned_order.employee_ids is None)
tire_line = orders.add_service_to_order(assigned_order.id, tire_service.id)
check('построчно шиномонтаж не назначается', salary.unassigned_wash(assigned_order.id) == [])
try:
    salary.process_payment(assigned_order.id, 'cash', orders.calculate_total(assigned_order.id))
    check('без мастеров наряда пробить нельзя', False)
except ValueError:
    check('без мастеров наряда пробить нельзя', True)
db.rollback()
orders.set_order_masters(assigned_order.id, [2])
people, _ = salary.preview(assigned_order.id)
check('начислено только назначенному по ставке шиномонтажа',
      set(people) == {2} and people[2]['amount'] == 800.0, str(people))
salary.process_payment(assigned_order.id, 'cash', orders.calculate_total(assigned_order.id))
paid = {t.employee_id: t.amount for t in db.query(SalaryTransaction).filter(
    SalaryTransaction.work_order_id == assigned_order.id).all()}
check('остальным мастерам смены — ничего', paid == {2: 800.0}, str(paid))
directions.set_tire_assign(db, False)
check('выключили — как всегда', not directions.assigned(db, 'tire'))

print()
print('=== Ставки мойки ===')
from services.auth_service import AuthService
employees.update_salary_percent(1, 35, '0000', direction='wash')
db.refresh(e1)
check('ставка мойки поменялась, шиномонтажа — нет', e1.wash_percent == 35 and e1.salary_percent == 40)

print()
print('=== Календарь и контрагенты мойки — свой слой ===')
from datetime import date
from services.calendar_service import CalendarService, TaskError
calendar = CalendarService(db)
today = date.today()
tire_task = calendar.create('Еврошины — 8 шин', today, category='tires')
wash_task = calendar.create('Химия: шампунь 2 канистры', today, category='supply', direction='wash')
check('у шиномонтажа — только его задачи', [t.id for t in calendar.day(today, direction='tire')] == [tire_task.id])
check('у мойки — только её', [t.id for t in calendar.day(today, direction='wash')] == [wash_task.id])
check('лента мойки', [t.id for t in calendar.strip(direction='wash')] == [wash_task.id])
try:
    calendar.create('Не туда', today, category='supply', direction='tire')
    check('«Поставки» — раздел мойки, в шиномонтаже нельзя', False)
except TaskError:
    check('«Поставки» — раздел мойки, в шиномонтаже нельзя', True)
chem = calendar.save_counterparty(name='ХимПро', direction='wash')
calendar.save_counterparty(name='Еврошины')
check('контрагенты мойки отдельно', [c.name for c in calendar.counterparties('wash')] == ['ХимПро'])
check('шиномонтажа — свои', [c.name for c in calendar.counterparties('tire')] == ['Еврошины'])
check('в обмен уходит направление', calendar.task_payload(wash_task)['direction'] == 'wash'
      and calendar.counterparty_payload(chem)['direction'] == 'wash')
calendar.apply_server({'tasks': [{'uid': 'old-1', 'category': 'work', 'due_date': today.isoformat(),
                                   'title': 'Без направления', 'updated_at': '2026-10-26T10:00:00'}]})
check('старый сервер без направления — шиномонтаж', calendar.by_uid('old-1').direction == 'tire')

print()
print('=== В окне: переключатель и создание наряда ===')
import tkinter as tk
from ui import MainWindow
root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
check('переключатель нарисован', len(app.mode_switch.winfo_children()) == 2)
app.set_mode('wash')
root.update()
check('в мойке нет «Хранения» и «Покраски»',
      app.nav._items[app.nav.titles().index('Хранение шин')].get('hidden') is True)
check('кнопки услуг — мойки', app.orders_tab.mode == 'wash')
cal = app.calendar_tab
check('календарь общий — переключатель сверху его не трогает', cal.direction == 'all')
check('есть строка «Направление»', len(cal.direction_row.winfo_children()) == 4)
cal.set_direction_filter('wash')
filters = [w.cget('text') for w in cal.filter_row.winfo_children()]
check('фильтр «Мойка»: Рабочая, Поставки, Комментарии, Все',
      [f.replace('● ', '') for f in filters] == ['Разделы:', 'Рабочая', 'Поставки',
                                                 '✎ Комментарии', 'Все'], str(filters))
titles = [t.title for t in cal.service.day(today, None, cal.query_direction())]
check('видны только задачи мойки', titles == ['Химия: шампунь 2 канистры'], str(titles))
cal.set_direction_filter('all')
from ui.task_dialog import TaskDialog
import ui.task_dialog as task_dialog_module
shown = _setup.silence_dialogs(task_dialog_module)
dialog = TaskDialog(root, app.db, None, None, {'due_date': today})
check('новая задача: направление не выбрано', dialog.direction is None)
dialog.title.insert(0, 'Задача из окна')
dialog.save()
check('без направления не сохранить', any('шиномонтаж это или мойка' in (t or '') for _k, _ti, t in shown))
dialog.direction_var.set('wash')
dialog._direction_chosen()
check('после выбора — разделы мойки и её контрагенты',
      dialog.category.get() == 'work' and [p.name for p in dialog.parties] == ['ХимПро'])
dialog.category.set('supply')
dialog.save()
from models import CalendarTask
saved = app.db.query(CalendarTask).filter(CalendarTask.title == 'Задача из окна').first()
check('сохранилась в мойку', saved is not None and saved.direction == 'wash' and saved.category == 'supply',
      str(shown[-1:]))
app.set_mode('tire')
check('вернулись — разделы на месте',
      not app.nav._items[app.nav.titles().index('Хранение шин')].get('hidden'))
directions.set_enabled(app.db, True, False)
root.update()
check('выключили мойку — переключателя нет', len(app.mode_switch.winfo_children()) == 0)
root.destroy()

db.close()
finish()
