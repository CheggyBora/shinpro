"""
Товар в наряде: вентиль, грузик, грибок.

Раньше в прайсе были только работы, и расходник приходилось заводить
«услугой»: цену вписывать в двенадцать ячеек по диаметрам, хотя
вентиль стоит одинаково, а в отчётах он смешивался с работой.

Две вещи, которые тут легко сделать неправильно:

  · цена. У товара она одна, не по диаметру;
  · зарплата. Мастер вентиль не делал, он достал его с полки — процент
    с перепродажи это не зарплата за работу, а скидка себе в убыток.

Плюс снимки: позицию могут потом переделать из товара в работу, и
закрытые наряды вместе с начисленными зарплатами от этого меняться
не должны.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('goods')

_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, WorkOrderItem
from services import OrderService
from services.settings_service import SettingsService

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()
orders = OrderService(db)

# Работа: цена зависит от диаметра, мастеру идёт процент
mounting = Service(name='Шиномонтаж', vehicle_type='car',
                   price_r15=500, price_r17=700, consumable_cost=20)

# Товар: цена одна, себестоимость — закупка
valve = Service(name='Вентиль', vehicle_type='car',
                is_goods=True, flat_price=150, purchase_price=40, unit='шт')

# Услуга с единой ценой — так тоже бывает: мойка одного колеса
wash = Service(name='Мойка колеса', vehicle_type='car', flat_price=100)

db.add_all([mounting, valve, wash])
db.commit()

print('=== Цена товара не зависит от диаметра ===')
check('под R15 — сто пятьдесят', orders.price_for(valve, 'R15') == 150,
      str(orders.price_for(valve, 'R15')))
check('под R17 — те же сто пятьдесят', orders.price_for(valve, 'R17') == 150,
      str(orders.price_for(valve, 'R17')))

print()
print('=== У работы — зависит ===')
check('R15', orders.price_for(mounting, 'R15') == 500,
      str(orders.price_for(mounting, 'R15')))
check('R17', orders.price_for(mounting, 'R17') == 700,
      str(orders.price_for(mounting, 'R17')))

print()
print('=== Единая цена разрешена и работе ===')
check('мойка стоит одинаково', orders.price_for(wash, 'R20') == 100,
      str(orders.price_for(wash, 'R20')))

print()
print('=== Наряд: товар и работа рядом ===')
order = orders.create_order(license_plate='А123ВВ777', wheel_diameter='R17',
                            vehicle_type='car')
orders.add_service_to_order(order.id, mounting.id)
orders.add_service_to_order(order.id, valve.id)

items = {item.service.name: item for item in orders.get_order_items(order.id)}
check('работа взята по диаметру', items['Шиномонтаж'].price == 700,
      str(items['Шиномонтаж'].price))
check('товар — по единой цене', items['Вентиль'].price == 150,
      str(items['Вентиль'].price))
check('товар помечен товаром', items['Вентиль'].is_goods is True)
check('работа — не товар', items['Шиномонтаж'].is_goods is False)
check('у товара в себестоимости закупка',
      items['Вентиль'].consumable_cost == 40,
      str(items['Вентиль'].consumable_cost))
check('у работы — расходник',
      items['Шиномонтаж'].consumable_cost == 20,
      str(items['Шиномонтаж'].consumable_cost))

print()
print('=== Итог наряда считает всё ===')
check('700 + 150', orders.calculate_total(order.id) == 850,
      str(orders.calculate_total(order.id)))

print()
print('=== А зарплата — только работу ===')
# 700 за работу минус 20 расходников = 680. Вентиль не в счёт:
# ни ценой, ни закупкой
check('база зарплаты — 680', orders.calculate_salary_base(order.id) == 680,
      str(orders.calculate_salary_base(order.id)))

print()
print('=== Без товаров расчёт прежний ===')
plain = orders.create_order(license_plate='К900ОР99', wheel_diameter='R15',
                            vehicle_type='car')
orders.add_service_to_order(plain.id, mounting.id)
check('500 минус 20 расходников',
      orders.calculate_salary_base(plain.id) == 480,
      str(orders.calculate_salary_base(plain.id)))

print()
print('=== Несколько штук товара ===')
item = items['Вентиль']
orders.update_item_full(item.id, quantity=4, price=150, discount=0)
check('четыре вентиля в итоге', orders.calculate_total(order.id) == 1300,
      str(orders.calculate_total(order.id)))
check('а зарплата не выросла',
      orders.calculate_salary_base(order.id) == 680,
      str(orders.calculate_salary_base(order.id)))

print()
print('=== Переделали товар в работу — старый наряд не изменился ===')
valve.is_goods = False
db.commit()

again = {item.service.name: item for item in orders.get_order_items(order.id)}
check('позиция в наряде осталась товаром',
      again['Вентиль'].is_goods is True)
check('и зарплата та же',
      orders.calculate_salary_base(order.id) == 680,
      str(orders.calculate_salary_base(order.id)))

db.close()
finish()
