"""
Наряд, открытый в одной смене и пробитый в другой.

Владелец решил: наряд проводится тем днём, когда машину закрыли.
Приняли вечером, смена закрылась (сама или руками), пробили утром —
выручка и зарплата в утренней смене. Мастера — те, кто был при создании.

  · неоплаченный наряд не теряется: после перезапуска он снова на экране;
  · пробили в новой смене — он в новой смене, а не во вчерашней;
  · начисление — тем же мастерам, что были при создании;
  · без открытой смены пробить нельзя.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('shift_carryover')
os.chdir(_setup.PROJECT_DIR)
shown = _setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, WorkOrder, SalaryTransaction
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()

shifts = ShiftService(db)
employees = EmployeeService(db)
orders = OrderService(db)

print('=== Вечер: приняли машину, смену закрыли ===')
first = shifts.open_shift(open_posts=2)
employees.register_employee(1)
employees.register_employee(2)
employees.start_shift(1)
employees.start_shift(2)
order = orders.create_order('А111АА77', 'R16', 'car', create_client=False)
service = db.query(Service).first()
orders.add_service_to_order(order.id, service.id)
check('мастера — оба, кто был при создании', order.employee_ids == '1,2', order.employee_ids)
employees.end_shift(2)
check('неоплаченный — в списке открытых', [o.id for o in orders.unpaid_orders()] == [order.id])
shifts.close_shift(first.id)

print()
print('=== Перезапуск: наряд снова на экране ===')
import tkinter as tk
from ui import MainWindow
root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
check('вкладка неоплаченного наряда открыта', order.id in app.orders_tab.active_orders,
      str(list(app.orders_tab.active_orders)))

widget = app.orders_tab.active_orders[order.id]
shown.clear()
widget.process_payment()
check('без смены пробить нельзя', any('Откройте смену' in (text or '') for _k, _t, text in shown),
      str(shown[-1:]))
root.destroy()

print()
print('=== Утро: новая смена, пробили ===')
second = shifts.open_shift(open_posts=2)
total = orders.calculate_total(order.id)
SalaryService(db).process_payment(order.id, 'cash', total)
db.refresh(order)
check('наряд — в новой смене', order.shift_id == second.id, f'{order.shift_id} против {second.id}')
paid_to = sorted(t.employee_id for t in db.query(SalaryTransaction).filter(
    SalaryTransaction.work_order_id == order.id).all())
check('начислено тем, кто был при создании', paid_to == [1, 2], str(paid_to))
details = shifts.get_shift_salary_details(second.id)
check('зарплата — в сводке новой смены', set(details) == {1, 2}, str(list(details)))
check('во вчерашней сводке его нет', shifts.get_shift_salary_details(first.id) == {})
check('больше не в списке открытых', orders.unpaid_orders() == [])

db.close()
finish()
