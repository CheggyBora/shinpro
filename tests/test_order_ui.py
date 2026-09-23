"""Интерфейс наряда: колёса в сборе, плановое время, кнопка «Сохранить наряд»."""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('order_ui')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Service, Shift
from services import OrderService, EmployeeService
from services.shift_service import ShiftService

init_db()
initialize_data()

db = SessionLocal()
ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

# Услуге даём длительность и себестоимость расходников
service = db.query(Service).filter(Service.name == 'Шиномонтаж').first()
service.duration_minutes = 15
service.consumable_cost = 50.0
db.commit()
db.close()

import tkinter as tk
from tkinter import ttk
import ui.orders_tab

popups = _setup.silence_dialogs(ui.orders_tab)
from ui import MainWindow


def find_dialogs(widget, acc=None):
    if acc is None:
        acc = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Toplevel) and not child.wm_overrideredirect():
            acc.append(child)
        find_dialogs(child, acc)
    return acc


def texts(widget, acc=None):
    if acc is None:
        acc = []
    try:
        value = widget.cget('text')
        if value:
            acc.append(str(value))
    except Exception:
        pass
    for child in widget.winfo_children():
        texts(child, acc)
    return acc


root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
orders = app.orders_tab

print('=== В диалоге наряда спрашивают про колёса ===')
orders.prefilled_data = None
orders.license_entry.delete(0, tk.END)
orders.license_entry.insert(0, 'А123ВВ777')
orders.create_new_order()
root.update()

dialogs = find_dialogs(root)
check('диалог открылся', len(dialogs) == 1, f'окон: {len(dialogs)}')
if dialogs:
    dialog_texts = texts(dialogs[0])
    check('есть поле «Колёса»', any('Колёса' in t for t in dialog_texts),
          [t for t in dialog_texts if 'олёс' in t])
    dialogs[0].destroy()
    root.update()

print('\n=== Плановое время и кнопка сохранения ===')
order_service = OrderService(orders.db)
order = order_service.create_order('К900ОР99', 'R16', 'car', wheels_assembled=True)
orders.open_order_tab(order)
root.update()

widget = orders.active_orders[order.id]
check('кнопка «Сохранить наряд» есть',
      'Сохранить наряд' in widget.save_order_button.cget('text'),
      widget.save_order_button.cget('text'))
check('время показано', 'Время' in widget.time_label.cget('text'),
      widget.time_label.cget('text'))

print('\n=== Добавили услугу — время не меняется до сохранения ===')
widget.add_service(db_service := SessionLocal().query(Service).filter(
    Service.name == 'Шиномонтаж', Service.vehicle_type == 'car').first())
root.update()

check('появилось предупреждение о несохранённом',
      'не сохранено' in widget.unsaved_label.cget('text'),
      widget.unsaved_label.cget('text'))
check('в предупреждении видно будущее время',
      '25 мин' in widget.unsaved_label.cget('text'),
      widget.unsaved_label.cget('text'))
check('плановое время пока не изменилось',
      (widget.order.planned_minutes or 0) == 0, str(widget.order.planned_minutes))

print('\n=== Нажали «Сохранить наряд» ===')
widget.save_composition(silent=True)
root.update()
check('плановое время стало 10 + 15 = 25 мин', widget.order.planned_minutes == 25,
      str(widget.order.planned_minutes))
check('предупреждение снято', widget.unsaved_label.cget('text') == '',
      widget.unsaved_label.cget('text'))
check('время показано в строке', '25 мин' in widget.time_label.cget('text'),
      widget.time_label.cget('text'))

print('\n=== Расходники видны в наряде ===')
check('строка расходников заполнена',
      'Расходники' in widget.salary_base_label.cget('text'),
      widget.salary_base_label.cget('text'))
check('база для ЗП посчитана',
      'База для ЗП' in widget.salary_base_label.cget('text'),
      widget.salary_base_label.cget('text'))

print('\n=== Отложенное автосохранение отменяется при закрытии вкладки ===')
widget.schedule_autosave()
check('автосохранение запланировано', widget._autosave_job is not None)
orders.close_order_tab(order.id)
root.update()
check('после закрытия вкладки отменено', widget._autosave_job is None)

root.destroy()
finish()
