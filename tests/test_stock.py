"""
Склад и база зарплаты (docs/stock.md).

Решения владельца от 26.10.2026:

  · продажи — только через наряд на машину;
  · зарплата у шиномонтажа и у мойки считается по-своему: «от выручки»
    (итог строки после скидок) или «минус расходники»; товары — никогда;
  · склад включается тумблером. Позиция — товар или материал, цена
    отпускная обязательна, закупка — нет. Расход материалов прописан у
    услуги на одно выполнение, его стоимость — по отпускной цене;
  · при оплате списываются материалы и проданные товары, при полном
    возврате — возвращаются. Остаток может уйти в минус: тогда один раз
    сообщение в Telegram тем, кому идёт сводка. «Мало» — только отметки.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('stock')
os.chdir(_setup.PROJECT_DIR)
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, SalaryTransaction, Employee
from models.stock import StockItem, StockMove, GOODS, MATERIAL
from models.calendar import TelegramOutbox
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.stock_service import StockService, StockError, fmt_qty

init_db()
db = SessionLocal()
tire = Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000, consumable_cost=100)
db.add(tire)
db.add(Service(name='Колпачок', vehicle_type='all', is_goods=True, flat_price=50, direction='tire'))
db.commit()

shifts = ShiftService(db)
employees = EmployeeService(db)
orders = OrderService(db)
salary = SalaryService(db)
settings = SettingsService(db)
stock = StockService(db)
shifts.open_shift(open_posts=2)
for n in (1, 2):
    employees.register_employee(n)
    employees.start_shift(n)
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()


def pay(order):
    salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    return sorted(t.amount for t in db.query(SalaryTransaction).filter(
        SalaryTransaction.work_order_id == order.id))


def stock_messages():
    return db.query(TelegramOutbox).filter(TelegramOutbox.kind == 'stock').count()


print('=== Склад выключен — всё как было ===')
check('по умолчанию склад выключен', not stock.enabled())
first = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
line = orders.add_service_to_order(first.id, tire.id)
check('расходник — сумма у услуги', line.consumable_cost == 100)
check('по умолчанию «минус расходники»: (2000 − 100) × 40% ÷ 2', pay(first) == [380, 380])
check('без склада ничего не списывается', db.query(StockMove).count() == 0)

print()
print('=== «От выручки» ===')
settings.set('salary_base_tire', 'revenue')
second = orders.create_order('В200ВВ77', 'R16', 'car', create_client=False)
orders.add_service_to_order(second.id, tire.id)
check('2000 × 40% ÷ 2, расходник не вычитается', pay(second) == [400, 400])
check('мойка своё: по умолчанию минус расходники',
      __import__('services.directions', fromlist=['x']).salary_base(db, 'wash') == 'minus')

print()
print('=== Позиции склада ===')
stock.set_enabled(True)
check('склад включён', stock.enabled())
try:
    stock.save_item(None, direction='tire', kind=MATERIAL, name='Грибок', price='')
    check('без цены — нельзя', False)
except StockError:
    check('без цены — нельзя', True)
try:
    stock.save_item(None, kind=MATERIAL, name='Грибок', price=50)
    check('без «Где» — нельзя', False)
except StockError:
    check('без «Где» — нельзя', True)
mushroom = stock.save_item(None, direction='tire', kind=MATERIAL, name='Грибок',
                           price='50', quantity='3', min_quantity='2')
check('закупка необязательна', mushroom.purchase_price is None)
valve = stock.save_item(None, direction='tire', kind=GOODS, name='Вентиль',
                        price=150, purchase_price=40, quantity=1)
valve_service = db.query(Service).filter(Service.id == valve.service_id).first()
check('товар появился в прайсе с одной ценой',
      valve_service.is_goods and valve_service.flat_price == 150 and valve_service.purchase_price == 40)
cap = stock.save_item(None, direction='tire', kind=GOODS, name='Колпачок', price=60, quantity=10)
check('товар из прайса не задваивается',
      db.query(Service).filter(Service.name == 'Колпачок').count() == 1
      and db.query(Service).filter(Service.name == 'Колпачок').first().flat_price == 60)

stock.set_material(tire.id, mushroom.id, '1,5')
check('расход услуги: 1,5 × 50 = 75 ₽', stock.recipe_cost(tire.id) == 75)

print()
print('=== Оплата списывает ===')
third = orders.create_order('С300СС77', 'R16', 'car', create_client=False)
line = orders.add_service_to_order(third.id, tire.id)
check('расходник строки — по расходу склада', line.consumable_cost == 75)
orders.add_service_to_order(third.id, valve_service.id)
orders.add_service_to_order(third.id, valve_service.id)
check('с товара зарплаты нет: 2000 × 40% ÷ 2', pay(third) == [400, 400])
db.refresh(mushroom)
db.refresh(valve)
check('грибок: 3 − 1,5 = 1,5 — мало', mushroom.quantity == 1.5 and mushroom.state == 'low')
check('вентиль: 1 − 2 = −1 — в минусе', valve.quantity == -1 and valve.state == 'neg')
check('ушло в минус — одно сообщение главному', stock_messages() == 1)
stock.write_off_order(third.id)
db.refresh(valve)
check('повторно не списывает', valve.quantity == -1)
check('позиции с проблемами — вверху, минус первым',
      [i.name for i in stock.items(problems_only=True)] == ['Вентиль', 'Грибок'])
check('счётчик в меню', stock.problems_count() == 2)

print()
print('=== «Минус расходники» по складу ===')
settings.set('salary_base_tire', 'minus')
fourth = orders.create_order('Е400ЕЕ77', 'R16', 'car', create_client=False)
orders.add_service_to_order(fourth.id, tire.id)
orders.add_service_to_order(fourth.id, valve_service.id)
check('минус расходники по складу: (2000 − 75) × 40% ÷ 2', pay(fourth) == [385, 385])
db.refresh(valve)
check('вентиль −2', valve.quantity == -2)
check('уже был в минусе — второй раз не пишем', stock_messages() == 1)

print()
print('=== Возврат и приход ===')
ok, _ = orders.refund_order(third.id, reason='вернули')
db.refresh(valve)
db.refresh(mushroom)
check('полный возврат вернул на склад', ok and valve.quantity == 0 and mushroom.quantity == 1.5)
stock.receive(mushroom, '10', purchase_price='30', note='Поставщик')
db.refresh(mushroom)
check('приход добавил и запомнил закупку', mushroom.quantity == 11.5 and mushroom.purchase_price == 30)
stock.correct(valve, '5')
db.refresh(valve)
check('пересчёт ставит факт', valve.quantity == 5)
check('история позиции', [m.reason for m in stock.history(valve)][:2] == ['correct', 'refund'])
check('остаток пишется по-русски', fmt_qty(-0.4, 'л') == '−0,4 л')

print()
print('=== Для дашборда ===')
snap = stock.snapshot()
check('снимок: склад включён и все позиции', snap['enabled'] and len(snap['items']) == 3)
before = StockService.fingerprint(snap)
stock.receive(valve, 1)
check('приход меняет отпечаток — уйдёт на сервер', StockService.fingerprint(stock.snapshot()) != before)

print()
print('=== Выключили склад ===')
stock.set_enabled(False)
fifth = orders.create_order('К500КК77', 'R16', 'car', create_client=False)
line = orders.add_service_to_order(fifth.id, tire.id)
check('расходник снова вручную', line.consumable_cost == 100)
moves = db.query(StockMove).count()
pay(fifth)
check('ничего не списано', db.query(StockMove).count() == moves)

db.close()
finish()
