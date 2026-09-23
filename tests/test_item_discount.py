"""
Скидка на отдельную услугу с ограничением.

Кассир может поставить скидку по конкретной позиции, но не больше
максимума, разрешённого для этой услуги. Выставленное вручную значение
общая скидка на наряд не перезаписывает: его выставил человек осознанно.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('item_discount')

from config import init_db, SessionLocal
from models import Service
from services import OrderService, EmployeeService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()
ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

order_service = OrderService(db)

# Балансировка со строгим лимитом, шиномонтаж без ограничений
db.add(Service(name='Балансировка', vehicle_type='car', price_r16=400.0,
               max_discount_percent=5))
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0,
               max_discount_percent=100))
db.add(Service(name='Правка литого диска', vehicle_type='car', price_r16=2000.0,
               max_discount_percent=20))
db.commit()
services = {s.name: s for s in db.query(Service).all()}


def item_by_service(order_id, name):
    return next(i for i in order_service.get_order_items(order_id)
                if i.service.name == name)


print('=== Умолчание не ломает прежнее поведение ===')
check('без ограничений по умолчанию 100',
      Service(name='х').max_discount_percent is None
      or services['Шиномонтаж'].max_discount_percent == 100)

order = order_service.create_order('А123ВВ777', 'R16', 'car')
order_service.add_service_to_order(order.id, services['Шиномонтаж'].id)
order_service.add_service_to_order(order.id, services['Балансировка'].id)

print('\n=== Ручная скидка в допустимом диапазоне ===')
item = item_by_service(order.id, 'Шиномонтаж')
order_service.set_item_discount(item.id, 12)
item = item_by_service(order.id, 'Шиномонтаж')
check('скидка 12% поставлена', item.discount_percent == 12, str(item.discount_percent))
check('позиция помечена как ручная', item.discount_manual is True)

print('\n=== Выше максимума не принимается ===')
balance = item_by_service(order.id, 'Балансировка')
try:
    order_service.set_item_discount(balance.id, 10)  # лимит 5
    check('скидка выше лимита отклонена', False, 'принята')
except ValueError as e:
    check('скидка выше лимита отклонена', True, str(e))

balance = item_by_service(order.id, 'Балансировка')
check('скидка не изменилась после отказа', balance.discount_percent == 0,
      str(balance.discount_percent))

order_service.set_item_discount(balance.id, 5)
check('скидка ровно по лимиту принимается',
      item_by_service(order.id, 'Балансировка').discount_percent == 5)

try:
    order_service.set_item_discount(balance.id, -3)
    check('отрицательная скидка отклонена', False, 'принята')
except ValueError as e:
    check('отрицательная скидка отклонена', True, str(e))

print('\n=== Общая скидка не затирает ручную ===')
order_service.update_general_discount(order.id, 15)

item = item_by_service(order.id, 'Шиномонтаж')
check('ручные 12% сохранились, а не стали 15%', item.discount_percent == 12,
      str(item.discount_percent))
balance = item_by_service(order.id, 'Балансировка')
check('ручные 5% сохранились', balance.discount_percent == 5, str(balance.discount_percent))

print('\n=== Общая скидка применяется к позициям без ручной ===')
order2 = order_service.create_order('К900ОР99', 'R16', 'car')
order_service.add_service_to_order(order2.id, services['Шиномонтаж'].id)
order_service.add_service_to_order(order2.id, services['Балансировка'].id)
order_service.update_general_discount(order2.id, 15)

check('на услуге без ограничений общая скидка 15%',
      item_by_service(order2.id, 'Шиномонтаж').discount_percent == 15,
      str(item_by_service(order2.id, 'Шиномонтаж').discount_percent))
check('на балансировке общая скидка урезана до лимита 5%',
      item_by_service(order2.id, 'Балансировка').discount_percent == 5,
      str(item_by_service(order2.id, 'Балансировка').discount_percent))

print('\n=== Скидка на диски тоже ограничена ===')
order3 = order_service.create_order('Т555ТТ77', 'R16', 'car')
order_service.add_service_to_order(order3.id, services['Правка литого диска'].id)
order_service.update_rim_discount(order3.id, 20)
check('скидка на диски 20% в пределах лимита',
      item_by_service(order3.id, 'Правка литого диска').discount_percent == 20)

services['Правка литого диска'].max_discount_percent = 10
db.commit()
order_service.update_rim_discount(order3.id, 20)
check('после снижения лимита скидка урезана до 10%',
      item_by_service(order3.id, 'Правка литого диска').discount_percent == 10,
      str(item_by_service(order3.id, 'Правка литого диска').discount_percent))

print('\n=== Новая услуга получает скидку с учётом лимита ===')
order4 = order_service.create_order('У777УУ77', 'R16', 'car')
order_service.update_general_discount(order4.id, 15)
order_service.add_service_to_order(order4.id, services['Балансировка'].id)
check('добавленная позиция сразу урезана до 5%',
      item_by_service(order4.id, 'Балансировка').discount_percent == 5,
      str(item_by_service(order4.id, 'Балансировка').discount_percent))

print('\n=== Возврат под общие скидки ===')
item = item_by_service(order.id, 'Шиномонтаж')
order_service.clear_item_discount_override(item.id)
order_service.update_general_discount(order.id, 15)
check('после снятия пометки применилась общая 15%',
      item_by_service(order.id, 'Шиномонтаж').discount_percent == 15,
      str(item_by_service(order.id, 'Шиномонтаж').discount_percent))

print('\n=== Скидка влияет на сумму ===')
order5 = order_service.create_order('Е111ЕЕ77', 'R16', 'car')
i5 = order_service.add_service_to_order(order5.id, services['Шиномонтаж'].id)
check('без скидки 1000', order_service.calculate_total(order5.id) == 1000.0)
order_service.set_item_discount(i5.id, 20)
check('со скидкой 20% — 800', order_service.calculate_total(order5.id) == 800.0,
      str(order_service.calculate_total(order5.id)))

db.close()
finish()
