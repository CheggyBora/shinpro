"""
Раздельная оплата: часть наличными, часть картой (решение владельца 30.10.2026).

  · кассир вписывает наличные, картой — остаток;
  · в кассу смены идёт только наличная часть, в сводке — по частям;
  · чек и история пишут, сколько чем заплатили;
  · возврат: наличными не больше, чем ими дали, — из кассы ордером;
  · на сервер уходят способ и наличная часть.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('split_payment')
os.chdir(_setup.PROJECT_DIR)
shown = _setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction
from models.cash import CashOrder
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.cash_service import CashService
from services.shift_report_service import ShiftReportService
from services.print_service import PrintService
from services.sync_service import SyncService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=5400))
db.commit()
cash = CashService(db)
orders = OrderService(db)
salary = SalaryService(db)

shift = ShiftService(db).open_shift(cash_start='1 000')
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()


def new_order(plate):
    order = orders.create_order(plate, 'R16', 'car', create_client=False)
    orders.add_service_to_order(order.id, 1)
    return order, orders.calculate_total(order.id)


print('=== Проверка сумм ===')
order, total = new_order('А100АА77')
for bad in (0, total, total + 1, None):
    try:
        salary.process_payment(order.id, 'mixed', total, bad)
        check(f'наличные {bad} — нельзя', False)
    except ValueError as e:
        check(f'наличные {bad} — нельзя: {e}', 'картой' in str(e))
db.refresh(order)
check('после ошибки наряд не оплачен', order.status != 'paid')

print('\n=== Оплата ===')
salary.process_payment(order.id, 'mixed', total, 2000)
db.refresh(order)
check('способ и наличные записаны', order.payment_method == 'mixed' and order.cash_amount == 2000)
check('картой — остаток', order.cash_part == 2000 and order.card_part == total - 2000)
check('название', order.payment_title == 'Наличные 2 000 ₽ + карта 3 400 ₽', order.payment_title)
check('в кассу — только наличные', cash.expected(shift) == 3000, str(cash.expected(shift)))
line = [r for r in cash.lines(shift) if r['what'] == f'Наряд №{order.id}'][0]
check('в журнале кассы — обе части', 'наличными' in line['text'] and 'картой' in line['text']
      and line['effect'] == 2000, line['text'])
accrued = sum(t.amount for t in db.query(SalaryTransaction).filter_by(work_order_id=order.id))
check('зарплата — от всей суммы', round(accrued, 2) == round(total * 0.4, 2), str(accrued))

whole, whole_total = new_order('В200ВВ77')
salary.process_payment(whole.id, 'cash', whole_total, 999)
db.refresh(whole)
check('наличными целиком — без наличной части', whole.cash_amount is None
      and whole.cash_part == whole_total)

report = ShiftReportService(db).build_summary(shift)
check('сводка смены: наличные по частям', report['cash'] == 2000 + whole_total, str(report['cash']))
check('сводка смены: карта — остаток', report['card'] == total - 2000, str(report['card']))

print('\n=== Чек ===')
items = orders.get_order_items(order.id)
receipt = PrintService().generate_thermal_receipt(order, items, total, width_mm=58)
check('узкий чек создан', os.path.exists(receipt))
receipt = PrintService().generate_receipt(order, items, total)
check('чек A4 создан', os.path.exists(receipt))

print('\n=== Возврат ===')
cash_left, card_left = orders.refund_split(order)
check('доступно: 2000 наличными, 3400 на карту', (cash_left, card_left) == (2000, 3400))
ok, message = orders.refund_order(order.id, amount=1000, reason='тест', cash=2500)
check('наличными больше, чем дали, — нельзя', not ok and '2000' in message, message)
ok, message = orders.refund_order(order.id, amount=3500, reason='тест', cash=0)
check('на карту больше остатка — нельзя', not ok and '3400' in message, message)
ok, message = orders.refund_order(order.id, amount=1500, reason='часть', cash=500)
check('500 наличными + 1000 на карту', ok, message)
db.refresh(order)
check('из кассы ушло 500', cash.expected(shift) == 3000 + whole_total - 500,
      str(cash.expected(shift)))
check('учтено, сколько вернули наличными', order.refunded_cash == 500)
check('теперь доступно 1500 + 2400', orders.refund_split(order) == (1500, 2400),
      str(orders.refund_split(order)))
ok, message = orders.refund_order(whole.id, amount=100, reason='наличный наряд')
check('наличный наряд — как раньше, из кассы', ok and
      db.query(CashOrder).filter_by(work_order_id=whole.id).count() == 1, message)

print('\n=== Обмен ===')
push = SyncService(db).collect_push()
sent = {v['local_id']: v for v in push['visits']}
check('на сервер — способ и наличные', sent[order.id]['payment_method'] == 'mixed'
      and sent[order.id]['cash_amount'] == 2000)

db.close()
finish()
