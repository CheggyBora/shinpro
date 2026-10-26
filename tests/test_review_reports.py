"""
Отчёты сходятся (решения владельца 26.10.2026):

  · сводка смены: «Выручка / Возвраты / Итого» — возвраты, проведённые в
    смену, вычитаются, как в «Отчётах»;
  · отчёт по мастерам: выручка наряда делится между мастерами так же,
    как зарплата, а не пишется каждому целиком.
"""
import _setup
from _setup import use_temp_db, check, finish

import os
from datetime import timedelta

use_temp_db('review_reports')
os.chdir(_setup.PROJECT_DIR)
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.shift_report_service import ShiftReportService
from services.statistics_service import StatisticsService
from utils import get_moscow_time, as_naive

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=4000))
db.commit()
shift = ShiftService(db).open_shift(cash_start=0)
for n in (1, 2):
    EmployeeService(db).register_employee(n)
    EmployeeService(db).start_shift(n)
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()
orders = OrderService(db)
order = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
orders.add_service_to_order(order.id, 1)
SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))

now = as_naive(get_moscow_time())
period = (now - timedelta(days=1), now + timedelta(days=1))
masters = StatisticsService(db).get_masters_report(*period)
check('выручка поделена: по 2000 каждому', sorted(m['revenue'] for m in masters) == [2000, 2000],
      str([m['revenue'] for m in masters]))
check('в сумме — сам наряд', round(sum(m['revenue'] for m in masters)) == 4000)

orders.refund_order(order.id, amount=1000, reason='скидка')
report = ShiftReportService(db)
summary = report.build_summary(shift)
check('возврат вычтен: итого 3000', summary['refunds'] == 1000 and summary['net_revenue'] == 3000,
      str((summary['refunds'], summary['net_revenue'])))
text = report.format_summary(summary)
check('в сводке три строки', 'Выручка: <b>4000' in text and 'Возвраты: −1000' in text
      and 'Итого: <b>3000' in text, text[:400])
masters = StatisticsService(db).get_masters_report(*period)
check('у мастеров — тоже за вычетом возврата', round(sum(m['revenue'] for m in masters)) == 3000,
      str([m['revenue'] for m in masters]))

db.close()
finish()
