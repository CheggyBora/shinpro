"""
Время смены считается верно и наряд нельзя оплатить дважды.

Раньше: время начала смены писала SQLite в UTC, а сравнивали его с
московским временем с часовым поясом — приложение падало при запуске
с открытой сменой, а свежая смена показывала "работает 3ч".
Оплата не проверяла статус наряда, и при сбое печати чека кассир мог
провести её повторно — зарплата начислялась дважды.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('tz_payment')

from datetime import datetime

from config import init_db, SessionLocal
from models import Service, SalaryTransaction
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService
from utils import get_moscow_time, as_naive

init_db()
db = SessionLocal()

shift_service = ShiftService(db)
emp_service = EmployeeService(db)
order_service = OrderService(db)
salary_service = SalaryService(db)

print('=== Время всегда московское ===')
# Раньше время бралось у компьютера, и на машине с другим поясом всё
# разъезжалось: наряд, смена и запись получали разное «сейчас».
# Теперь оно считается от всемирного, а всемирное везде одно
gap = (get_moscow_time() - datetime.utcnow()).total_seconds() / 3600
check('московское время опережает всемирное на три часа',
      2.9 < gap < 3.1, f'{gap:.2f} ч')
check('время без часового пояса — как оно лежит в базе',
      get_moscow_time().tzinfo is None)

print('\n=== Время смены ===')
shift = shift_service.open_shift()
check('время начала смены без часового пояса', shift.start_time.tzinfo is None,
      repr(shift.start_time))

try:
    duration = as_naive(get_moscow_time()) - as_naive(shift.start_time)
    check('вычитание времени не падает', True)
    check('свежая смена показывает около нуля часов',
          abs(duration.total_seconds() / 3600) < 0.05,
          f'{duration.total_seconds() / 3600:.4f} ч')
except TypeError as e:
    check('вычитание времени не падает', False, str(e))
    check('свежая смена показывает около нуля часов', False)

print('\n=== Оплата наряда ===')
emp_service.register_employee(1)
emp_service.start_shift(1)
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=400.0))
db.commit()
service = db.query(Service).first()

order = order_service.create_order('А123ВВ777', 'R16', 'car')
order_service.add_service_to_order(order.id, service.id)
total = order_service.calculate_total(order.id)

salary_service.process_payment(order.id, 'cash', total)
db.refresh(order)
check('наряд оплачен', order.status == 'paid')
check('начислена одна транзакция ЗП',
      db.query(SalaryTransaction).filter_by(work_order_id=order.id).count() == 1)

try:
    salary_service.process_payment(order.id, 'cash', total)
    check('повторная оплата отклонена', False, 'оплата прошла второй раз!')
except ValueError as e:
    check('повторная оплата отклонена', True, str(e))

check('зарплата не задвоилась',
      db.query(SalaryTransaction).filter_by(work_order_id=order.id).count() == 1)

print('\n=== Закрытие смены ===')
result = shift_service.close_shift(shift.id)
check('длительность закрытой смены около нуля',
      abs(result['duration_hours']) < 0.05, f"{result['duration_hours']:.4f} ч")

print('\n=== Все даты в одной шкале ===')
now = datetime.now()
db.refresh(order)
transaction = db.query(SalaryTransaction).first()
for label, value in [
    ('наряд: создан', order.created_at),
    ('наряд: оплачен', order.paid_at),
    ('смена: начата', shift.start_time),
    ('начисление ЗП', transaction.transaction_date),
]:
    delta = abs((now - as_naive(value)).total_seconds())
    check(f'{label} — местное время', delta < 120, f'расхождение {delta:.0f} сек')

db.close()
finish()
