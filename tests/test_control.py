"""
Контроль в отчётах и выработка мастеров (решения владельца 13.11.2026).

  · контроль: скидка не меньше порога, удалённый наряд, возврат,
    расхождение кассы — в «Отчётах» и в сводке смены; скидка ниже
    порога — не замечание;
  · выработка: машин, выручка, средний чек, начислено, гарантийные
    переделки — по чьей работе.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('control')
_setup.silence_dialogs()

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Service, Employee
from services import EmployeeService, OrderService, SalaryService
from services import control_service
from services.shift_report_service import ShiftReportService
from services.shift_service import ShiftService
from services.statistics_service import StatisticsService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
staff = EmployeeService(db)
staff.register_employee(1, name='Иван')
staff.register_employee(2, name='Пётр')
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()
shift = ShiftService(db).open_shift(open_posts=2)
staff.start_shift(1)
orders = OrderService(db)
salary = SalaryService(db)


def paid(plate, discount=0, masters=(1,)):
    order = orders.create_order(plate, 'R16', 'car', create_client=False)
    orders.add_service_to_order(order.id, 1)
    orders.set_order_masters(order.id, list(masters))
    if discount:
        orders.update_general_discount(order.id, discount)
    salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    db.refresh(order)
    return order


small = paid('А001АА77', discount=10)
big = paid('А002АА77', discount=20)
# Оплаченный наряд не удаляют — только возврат (решение 26.10.2026): удаляют черновик
gone = orders.create_order('А003АА77', 'R16', 'car', create_client=False)
orders.add_service_to_order(gone.id, 1)
orders.delete_work_order(gone.id, 'ошибка')
refunded = paid('А004АА77')
orders.refund_order(refunded.id, amount=500, reason='клиент недоволен', cash=500)
shift.cash_diff, shift.cash_diff_reason = -300, 'не нашли'
db.commit()

start, end = datetime.now() - timedelta(hours=1), datetime.now() + timedelta(hours=1)
report = control_service.control(db, start, end)
print('=== Контроль ===')
check('скидка 20% — замечание, 10% — нет (порог 15%)',
      [r['order_id'] for r in report['discounts']] == [big.id], str(report['discounts']))
check('скидка в рублях: 2000 × 20% = 400', report['discounts'] and report['discounts'][0]['amount'] == 400)
check('удалённый наряд виден', [r['order_id'] for r in report['deleted']] == [gone.id], str(report['deleted']))
check('возврат 500 с причиной', report['refunds'] and report['refunds'][0]['amount'] == 500
      and report['refunds'][0]['reason'] == 'клиент недоволен', str(report['refunds']))
check('касса: недостача 300', report['cash'] and report['cash'][0]['diff'] == -300, str(report['cash']))
text = ShiftReportService(db).format_summary(ShiftReportService(db).build_summary(shift))
check('в сводке смены — блок «Контроль»', '<b>Контроль</b>' in text and 'скидка 20%' in text
      and 'недостача 300' in text and 'возврат' in text, text[-400:])
from services.settings_service import SettingsService
SettingsService(db).set(control_service.THRESHOLD_KEY, '5')
check('порог 5% — обе скидки', len(control_service.control(db, start, end)['discounts']) == 2)

print('\n=== Выработка мастеров ===')
redo = orders.create_warranty(small.id, 'бортировка')
redo = redo[0] if isinstance(redo, tuple) else redo
orders.set_order_masters(redo.id, [2])
salary.process_payment(redo.id, 'cash', orders.calculate_total(redo.id))
rows = {r['employee_id']: r for r in StatisticsService(db).get_masters_report(start, end)}
ivan = rows.get(1, {})
check('Иван по имени', ivan.get('name') == 'Иван (№1)', str(ivan))
check('у Ивана гарантийная переделка — по его работе, у Петра нет',
      ivan.get('warranty') == 1 and rows.get(2, {}).get('warranty', 0) == 0, str(rows))
check('средний чек = выручка ÷ машин', ivan.get('orders') and
      abs(ivan['average_check'] - ivan['revenue'] / ivan['orders']) < 0.01, str(ivan))

db.close()
finish()
