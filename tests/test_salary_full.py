"""
Полная проверка зарплаты, списания и кассы (правила владельца 13.11.2026).

Ожидаемое посчитано руками по правилам, а не взято из программы.

Правила:
  · только шиномонтаж — делят все на смене или исполнители наряда;
  · с мойкой — исполнители шиномонтажа и мойщики на наряд, любую строку
    можно отдать другим исполнителям;
  · товары шиномонтажа и мойки: база «от выручки» — входят, «минус
    расходники» — нет (у мастеров, мойщиков и администратора);
  · администратор — свой процент сверху; двое и больше — выбранный в
    наряде, на мойке — с поста, пополам не делят;
  · магазин — продавцу, если включено; администратору — если включено
    «с продаж», и тогда, продав сам, он второй раз не получает;
  · склад: материалы по расходу услуги и товары списываются при оплате,
    полный возврат возвращает; касса сходится.

Люди: 1 Иван — мастер 40%, магазин 10%; 2 Пётр — съёмщик 40% (без
правки); 3 Анна, 4 Мария — мойка 30%; 5 Семён — мастер 40%; 6 Ольга и
7 Ирина — администраторы 5%, магазин 4%.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('salary_full')
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction
from models.stock import GOODS, MATERIAL
from services import EmployeeService, OrderService, SalaryService, directions
from services.cash_service import CashService
from services.employee_role_service import EmployeeRoleService
from services.settings_service import SettingsService
from services.shift_service import ShiftService
from services.shop_service import ShopService
from services.stock_service import StockService
from services.wash_posts import WashPosts

init_db()
db = SessionLocal()
settings = SettingsService(db)
db.add_all([Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000, consumable_cost=300),
            Service(name='Правка литого диска', vehicle_type='car', price_r16=1500),
            Service(name='Вентиль', vehicle_type='all', flat_price=250, is_goods=True, purchase_price=90),
            Service(name='Балансировка', vehicle_type='car', price_r16=800)])
db.commit()
MOUNT, RIM, VALVE, BAL = 1, 2, 3, 4

roles = EmployeeRoleService(db)
by_title = {r.title: r for r in roles.roles()}
roles.set_excluded(by_title['Сезонный съёмщик'].id, ['Правка литого диска'])
IVAN, PETR, ANNA, MARIA, SEMEN, OLGA, IRINA = 1, 2, 3, 4, 5, 6, 7
staff = EmployeeService(db)
for number, name, role in ((IVAN, 'Иван', 'Мастер'), (PETR, 'Пётр', 'Сезонный съёмщик'),
                           (ANNA, 'Анна', 'Мастер'), (MARIA, 'Мария', 'Мастер'),
                           (SEMEN, 'Семён', 'Мастер')):
    staff.register_employee(number, name=name, role_id=by_title[role].id)
staff.register_employee(OLGA, name='Ольга', admin_percent=5)
staff.register_employee(IRINA, name='Ирина', admin_percent=5)
for e in db.query(Employee).all():
    e.salary_percent, e.wash_percent, e.shop_percent = 40, 30, 0
db.query(Employee).get(IVAN).shop_percent = 10
db.query(Employee).get(OLGA).shop_percent = 4
db.query(Employee).get(IRINA).shop_percent = 4
db.commit()
shift = ShiftService(db).open_shift(open_posts=2, cash_start=1000)
for number in (IVAN, PETR, OLGA):
    staff.start_shift(number)

orders = OrderService(db)
salary = SalaryService(db)
cash_paid = 0.0


def pay(order, method='cash', cash=None):
    global cash_paid
    total = orders.calculate_total(order.id)
    salary.process_payment(order.id, method, total, cash)
    cash_paid += total if method == 'cash' else (cash or 0)
    return accrued(order)


def accrued(order):
    result = {}
    for t in db.query(SalaryTransaction).filter_by(work_order_id=order.id):
        result[t.employee_id] = round(result.get(t.employee_id, 0) + t.amount, 2)
    return {k: v for k, v in result.items() if v}


def tire_order(plate, *services):
    order = orders.create_order(plate, 'R16', 'car', create_client=False)
    for service in services:
        orders.add_service_to_order(order.id, service)
    return order


def refused(order, word):
    try:
        salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
        return False
    except ValueError as e:
        db.rollback()
        return word in str(e)


print('=== А. Только шиномонтаж, делят все на смене ===')
got = pay(tire_order('А001АА77', MOUNT, RIM, VALVE))
# Шиномонтаж (2000 − 300) × 40% ÷ 2 = 340; правка — Ивану 600; вентиль при «минус» — никому.
# Ольга, база «вся сумма»: 5% × (2000 + 1500 + 250) = 187,5
check('база «минус»: Иван 940, Пётр 340, Ольга 187,5 (вентиль у админа входит)',
      got == {IVAN: 940.0, PETR: 340.0, OLGA: 187.5}, str(got))

settings.set('salary_base_tire', 'revenue')
got = pay(tire_order('А002АА77', MOUNT, RIM, VALVE))
# 2000 × 40% ÷ 2 = 400; правка 600; вентиль 250 × 40% ÷ 2 = 50 каждому (исключения — не для товара)
check('база «от выручки»: вентиль входит — Иван 1050, Пётр 450, Ольга 187,5',
      got == {IVAN: 1050.0, PETR: 450.0, OLGA: 187.5}, str(got))
settings.set('salary_base_tire', 'minus')

settings.set('salary_base_admin', 'minus')
got = pay(tire_order('А003АА77', MOUNT, RIM, VALVE))
# 5% × (1700 + 1500) = 160 — вентиль при «за вычетом расходников» не входит
check('администратор «за вычетом расходников»: Ольга 160', got.get(OLGA) == 160.0, str(got))
settings.set('salary_base_admin', 'revenue')

order = tire_order('А004АА77', MOUNT)
orders.update_general_discount(order.id, 10)
got = pay(order)
# Строка 1800: (1800 − 300) × 40% ÷ 2 = 300; Ольга 5% × 1800 = 90
check('скидка 10%: по 300, Ольга 90', got == {IVAN: 300.0, PETR: 300.0, OLGA: 90.0}, str(got))

print('\n=== Б. Исполнители в наряде, строку отдали другому ===')
directions.set_tire_assign(db, True)
order = tire_order('А005АА77', MOUNT, RIM, BAL)
check('сами исполнители не встают', not order.employee_ids)
check('без исполнителей не пробить', refused(order, 'сотрудник'))
orders.set_order_masters(order.id, [IVAN, PETR])
rim_line = next(i for i in orders.get_order_items(order.id) if i.service_id == RIM)
orders.set_item_executors(rim_line.id, [SEMEN])
got = pay(order)
# Шиномонтаж 1700 × 40% ÷ 2 = 340; балансировка 800 × 40% ÷ 2 = 160; правка — Семёну 1500 × 40% = 600
# Ольга 5% × (2000 + 1500 + 800) = 215
check('Иван 500, Пётр 500, Семён 600 (правку делал он), Ольга 215',
      got == {IVAN: 500.0, PETR: 500.0, SEMEN: 600.0, OLGA: 215.0}, str(got))

print('\n=== В. Мойка, двое администраторов, посты ===')
directions.set_enabled(db, True, True)
body = db.query(Service).filter(Service.direction == 'wash', Service.name.like('Мойка кузова%')).first()
salon = db.query(Service).filter(Service.direction == 'wash', Service.name == 'Уборка салона').first()
body.price_sedan, body.consumable_cost = 1000, 100
salon.price_sedan = 1200
polish = Service(name='Полироль', vehicle_type='all', flat_price=300, is_goods=True,
                 purchase_price=120, direction='wash')
db.add(polish)
db.commit()
for number in (ANNA, MARIA, SEMEN, IRINA):
    staff.start_shift(number)
WashPosts(db).set_post_staff(1, [ANNA, MARIA], IRINA)
check('пост 1 на смену: Анна, Мария, Ирина', WashPosts(db).post_staff(1) ==
      {'washers': [ANNA, MARIA], 'admin': IRINA}, str(WashPosts(db).post_staff(1)))

order = orders.create_order('В001ВВ77', 'R16', 'car', create_client=False,
                            directions=['tire', 'wash'], wash_class='sedan')
db.refresh(order)
check('наряд встал на пост 1 — мойщики с поста', order.wash_post_number == 1
      and orders.wash_masters(order) == [ANNA, MARIA], f'{order.wash_post_number} {order.wash_employee_ids}')
check('администратор мойки — с поста', salary.order_admins(order)['wash'].id == IRINA)
orders.set_order_masters(order.id, [IVAN])
for service in (MOUNT, body.id, salon.id, polish.id):
    orders.add_service_to_order(order.id, service)
salon_line = next(i for i in orders.get_order_items(order.id) if i.service_id == salon.id)
orders.set_item_executors(salon_line.id, [MARIA])
check('двое администраторов — шиномонтаж без выбора не пробить', refused(order, 'администратора'))
orders.set_order_admin(order.id, 'tire', OLGA)
got = pay(order)
# Иван: 1700 × 40% = 680. Мойка кузова (1000 − 100) × 30% ÷ 2 = 135 Анне и Марии;
# уборка салона — только Марии 1200 × 30% = 360; полироль при «минус» — мойщикам нет.
# Ольга (шиномонтаж): 5% × 2000 = 100. Ирина (мойка): 5% × (1000 + 1200 + 300) = 125
check('Иван 680, Анна 135, Мария 495, Ольга 100, Ирина 125 — пополам не делят',
      got == {IVAN: 680.0, ANNA: 135.0, MARIA: 495.0, OLGA: 100.0, IRINA: 125.0}, str(got))
mixed = order

settings.set('salary_base_wash', 'revenue')
order = orders.create_order('В002ВВ77', 'R16', 'car', create_client=False,
                            directions=['wash'], wash_class='sedan')
for service in (body.id, salon.id, polish.id):
    orders.add_service_to_order(order.id, service)
db.refresh(order)
check('первая машина уехала — вторая снова на посту 1, мойщики и администратор с поста',
      order.wash_post_number == 1 and orders.wash_masters(order) == [ANNA, MARIA]
      and salary.order_admins(order)['wash'].id == IRINA,
      f'{order.wash_post_number} {order.wash_employee_ids} {order.admin_ids}')
orders.set_wash_masters(order.id, [])
check('мойщиков убрали — не пробить', refused(order, 'кто делал'))
orders.set_wash_masters(order.id, [ANNA, MARIA])
got = pay(order)
# «от выручки»: кузов 1000 × 30% ÷ 2 = 150, салон 1200 × 30% ÷ 2 = 180, полироль 300 × 30% ÷ 2 = 45
# Анне и Марии по 375; Ирина 5% × 2500 = 125
check('мойка «от выручки»: Анна и Мария по 375, Ирина 125',
      got == {ANNA: 375.0, MARIA: 375.0, IRINA: 125.0}, str(got))
settings.set('salary_base_wash', 'minus')

print('\n=== Г. Магазин ===')
directions.set_shop_on(db, True)
directions.set_shop_pay_on(db, True)
card = ShopService(db).save_card(name='Ароматизатор', price=150, purchase_price=50, quantity=50)
got = pay(ShopService(db).create_sale([(card, 2)], seller_id=IVAN))
check('«с продаж» администратору выключено: Ивану 10% × 300 = 30, админам ничего',
      got == {IVAN: 30.0}, str(got))
directions.set_admin_shop_on(db, True)
sale = ShopService(db).create_sale([(card, 2)], seller_id=IVAN)
check('двое администраторов — продажу без выбора не пробить', refused(sale, 'администратора'))
orders.set_order_admin(sale.id, 'shop', OLGA)
got = pay(sale)
check('Иван 30, Ольга 5% × 300 = 15', got == {IVAN: 30.0, OLGA: 15.0}, str(got))
got = pay(ShopService(db).create_sale([(card, 2)], seller_id=OLGA, admin_id=OLGA))
check('продала сама Ольга — только её 5% = 15, без 4% продавца', got == {OLGA: 15.0}, str(got))
directions.set_admin_shop_on(db, False)
got = pay(ShopService(db).create_sale([(card, 2)], seller_id=OLGA))
check('«с продаж» выключено, продала Ольга — как продавец 4% = 12', got == {OLGA: 12.0}, str(got))
directions.set_admin_shop_on(db, True)
settings.set('shop_salary_base', 'margin')
got = pay(ShopService(db).create_sale([(card, 2)], seller_id=IVAN, admin_id=IRINA))
# Продавцу от наценки: 2 × (150 − 50) × 10% = 20; администратору — от суммы продажи 5% × 300 = 15
check('продавцу от наценки 20, Ирине от продажи 15', got == {IVAN: 20.0, IRINA: 15.0}, str(got))
settings.set('shop_salary_base', 'sale')

print('\n=== Д. Возврат ===')
paid = orders.calculate_total(mixed.id)
ok, _ = orders.refund_order(mixed.id, amount=paid / 2, reason='тест', cash=paid / 2)
left = accrued(mixed)
check('половина у каждого', ok and left == {IVAN: 340.0, ANNA: 67.5, MARIA: 247.5, OLGA: 50.0,
                                            IRINA: 62.5}, str(left))
refund_cash = paid / 2
ok, _ = orders.refund_order(mixed.id, reason='всё', cash=paid / 2)
refund_cash += paid / 2
check('полный возврат — у всех 0', ok and not accrued(mixed), str(accrued(mixed)))

print('\n=== Е. Склад: расход по услуге и товары ===')
stock = StockService(db)
stock.set_enabled(True)
weights = stock.save_item(name='Грузики', direction='tire', kind=MATERIAL, price=10, quantity=100)
valve_item = stock.save_item(name='Вентиль хром', direction='tire', kind=GOODS, price=250,
                             purchase_price=90, quantity=10)
stock.set_material(BAL, weights.id, 6)
order = tire_order('Е001ЕЕ77', BAL)
orders.set_order_masters(order.id, [IVAN])
orders.set_order_admin(order.id, 'tire', OLGA)
orders.add_service_to_order(order.id, valve_item.service_id)
bal_line = next(i for i in orders.get_order_items(order.id) if i.service_id == BAL)
check('расходник балансировки — по расходу: 6 × 10 = 60 ₽', bal_line.consumable_cost == 60,
      str(bal_line.consumable_cost))
got = pay(order)
# Иван: (800 − 60) × 40% = 296; вентиль при «минус» — нет. Ольга: 5% × (800 + 250) = 52,5
check('Иван 296, Ольга 52,5', got == {IVAN: 296.0, OLGA: 52.5}, str(got))
db.refresh(weights)
db.refresh(valve_item)
check('списано: грузиков 100 − 6 = 94, вентилей 10 − 1 = 9',
      weights.quantity == 94 and valve_item.quantity == 9, f'{weights.quantity} {valve_item.quantity}')
total = orders.calculate_total(order.id)
ok, _ = orders.refund_order(order.id, reason='вернули', cash=total)
refund_cash += total
db.refresh(weights)
db.refresh(valve_item)
check('полный возврат — склад вернулся: 100 и 10', ok and weights.quantity == 100
      and valve_item.quantity == 10, f'{weights.quantity} {valve_item.quantity}')
db.refresh(card)
check('магазин: продано 2 + 2 + 2 + 2 + 2 = 10 из 50 → 40', card.quantity == 40, str(card.quantity))

print('\n=== Ж. Раздельная оплата и касса ===')
order = tire_order('Ж001ЖЖ77', MOUNT)
orders.set_order_masters(order.id, [IVAN])
orders.set_order_admin(order.id, 'tire', OLGA)
got = pay(order, 'mixed', 500)
check('раздельная оплата не меняет зарплату: Иван 680, Ольга 100',
      got == {IVAN: 680.0, OLGA: 100.0}, str(got))
db.refresh(shift)
totals = CashService(db).totals(shift)
# Наличными пришло всё, что пробили наличными, + 500 из раздельной; ушло — возвраты
check(f'касса: пришло наличными {cash_paid:.2f}', round(totals['paid_cash'], 2) == round(cash_paid, 2),
      str(totals))
check(f'касса: ушло на возвраты {refund_cash:.2f}', round(totals['went'], 2) == round(refund_cash, 2),
      str(totals))
check('касса: должно быть = 1000 + пришло − ушло',
      round(totals['expected'], 2) == round(1000 + cash_paid - refund_cash, 2), str(totals))

db.close()
finish()
