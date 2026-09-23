"""
Имя сотрудника и разбор начислений за смену по нарядам.

Имя нужно там, где речь о деньгах человека: «Игорь — 18 400 ₽» читается,
а «№3 — 18 400 ₽» требует помнить номера. В нарядах и чеках сотрудник
остаётся номером — так он подписан в работе.

Разбор по нарядам показывает, из чего сложилась сумма: номер наряда,
машина, начислено. Один и тот же расчёт для программы цеха и дашборда,
иначе мастер увидит на телефоне одно, у приёмщика другое.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('employee_names')

from config import init_db, SessionLocal, add_missing_columns
from models import Service, Employee
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()

shift = ShiftService(db).open_shift()
employees = EmployeeService(db)
orders = OrderService(db)
salaries = SalaryService(db)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0,
               consumable_cost=0.0))
db.commit()
service_id = db.query(Service).first().id

print('=== Имя задаётся при создании и меняется потом ===')
igor = employees.register_employee(1, 'Игорь')
check('имя сохранено', igor.name == 'Игорь', str(igor.name))

noname = employees.register_employee(2)
check('без имени — пусто', noname.name is None, str(noname.name))
check('без имени показываем номер', noname.title == '№2', noname.title)
check('с именем показываем имя и номер', igor.title == 'Игорь (№1)', igor.title)

employees.set_name(2, '  Пётр  ')
check('имя подчищено от пробелов',
      db.query(Employee).filter_by(id=2).first().name == 'Пётр')

employees.set_name(2, '   ')
check('пустое имя убирает имя, а не пишет пробелы',
      db.query(Employee).filter_by(id=2).first().name is None)
employees.set_name(2, 'Пётр')

try:
    employees.set_name(99, 'Никто')
    check('несуществующему сотруднику имя не задать', False)
except ValueError:
    check('несуществующему сотруднику имя не задать', True)

print('\n=== Разбор начислений за смену по нарядам ===')
employees.start_shift(1)
employees.start_shift(2)


def pay(plate, employee_ids):
    order = orders.create_order(plate, 'R16', 'car')
    orders.add_service_to_order(order.id, service_id)
    order.employee_ids = employee_ids
    db.commit()
    salaries.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    return order


first = pay('А111АА77', '1')
second = pay('В222ВВ77', '1')
shared = pay('С333СС77', '1,2')

details = ShiftService(db).get_shift_salary_details(shift.id)

check('в разборе оба сотрудника', sorted(details.keys()) == [1, 2],
      str(sorted(details.keys())))

igor_rows = details[1]['orders']
check('у Игоря три наряда', len(igor_rows) == 3, str(len(igor_rows)))
check('в строке номер наряда', igor_rows[0]['order_id'] == first.id)
check('в строке номер машины', igor_rows[1]['license_plate'] == 'В222ВВ77',
      str(igor_rows[1]['license_plate']))

# 1000 без расходников: одному — 40%, вдвоём — по 20%
check('соло-наряд: 400', igor_rows[0]['amount'] == 400.0,
      str(igor_rows[0]['amount']))
check('наряд на двоих: 200', igor_rows[2]['amount'] == 200.0,
      str(igor_rows[2]['amount']))

check('итог сходится с суммой строк',
      details[1]['salary'] == sum(row['amount'] for row in igor_rows),
      str(details[1]['salary']))
check('итог Игоря 1000', details[1]['salary'] == 1000.0,
      str(details[1]['salary']))
check('у Петра только общий наряд',
      [row['order_id'] for row in details[2]['orders']] == [shared.id])

check('имя доехало до разбора', details[1]['employee'].title == 'Игорь (№1)',
      details[1]['employee'].title)

print('\n=== Короткий вид считает то же самое ===')
short = ShiftService(db).get_all_employees_shift_salary(shift.id)
check('суммы совпадают с подробным видом',
      all(short[emp_id]['salary'] == details[emp_id]['salary']
          for emp_id in details))

print('\n=== Закрытие смены отдаёт разбор ===')
result = ShiftService(db).close_shift(shift.id)
check('в итоге смены есть наряды по сотруднику',
      len(result['employees'][1]['orders']) == 3)
check('итог смены — сумма начислений',
      result['total_salary'] == 1000.0 + 200.0,
      str(result['total_salary']))

print('\n=== Колонка имени дописывается в старую базу ===')
from sqlalchemy import text
from config import engine

with engine.begin() as connection:
    connection.execute(text('ALTER TABLE employees DROP COLUMN name'))

add_missing_columns()

db.close()
db = SessionLocal()
check('старый сотрудник на месте и без имени',
      db.query(Employee).filter_by(id=1).first().name is None)

employees = EmployeeService(db)
employees.set_name(1, 'Игорь')
check('имя снова пишется', db.query(Employee).filter_by(id=1).first().name == 'Игорь')

finish()
