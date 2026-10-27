"""
Рабочий день — это смена (решение владельца 27.10.2026), программа цеха.

Смена открыта в 18:00 1-го и закрыта в 03:00 2-го. Наряд, оплаченный в
01:00 2-го, — в «Отчётах» и зарплате за 1-е, а не за 2-е.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('workday_shop')

from datetime import date, datetime

from config import init_db, SessionLocal
from models import SalaryTransaction, Shift, WorkOrder
from services import OrderService, EmployeeService, workday
from services.settings_service import SettingsService
from services.statistics_service import StatisticsService

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()
EmployeeService(db).register_employee(1, name='Сергей')

evening = Shift(start_time=datetime(2026, 10, 1, 18, 0), end_time=datetime(2026, 10, 2, 3, 0),
                status='closed')
morning = Shift(start_time=datetime(2026, 10, 2, 9, 0), end_time=datetime(2026, 10, 2, 20, 0),
                status='closed')
db.add_all([evening, morning])
db.commit()

orders = OrderService(db)


def paid(plate, shift, at, amount):
    order = orders.create_order(plate, 'R16', 'car')
    order.shift_id = shift.id if shift else None
    order.status = 'paid'
    order.paid_at = at
    order.total_amount = amount
    db.add(SalaryTransaction(employee_id=1, work_order_id=order.id, amount=amount * 0.4,
                             transaction_date=at))
    db.commit()
    return order


paid('А111АА77', evening, datetime(2026, 10, 1, 19, 0), 1000)
paid('В222ВВ77', evening, datetime(2026, 10, 2, 1, 0), 2000)
paid('Е333ЕЕ77', morning, datetime(2026, 10, 2, 12, 0), 4000)
paid('К444КК77', None, datetime(2026, 10, 2, 0, 30), 300)

stats = StatisticsService(db)
D1 = datetime(2026, 10, 1)
D2 = datetime(2026, 10, 2, 23, 59, 59)

first = stats.get_orders_report(D1, datetime(2026, 10, 1, 23, 59, 59))
check('1-е — оба наряда вечерней смены, и ночной тоже',
      sorted(row['total'] for row in first) == [1000, 2000], str([row['total'] for row in first]))
second = stats.get_orders_report(datetime(2026, 10, 2), D2)
check('2-е — дневная смена и старая запись без смены',
      sorted(row['total'] for row in second) == [300, 4000], str([row['total'] for row in second]))

salary = EmployeeService(db).get_salary_report(1, D1, datetime(2026, 10, 1, 23, 59, 59))
check('зарплата за 1-е — по смене', round(sum(t.amount for t in salary)) == 1200,
      str([t.amount for t in salary]))

statement = __import__('services.payout_service', fromlist=['x']).PayoutService(db).statement(
    D1, datetime(2026, 10, 1, 23, 59, 59))
check('ведомость за 1-е — начислено по смене',
      statement and round(statement[0]['accrued']) == 1200, str(statement)[:200])

check('моментом ночью — день смены',
      workday.moment_day(db, datetime(2026, 10, 2, 2, 0)) == date(2026, 10, 1))
check('вне смен — календарный день',
      workday.moment_day(db, datetime(2026, 10, 2, 5, 0)) == date(2026, 10, 2))

db.add(Shift(start_time=datetime(2026, 10, 5, 18, 0), status='open'))
db.commit()
check('открыта смена с вечера 5-го — рабочий день 5-е', workday.work_day(db) == date(2026, 10, 5))

db.close()
finish()
