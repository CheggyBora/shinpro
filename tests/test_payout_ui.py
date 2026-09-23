"""
Экран выдачи зарплаты: остатки, выдача под PIN, история, ведомость.

Главное, что проверяется, — человек видит остаток до того, как
вводит сумму, и не может выдать деньги без PIN. И второе: аванс
спрашивает подтверждение, а не проходит молча.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('payout_ui')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Service, SalaryPayout, Employee
from services import (OrderService, SalaryService, EmployeeService,
                      PayoutService)
from services.shift_service import ShiftService

init_db()
initialize_data()

db = SessionLocal()
ShiftService(db).open_shift()

employees = EmployeeService(db)
employees.register_employee(1, 'Игорь')
employees.start_shift(1)

db.add(Service(name='Шиномонтаж колеса', vehicle_type='car', price_r16=1000.0,
               consumable_cost=0.0))
db.commit()
service_id = db.query(Service).filter(
    Service.name == 'Шиномонтаж колеса').first().id

orders = OrderService(db)
order = orders.create_order('А111АА77', 'R16', 'car')
orders.add_service_to_order(order.id, service_id)
order.employee_ids = '1'
db.commit()
SalaryService(db).process_payment(order.id, 'cash',
                                  orders.calculate_total(order.id))
db.close()

import tkinter as tk
from tkinter import ttk
import ui.employees_tab

popups = _setup.silence_dialogs(ui.employees_tab)

from ui import MainWindow


def find_dialogs(widget, acc=None):
    if acc is None:
        acc = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Toplevel) and not child.wm_overrideredirect():
            acc.append(child)
        find_dialogs(child, acc)
    return acc


def collect(widget, kind, acc=None):
    if acc is None:
        acc = []
    if isinstance(widget, kind):
        acc.append(widget)
    for child in widget.winfo_children():
        collect(child, kind, acc)
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
tab = app.employees_tab

print('=== Кнопки выдачи на экране сотрудников ===')
screen = texts(tab.frame)
check('есть кнопка выдачи', any('Выдать зарплату' in t for t in screen))
check('есть ведомость', any('Ведомость за период' in t for t in screen))

print('\n=== Экран выдачи показывает остаток ===')
tab.open_payout()
root.update()
dialogs = find_dialogs(root)
check('окно выдачи открылось', len(dialogs) == 1, f'окон: {len(dialogs)}')

dialog = dialogs[0]
trees = collect(dialog, ttk.Treeview)
rows = [trees[0].item(item)['values'] for item in trees[0].get_children()]
check('сотрудник в списке', len(rows) == 1, str(rows))
check('видно имя', 'Игорь' in str(rows[0]), str(rows[0]))
check('начислено 400', '400' in str(rows[0]), str(rows[0]))
check('к выдаче 400', str(rows[0]).count('400') >= 2, str(rows[0]))

entries = collect(dialog, tk.Entry)
check('есть поле суммы, PIN и комментарий', len(entries) >= 3,
      f'полей: {len(entries)}')
check('PIN скрыт звёздочками',
      any(entry.cget('show') for entry in entries),
      str([entry.cget('show') for entry in entries]))

print('\n=== Выбор сотрудника подставляет остаток ===')
trees[0].selection_set(trees[0].get_children()[0])
root.update()
amount = entries[0]
check('сумма подставилась', amount.get() == '400', amount.get())
check('подсказка называет остаток',
      any('к выдаче' in t and 'Игорь' in t for t in texts(dialog)),
      str([t for t in texts(dialog) if 'выдаче' in t]))

print('\n=== Без верного PIN не выдаётся ===')
pin = [entry for entry in entries if entry.cget('show')][0]
pin.delete(0, tk.END)
pin.insert(0, '9999')

buttons = [b for b in collect(dialog, ttk.Button) if b.cget('text') == 'Выдать']
check('кнопка выдачи есть', len(buttons) == 1)
buttons[0].invoke()
root.update()

db = SessionLocal()
check('выдача не записалась', db.query(SalaryPayout).count() == 0)
check('человеку сказали про PIN',
      any('PIN' in str(item[2]) for item in popups), str(popups[-1:]))
db.close()

print('\n=== С верным PIN зарплата выдаётся ===')
pin.delete(0, tk.END)
pin.insert(0, '0000')
buttons[0].invoke()
root.update()

db = SessionLocal()
payout = db.query(SalaryPayout).first()
check('выдача записана', payout is not None)
check('сумма 400', payout and payout.amount == 400.0,
      str(payout.amount if payout else None))
check('способ — наличные', payout and payout.method == 'cash')
check('остаток обнулился', PayoutService(db).balance(1) == 0.0,
      str(PayoutService(db).balance(1)))
db.close()

for opened in find_dialogs(root):
    opened.destroy()
root.update()

print('\n=== Аванс спрашивает подтверждение ===')
tab.open_payout()
root.update()
dialog = find_dialogs(root)[0]
entries = collect(dialog, tk.Entry)
amount, pin = entries[0], [e for e in entries if e.cget('show')][0]

trees = collect(dialog, ttk.Treeview)
trees[0].selection_set(trees[0].get_children()[0])
root.update()

amount.delete(0, tk.END)
amount.insert(0, '5000')
pin.delete(0, tk.END)
pin.insert(0, '0000')

before = len(popups)
[b for b in collect(dialog, ttk.Button) if b.cget('text') == 'Выдать'][0].invoke()
root.update()

asked = [item for item in popups[before:] if item[0] == 'askyesno']
check('спросили про аванс', len(asked) == 1, str(popups[before:]))
check('в вопросе названо словом «аванс»',
      any('аванс' in str(item[2]).lower() or 'аванс' in str(item[1]).lower()
          for item in asked), str(asked))

db = SessionLocal()
# silence_dialogs отвечает «да» на любой вопрос — значит аванс выдан
advance = db.query(SalaryPayout).filter(SalaryPayout.amount == 5000.0).first()
check('после согласия аванс выдан', advance is not None)
check('он помечен авансом', advance and advance.is_advance is True)
check('остаток ушёл в минус', PayoutService(db).balance(1) == -5000.0,
      str(PayoutService(db).balance(1)))
db.close()

for opened in find_dialogs(root):
    opened.destroy()
root.update()

print('\n=== История выплат и отмена ===')
tab.show_payout_history()
root.update()
dialog = find_dialogs(root)[0]
trees = collect(dialog, ttk.Treeview)
rows = [trees[0].item(item)['values'] for item in trees[0].get_children()]
check('в истории две выплаты', len(rows) == 2, str(rows))
check('видно, что выдано в цеху', 'цех' in str(rows), str(rows))

for opened in find_dialogs(root):
    opened.destroy()
root.update()

print('\n=== Ведомость сохраняется в файл ===')
before = len(popups)
tab.export_statement()
root.update()

messages = [str(item[2]) for item in popups[before:]]
check('ведомость сохранена', any('vedomost' in text for text in messages),
      str(messages))

saved = [text for text in messages if 'vedomost' in text]
if saved:
    path = saved[0].split('\n')[1].strip()
    check('файл на месте', os.path.exists(path), path)
    # Читаем той же кодировкой, какой пишет выгрузка: иначе проверка
    # ругается на кириллицу, а не на содержимое
    from services.export_service import ENCODING
    content = open(path, encoding=ENCODING, errors='replace').read()
    check('в ведомости есть сотрудник', 'Игорь' in content, content[:200])
    check('есть строка итога', 'ИТОГО' in content, content[:400])
    check('видно начисленное', '400' in content, content[:400])

root.destroy()
finish()
