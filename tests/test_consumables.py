"""
Расходники вычитаются из суммы до расчёта зарплаты.

Механик получает процент с работы, а не с материалов. Себестоимость
запоминается снимком в момент добавления услуги в наряд, поэтому
подорожание закупки не меняет уже начисленные зарплаты.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('consumables')

from config import init_db, SessionLocal
from models import Service, SalaryTransaction, Employee
from services import OrderService, SalaryService, EmployeeService, ClientService
from services.shift_service import ShiftService
from services.statistics_service import StatisticsService

init_db()
db = SessionLocal()

ShiftService(db).open_shift()
emp_service = EmployeeService(db)
emp_service.register_employee(1)
emp_service.start_shift(1)

order_service = OrderService(db)
salary_service = SalaryService(db)

# Шиномонтаж без расходников, ремонт грибком — грибок стоит 80
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=400.0, consumable_cost=0.0))
db.add(Service(name='Ремонт грибком', vehicle_type='car', price_r16=500.0, consumable_cost=80.0))
db.commit()
services = {s.name: s for s in db.query(Service).all()}


def zp(order_id):
    return sum(t.amount for t in
               db.query(SalaryTransaction).filter_by(work_order_id=order_id).all())


print('=== Без расходников зарплата как раньше ===')
o1 = order_service.create_order('А111АА77', 'R16', 'car')
order_service.add_service_to_order(o1.id, services['Шиномонтаж'].id)
total = order_service.calculate_total(o1.id)
check('сумма наряда 400', total == 400.0, str(total))
check('расходников нет', order_service.calculate_consumables(o1.id) == 0.0)
check('база равна сумме', order_service.calculate_salary_base(o1.id) == 400.0)

salary_service.process_payment(o1.id, 'cash', total)
check('зарплата 40% от 400 = 160', zp(o1.id) == 160.0, str(zp(o1.id)))

print('\n=== С расходниками база уменьшается ===')
o2 = order_service.create_order('А222АА77', 'R16', 'car')
order_service.add_service_to_order(o2.id, services['Ремонт грибком'].id)
total = order_service.calculate_total(o2.id)
check('сумма наряда 500', total == 500.0, str(total))
check('расходники 80', order_service.calculate_consumables(o2.id) == 80.0)
check('база 500 - 80 = 420', order_service.calculate_salary_base(o2.id) == 420.0)

salary_service.process_payment(o2.id, 'cash', total)
check('зарплата 40% от 420 = 168', zp(o2.id) == 168.0, str(zp(o2.id)))
db.refresh(o2)
check('расходники сохранены в наряде', o2.consumables_amount == 80.0, str(o2.consumables_amount))
check('база сохранена в наряде', o2.salary_base == 420.0, str(o2.salary_base))

print('\n=== Расходники умножаются на количество ===')
o3 = order_service.create_order('А333АА77', 'R16', 'car')
item = order_service.add_service_to_order(o3.id, services['Ремонт грибком'].id)
order_service.update_item_full(item.id, 4, item.price, item.discount_percent)
check('расходники 80 x 4 = 320', order_service.calculate_consumables(o3.id) == 320.0,
      str(order_service.calculate_consumables(o3.id)))
check('база 2000 - 320 = 1680', order_service.calculate_salary_base(o3.id) == 1680.0,
      str(order_service.calculate_salary_base(o3.id)))

print('\n=== Скидка клиенту не удешевляет материалы ===')
o4 = order_service.create_order('А444АА77', 'R16', 'car')
order_service.add_service_to_order(o4.id, services['Ремонт грибком'].id)
order_service.update_general_discount(o4.id, 10)
total = order_service.calculate_total(o4.id)
check('сумма со скидкой 450', total == 450.0, str(total))
check('расходники по-прежнему 80', order_service.calculate_consumables(o4.id) == 80.0)
check('база 450 - 80 = 370', order_service.calculate_salary_base(o4.id) == 370.0,
      str(order_service.calculate_salary_base(o4.id)))

print('\n=== Себестоимость запоминается снимком ===')
o5 = order_service.create_order('А555АА77', 'R16', 'car')
order_service.add_service_to_order(o5.id, services['Ремонт грибком'].id)
before = order_service.calculate_consumables(o5.id)

# Закупка подорожала вдвое
services['Ремонт грибком'].consumable_cost = 160.0
db.commit()

check('старый наряд считает по прежней цене',
      order_service.calculate_consumables(o5.id) == before == 80.0,
      f'было {before}, стало {order_service.calculate_consumables(o5.id)}')

o6 = order_service.create_order('А666АА77', 'R16', 'car')
order_service.add_service_to_order(o6.id, services['Ремонт грибком'].id)
check('новый наряд считает по новой цене',
      order_service.calculate_consumables(o6.id) == 160.0,
      str(order_service.calculate_consumables(o6.id)))

print('\n=== База не уходит в минус ===')
services['Шиномонтаж'].consumable_cost = 10000.0
db.commit()
o7 = order_service.create_order('А777АА77', 'R16', 'car')
order_service.add_service_to_order(o7.id, services['Шиномонтаж'].id)
check('расходники дороже работы', order_service.calculate_consumables(o7.id) > order_service.calculate_total(o7.id))
check('база равна нулю, а не отрицательная',
      order_service.calculate_salary_base(o7.id) == 0.0,
      str(order_service.calculate_salary_base(o7.id)))
salary_service.process_payment(o7.id, 'cash', order_service.calculate_total(o7.id))
check('зарплата ноль, а не минус', zp(o7.id) == 0.0, str(zp(o7.id)))

print('\n=== Зарплата делится между сотрудниками от базы ===')
emp_service.register_employee(2)
emp_service.start_shift(2)
services['Ремонт грибком'].consumable_cost = 80.0
db.commit()
o8 = order_service.create_order('А888АА77', 'R16', 'car')
order_service.add_service_to_order(o8.id, services['Ремонт грибком'].id)
total = order_service.calculate_total(o8.id)
salary_service.process_payment(o8.id, 'cash', total)
transactions = db.query(SalaryTransaction).filter_by(work_order_id=o8.id).all()
check('начислено двоим', len(transactions) == 2, str(len(transactions)))
check('каждому по 20% от базы 420 = 84',
      all(t.amount == 84.0 for t in transactions), str([t.amount for t in transactions]))

print('\n=== В отчётах видны расходники и маржа ===')
from datetime import datetime, timedelta
stats = StatisticsService(db).get_sales_statistics(
    datetime.now() - timedelta(days=1), datetime.now() + timedelta(days=1))
check('расходники попали в отчёт', stats['total_consumables'] > 0,
      str(stats['total_consumables']))
check('зарплата попала в отчёт', stats['total_salary'] > 0, str(stats['total_salary']))
# Маржа — то, что осталось шиномонтажу после материалов И зарплаты мастеров
check('маржа = выручка минус расходники минус зарплата',
      round(stats['margin'], 2) == round(stats['total_revenue']
                                         - stats['total_consumables']
                                         - stats['total_salary'], 2),
      f"{stats['margin']} vs {stats['total_revenue']} - "
      f"{stats['total_consumables']} - {stats['total_salary']}")

db.close()
finish()
