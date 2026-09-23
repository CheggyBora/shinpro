"""
Возврат, сторно и гарантийная переделка.

Возврат — это не удаление наряда: работа выполнялась, и в истории
это должно остаться видно. Из выручки уходит только возвращённая сумма,
а начисления зарплаты откатываются соразмерно.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('refund')

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Service, SalaryTransaction, AuditLog
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService
from services.statistics_service import StatisticsService

init_db()
db = SessionLocal()

ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.commit()
service = db.query(Service).first()

order_service = OrderService(db)
stats = StatisticsService(db)
PERIOD = (datetime.now() - timedelta(days=1), datetime.now() + timedelta(days=1))


def paid_order(plate):
    order = order_service.create_order(plate, 'R16', 'car')
    order_service.add_service_to_order(order.id, service.id)
    SalaryService(db).process_payment(order.id, 'cash', order_service.calculate_total(order.id))
    return order


def salary_of(order_id):
    return round(sum(t.amount for t in db.query(SalaryTransaction)
                     .filter_by(work_order_id=order_id).all()), 2)


print('=== Полный возврат ===')
order = paid_order('А123ВВ777')
check('начислено 400 (40% от 1000)', salary_of(order.id) == 400.0, str(salary_of(order.id)))

ok, message = order_service.refund_order(order.id, reason='клиент недоволен')
check('возврат проведён', ok, message)
db.refresh(order)
check('сумма возврата 1000', order.refunded_amount == 1000.0, str(order.refunded_amount))
check('дата возврата проставлена', order.refunded_at is not None)
check('причина сохранена', order.refund_reason == 'клиент недоволен')
check('наряд НЕ удалён', order.is_deleted is False)
check('наряд остался оплаченным', order.status == 'paid')
check('зарплата откачена полностью', salary_of(order.id) == 0.0, str(salary_of(order.id)))

print('\n=== Повторный возврат отклоняется ===')
ok, message = order_service.refund_order(order.id, reason='ещё раз')
check('второй раз вернуть нельзя', ok is False, message)

print('\n=== Частичный возврат ===')
order2 = paid_order('К900ОР99')
ok, message = order_service.refund_order(order2.id, amount=250, reason='вернули одну услугу')
check('частичный возврат проведён', ok, message)
db.refresh(order2)
check('возвращено 250', order2.refunded_amount == 250.0, str(order2.refunded_amount))
check('зарплата уменьшилась на четверть: 400 -> 300',
      salary_of(order2.id) == 300.0, str(salary_of(order2.id)))

ok, message = order_service.refund_order(order2.id, amount=750, reason='вернули остальное')
check('остаток вернуть можно', ok, message)
db.refresh(order2)
check('возвращено всё', order2.refunded_amount == 1000.0, str(order2.refunded_amount))
check('зарплата обнулилась', salary_of(order2.id) == 0.0, str(salary_of(order2.id)))

print('\n=== Проверки суммы ===')
order3 = paid_order('М777ММ199')
ok, message = order_service.refund_order(order3.id, amount=5000, reason='слишком много')
check('сумма больше оплаченной отклонена', ok is False, message)
ok, message = order_service.refund_order(order3.id, amount=0, reason='ноль')
check('нулевая сумма отклонена', ok is False, message)
ok, message = order_service.refund_order(order3.id, amount=-100, reason='минус')
check('отрицательная сумма отклонена', ok is False, message)

print('\n=== Сторно ===')
order4 = paid_order('Т555ТТ77')
ok, message = order_service.refund_order(order4.id, reason='пробили по ошибке',
                                         refund_type=OrderService.REVERSAL)
check('сторно проведено', ok, message)
db.refresh(order4)
check('тип операции сохранён', order4.refund_type == OrderService.REVERSAL)

print('\n=== Всё записано в журнал ===')
entries = db.query(AuditLog).filter(AuditLog.action == 'order.refund').all()
check('операции возврата в журнале', len(entries) == 4, str(len(entries)))
check('в записи видна причина',
      any('клиент недоволен' in (e.description or '') for e in entries))

print('\n=== Гарантийная переделка ===')
warranty = paid_order('Н555НН50')
order_service.set_warranty(warranty.id, True, reason='повторная балансировка')
db.refresh(warranty)
check('отметка проставлена', warranty.is_warranty is True)

warranty_log = db.query(AuditLog).filter(AuditLog.action == 'order.warranty').all()
check('отметка записана в журнал', len(warranty_log) == 1)

order_service.set_warranty(warranty.id, False)
db.refresh(warranty)
check('отметку можно снять', warranty.is_warranty is False)
order_service.set_warranty(warranty.id, True)

print('\n=== Отчёты учитывают возвраты ===')
summary = stats.get_sales_statistics(*PERIOD)
check('возвраты посчитаны', summary['total_refunds'] == 3000.0,
      str(summary['total_refunds']))
check('гарантийных нарядов 1', summary['warranty_count'] == 1,
      str(summary['warranty_count']))

# Пять нарядов по 1000, из них возвращено 3000
check('выручка за вычетом возвратов 2000', summary['total_revenue'] == 2000.0,
      str(summary['total_revenue']))

print('\n=== Средний чек не искажён ===')
# Платными остались: order3 (1000), warranty исключён, полностью
# возвращённые исключены
check('средний чек считается по платным нарядам',
      summary['average_check'] == 1000.0, str(summary['average_check']))

print('\n=== Отчёт по нарядам показывает возврат ===')
report = stats.get_orders_report(*PERIOD)
refunded = next(r for r in report if r['id'] == order.id)
check('видна возвращённая сумма', refunded['refunded'] == 1000.0)
check('к зачёту ноль', refunded['net'] == 0.0, str(refunded['net']))
check('причина доступна', refunded['refund_reason'] == 'клиент недоволен')

warranty_row = next(r for r in report if r['id'] == warranty.id)
check('гарантийный наряд помечен', warranty_row['is_warranty'] is True)

db.close()
finish()
