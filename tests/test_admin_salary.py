"""
Зарплата администратора (решение владельца 08.11.2026).

  · администратор — категория; шиномонтаж он не делит и в мастера
    наряда сам не попадает;
  · свой процент со всего наряда — шиномонтаж, мойка, товары — сверху,
    мастерам и мойщикам не меньше;
  · от чего — настройка: вся сумма или без расходников;
  · двое на смене — делят поровну; возврат откатывает и его долю;
  · с мойкой мастеров шиномонтажа выбирают в наряде всегда.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('admin_salary')
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction, WorkShift
from services import EmployeeService, OrderService, SalaryService, directions
from services.employee_role_service import EmployeeRoleService
from services.salary_service import by_direction
from services.settings_service import SettingsService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=4000, consumable_cost=300))
db.commit()
roles = EmployeeRoleService(db)
admin_role = next(r for r in roles.roles() if r.is_admin)
master_role = next(r for r in roles.roles() if r.title == 'Мастер')

ShiftService(db).open_shift(open_posts=2)
staff = EmployeeService(db)
for n in (1, 2, 3, 4):
    staff.register_employee(n, role_id=admin_role.id if n == 4 else master_role.id)
    staff.start_shift(n)
for e in db.query(Employee).all():
    e.salary_percent, e.wash_percent = 40, 30
db.query(Employee).get(4).admin_percent = 5
db.commit()

orders = OrderService(db)
salary = SalaryService(db)


def paid_order(plate, masters=None, washer=None):
    order = orders.create_order(plate, 'R16', 'car', create_client=False)
    orders.add_service_to_order(order.id, 1)
    if washer is not None:
        orders.add_direction(order.id, 'wash', wash_class='sedan')
        body = db.query(Service).filter(Service.direction == 'wash',
                                        Service.name.like('Мойка кузова%')).first()
        orders.add_service_to_order(order.id, body.id)
        orders.assign_wash(order.id, washer)
    if masters is not None:
        orders.set_order_masters(order.id, masters)
    salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    db.refresh(order)
    return order


def accrued(order):
    result = {}
    for row in db.query(SalaryTransaction).filter_by(work_order_id=order.id):
        result[row.employee_id] = round(result.get(row.employee_id, 0) + row.amount, 2)
    return result


print('=== Без мойки: администратор шиномонтаж не делит ===')
order = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
check('в мастерах наряда — все со смены, кроме администратора',
      order.employee_ids == '1,2,3', str(order.employee_ids))
orders.add_service_to_order(order.id, 1)
salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
money = accrued(order)
check('мастера — как без администратора: 40% × 3 700 / 3', money[1] == round(3700 * 0.4 / 3, 2),
      str(money))
check('администратору — 5% со всей суммы', money[4] == 200.0, str(money))

print('\n=== От суммы без расходников ===')
SettingsService(db).set('salary_base_admin', 'minus')
order = paid_order('В200ВВ77')
check('5% × (4 000 − 300)', accrued(order)[4] == 185.0, str(accrued(order)))
SettingsService(db).set('salary_base_admin', 'revenue')

print('\n=== С мойкой: пример владельца ===')
directions.set_enabled(db, True, True)
body = db.query(Service).filter(Service.direction == 'wash',
                                Service.name.like('Мойка кузова%')).first()
body.price_sedan = 1500
db.commit()
check('с мойкой мастеров выбирают в наряде', directions.tire_assign(db))
fresh = orders.create_order('С300СС77', 'R16', 'car', create_client=False)
check('мастера сами не встают — ни мойщик, ни администратор', not fresh.employee_ids)
order = paid_order('Е400ЕЕ77', masters=[1, 2], washer=3)
money = accrued(order)
check('Иван и Пётр — по 740', money[1] == 740.0 and money[2] == 740.0, str(money))
check('Анна — 30% мойки = 450', money[3] == 450.0, str(money))
check('Ольга — 5% × 5 500 = 275', money[4] == 275.0, str(money))
admin_row = db.query(SalaryTransaction).filter_by(work_order_id=order.id, employee_id=4).first()
parts = dict(by_direction([admin_row]))[admin_row]
check('доля администратора делится по направлениям', parts == {'wash': 75.0, 'tire': 200.0},
      str(parts))

print('\n=== Двое администраторов — процент выбранному (решение 13.11.2026) ===')
staff.register_employee(5, role_id=admin_role.id)
staff.start_shift(5)
db.query(Employee).get(5).admin_percent = 5
db.commit()
fresh = orders.create_order('К500КК77', 'R16', 'car', create_client=False)
orders.add_service_to_order(fresh.id, 1)
orders.set_order_masters(fresh.id, [1])
try:
    salary.process_payment(fresh.id, 'cash', orders.calculate_total(fresh.id))
    check('не выбран — пробить нельзя', False)
except ValueError as e:
    check('не выбран — пробить нельзя', 'администратора' in str(e), str(e))
db.rollback()
orders.set_order_admin(fresh.id, 'tire', 4)
salary.process_payment(fresh.id, 'cash', orders.calculate_total(fresh.id))
order = fresh
money = accrued(order)
check('выбранному — весь 5%, второму ничего', money.get(4) == 200.0 and not money.get(5), str(money))

print('\n=== Возврат ===')
ok, message = orders.refund_order(order.id, reason='тест')
check('после полного возврата у администратора 0', ok and accrued(order)[4] == 0, str(accrued(order)))

print('\n=== Ставка ===')
check('ставка администратора по умолчанию — 0',
      db.query(Employee).get(1).admin_percent == 0)
staff.update_salary_percent(4, 7, '0000', 'admin')
check('ставку администратора меняют отдельно', db.query(Employee).get(4).admin_percent == 7
      and db.query(Employee).get(4).salary_percent == 40)

db.close()
finish()
