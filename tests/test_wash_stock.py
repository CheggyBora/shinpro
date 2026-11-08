"""
Мойка от прайса до склада — весь путь (проверка 08.11.2026).

  · услугу мойки добавляют в прайс, цену ставят по классу машины;
  · расходник — суммой вручную или рецептом со склада мойки;
  · товар мойки заводится в склад и сам встаёт в прайс мойки;
  · в наряде мойки услуга и товар, расходник — снимком в строке;
  · оплатили — материалы и товар списаны со склада мойки, зарплата
    мойщика — от суммы без расходников;
  · полный возврат — списанное вернулось.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('wash_stock')
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction
from models.stock import GOODS, MATERIAL
from services import EmployeeService, OrderService, SalaryService, directions
from services.price_list_service import PriceListService
from services.shift_service import ShiftService
from services.stock_service import StockService

init_db()
db = SessionLocal()
directions.set_enabled(db, True, True)
ShiftService(db).open_shift(open_posts=1)
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)
db.query(Employee).get(1).wash_percent = 30
db.commit()

print('=== Прайс мойки ===')
prices = PriceListService(db)
manual = prices.add_service('Полировка фар', direction='wash', consumable_cost=150)[0]
manual.price_sedan = 1000
recipe = prices.add_service('Озонирование салона', direction='wash')[0]
recipe.price_sedan = 3000
db.commit()
check('услуги мойки добавляются', manual.direction == 'wash' and recipe.direction == 'wash')

print('\n=== Склад мойки ===')
stock = StockService(db)
stock.set_enabled(True)
shampoo = stock.save_item(None, direction='wash', kind=MATERIAL, name='Химия для салона',
                          unit='л', price=400, quantity=10)
stock.set_material(recipe.id, shampoo.id, 1.5)
check('расход по рецепту: 1,5 л × 400', stock.recipe_cost(recipe.id) == 600.0)
scent = stock.save_item(None, direction='wash', kind=GOODS, name='Ароматизатор', price=300,
                        purchase_price=120, quantity=5)
goods = db.query(Service).filter(Service.name == 'Ароматизатор').first()
check('товар мойки сам встал в прайс мойки', goods is not None and goods.direction == 'wash'
      and goods.is_goods)
check('склад мойки отдельно от шиномонтажа',
      {i.name for i in stock.items('wash')} == {'Химия для салона', 'Ароматизатор'}
      and not stock.items('tire'))

print('\n=== Наряд мойки ===')
orders = OrderService(db)
order = orders.create_order('К100КК77', '', 'car', create_client=False, directions=['wash'],
                            wash_class='sedan')
line_manual = orders.add_service_to_order(order.id, manual.id)
line_recipe = orders.add_service_to_order(order.id, recipe.id)
line_goods = orders.add_service_to_order(order.id, goods.id)
check('цены по классу «седан» и товар', (line_manual.price, line_recipe.price, line_goods.price)
      == (1000, 3000, 300), str((line_manual.price, line_recipe.price, line_goods.price)))
check('расходник вручную — 150, по рецепту — 600',
      line_manual.consumable_cost == 150 and line_recipe.consumable_cost == 600,
      str((line_manual.consumable_cost, line_recipe.consumable_cost)))
orders.assign_wash(order.id, 1)
SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))

db.refresh(shampoo)
db.refresh(scent)
check('химия списана: 10 − 1,5', shampoo.quantity == 8.5, str(shampoo.quantity))
check('ароматизатор списан: 5 − 1', scent.quantity == 4, str(scent.quantity))
pay = sum(t.amount for t in db.query(SalaryTransaction).filter_by(work_order_id=order.id))
check('мойщику 30% от (1000 − 150) + (3000 − 600), с товара — ничего',
      round(pay, 2) == round(0.3 * (850 + 2400), 2), str(pay))

print('\n=== Полный возврат ===')
ok, message = orders.refund_order(order.id, reason='тест')
db.refresh(shampoo)
db.refresh(scent)
check('списанное вернулось', ok and shampoo.quantity == 10 and scent.quantity == 5,
      f'{shampoo.quantity} {scent.quantity}')

db.close()
finish()
