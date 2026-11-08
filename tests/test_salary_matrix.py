"""
Зарплата — все настройки разом (проверка 08.11.2026).

Ожидаемое здесь посчитано руками по правилам, а не взято из программы:
если правило и программа разойдутся, тест это покажет.

Люди: Иван — мастер (40% шиномонтаж, 10% магазин), Пётр — сезонный
съёмщик (40%, правка дисков ему не начисляется), Анна — мойка 30%,
Ольга — администратор (5% со всего наряда, 4% с магазина).
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('salary_matrix')
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction, WorkShift
from services import EmployeeService, OrderService, SalaryService, directions
from services.employee_role_service import EmployeeRoleService
from services.settings_service import SettingsService
from services.shift_service import ShiftService
from services.shop_service import ShopService

init_db()
db = SessionLocal()
settings = SettingsService(db)
db.add_all([Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000, consumable_cost=300),
            Service(name='Правка литого диска', vehicle_type='car', price_r16=1500),
            Service(name='Вентиль', vehicle_type='all', flat_price=250, is_goods=True,
                    purchase_price=90)])
db.commit()
MOUNT, RIM, VALVE = 1, 2, 3

roles = EmployeeRoleService(db)
by_title = {r.title: r for r in roles.roles()}
roles.set_excluded(by_title['Сезонный съёмщик'].id, ['Правка литого диска'])
IVAN, PETR, ANNA, OLGA = 1, 2, 3, 4
staff = EmployeeService(db)
for number, name, role in ((IVAN, 'Иван', 'Мастер'), (PETR, 'Пётр', 'Сезонный съёмщик'),
                           (ANNA, 'Анна', 'Мастер'), (OLGA, 'Ольга', 'Администратор')):
    staff.register_employee(number, name=name, role_id=by_title[role].id)
for e in db.query(Employee).all():
    e.salary_percent, e.wash_percent, e.shop_percent = 40, 30, 0
db.query(Employee).get(IVAN).shop_percent = 10
db.query(Employee).get(OLGA).admin_percent = 5
db.query(Employee).get(OLGA).shop_percent = 4
db.commit()
ShiftService(db).open_shift(open_posts=2)
for number in (IVAN, PETR, OLGA):
    staff.start_shift(number)

orders = OrderService(db)
salary = SalaryService(db)


def pay(order):
    salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    result = {}
    for t in db.query(SalaryTransaction).filter_by(work_order_id=order.id):
        result[t.employee_id] = round(result.get(t.employee_id, 0) + t.amount, 2)
    return {k: v for k, v in result.items() if v}


def tire_order(plate, *services):
    order = orders.create_order(plate, 'R16', 'car', create_client=False)
    for service in services:
        orders.add_service_to_order(order.id, service)
    return order


print('=== 1. Шиномонтаж: делят все на смене, база «минус расходники» ===')
order = tire_order('А001АА77', MOUNT, RIM, VALVE)
check('в мастерах наряда Иван и Пётр, администратора нет', order.employee_ids == '1,2', order.employee_ids)
got = pay(order)
# Шиномонтаж: (2000 − 300) × 40% ÷ 2 = 340 каждому. Правка: только Иван — 1500 × 40% = 600.
# Вентиль — товар: мастерам 0. Ольга: 5% × (2000 + 1500 + 250) = 187,5
check('Иван 940, Пётр 340, Ольга 187,5', got == {IVAN: 940.0, PETR: 340.0, OLGA: 187.5}, str(got))

print('\n=== 2. База шиномонтажа «от выручки» ===')
settings.set('salary_base_tire', 'revenue')
got = pay(tire_order('А002АА77', MOUNT, RIM))
# 2000 × 40% ÷ 2 = 400; правка Ивану 600; Ольга 5% × 3500 = 175
check('Иван 1000, Пётр 400, Ольга 175', got == {IVAN: 1000.0, PETR: 400.0, OLGA: 175.0}, str(got))
settings.set('salary_base_tire', 'minus')

print('\n=== 3. Администратор «за вычетом расходников» ===')
settings.set('salary_base_admin', 'minus')
got = pay(tire_order('А003АА77', MOUNT, VALVE))
# 5% × ((2000 − 300) + 250) = 97,5 — с товара вычитаются только расходники, закупка — нет
check('Ольга 97,5', got.get(OLGA) == 97.5, str(got))
settings.set('salary_base_admin', 'revenue')

print('\n=== 4. Скидка 10% ===')
order = tire_order('А004АА77', MOUNT)
orders.update_general_discount(order.id, 10)
got = pay(order)
# Строка 1800; база (1800 − 300) × 40% ÷ 2 = 300; Ольга 5% × 1800 = 90
check('скидка уменьшает базу: Иван и Пётр по 300, Ольга 90',
      got == {IVAN: 300.0, PETR: 300.0, OLGA: 90.0}, str(got))

print('\n=== 5. Мастеров выбирают в наряде ===')
directions.set_tire_assign(db, True)
order = tire_order('А005АА77', MOUNT)
check('сами не встали', not order.employee_ids)
orders.set_order_masters(order.id, [IVAN])
got = pay(order)
check('всё Ивану: 1700 × 40% = 680', got == {IVAN: 680.0, OLGA: 100.0}, str(got))
directions.set_tire_assign(db, False)

print('\n=== 6. Мойка + шиномонтаж + магазин, продавцу и администратору ===')
directions.set_enabled(db, True, True)
wash = db.query(Service).filter(Service.direction == 'wash',
                                Service.name.like('Мойка кузова%')).first()
wash.price_sedan, wash.consumable_cost = 1000, 100
db.commit()
staff.start_shift(ANNA)
directions.set_shop_on(db, True)
card = ShopService(db).save_card(name='Ароматизатор', price=150, purchase_price=50, quantity=10)
settings.set('shop_salary_to', 'both')
order = tire_order('А006АА77', MOUNT)
check('с мойкой мастера сами не встают — ни Анна, ни Ольга', not order.employee_ids)
orders.set_order_masters(order.id, [IVAN])
orders.add_direction(order.id, 'wash', wash_class='sedan')
orders.add_service_to_order(order.id, wash.id)
orders.assign_wash(order.id, ANNA)
orders.add_service_to_order(order.id, card.service_id, employee_id=IVAN)
got = pay(order)
# Иван: шиномонтаж 1700 × 40% = 680 + магазин 10% × 150 = 15 → 695
# Анна: мойка (1000 − 100) × 30% = 270
# Ольга: 5% × (2000 + 1000) = 150 + магазин 4% × 150 = 6 → 156
check('Иван 695, Анна 270, Ольга 156', got == {IVAN: 695.0, ANNA: 270.0, OLGA: 156.0}, str(got))
mixed = order

print('\n=== 7. Магазин «от наценки», бонус по карточке ===')
settings.set('shop_salary_base', 'margin')
sale = ShopService(db).create_sale([(card, 2)], seller_id=IVAN)
got = pay(sale)
# Наценка 2 × (150 − 50) = 200: Иван 10% = 20, Ольга 4% = 8. Со всего наряда у Ольги — 0: это магазин
check('Иван 20, Ольга 8', got == {IVAN: 20.0, OLGA: 8.0}, str(got))
ShopService(db).save_card(card, bonus=30)
got = pay(ShopService(db).create_sale([(card, 2)], seller_id=IVAN))
check('бонус 30 ₽ за штуку вместо процента: по 60', got == {IVAN: 60.0, OLGA: 60.0}, str(got))
settings.set('shop_salary_base', 'sale')

print('\n=== 8. Возврат половины ===')
paid = orders.calculate_total(mixed.id)
ok, _ = orders.refund_order(mixed.id, amount=paid / 2, reason='тест', cash=paid / 2)
left = {}
for t in db.query(SalaryTransaction).filter_by(work_order_id=mixed.id):
    left[t.employee_id] = round(left.get(t.employee_id, 0) + t.amount, 2)
check('у каждого осталась половина', ok and left == {IVAN: 347.5, ANNA: 135.0, OLGA: 78.0}, str(left))
ok, _ = orders.refund_order(mixed.id, reason='всё')
left = {}
for t in db.query(SalaryTransaction).filter_by(work_order_id=mixed.id):
    left[t.employee_id] = round(left.get(t.employee_id, 0) + t.amount, 2)
check('полный возврат — у всех 0', ok and all(v == 0 for v in left.values()), str(left))

print('\n=== 9. Гарантийная переделка ===')
first = tire_order('А009АА77', MOUNT, VALVE)
orders.set_order_masters(first.id, [IVAN])
pay(first)
redo = orders.create_warranty(first.id, 'бортировка')
redo = redo[0] if isinstance(redo, tuple) else redo
orders.set_order_masters(redo.id, [IVAN])
# Переделка копирует только услуги по 0 ₽; вентиль ставят заново — по цене
orders.add_service_to_order(redo.id, VALVE)
got = pay(redo)
# Услуги по 0 ₽ — мастеру 0; вентиль по цене — Ольге 5% × 250 = 12,5
check('мастеру 0, администратору с товара 12,5', got == {OLGA: 12.5}, str(got))

print('\n=== 10. Два администратора ===')
staff.register_employee(5, name='Ирина', role_id=by_title['Администратор'].id)
db.query(Employee).get(5).admin_percent = 5
db.commit()
staff.start_shift(5)
order = tire_order('А010АА77', MOUNT)
orders.set_order_masters(order.id, [IVAN])
got = pay(order)
check('пополам: Ольга и Ирина по 50', got.get(OLGA) == 50.0 and got.get(5) == 50.0, str(got))

db.close()
finish()
