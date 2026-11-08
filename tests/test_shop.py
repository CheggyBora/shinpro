"""
Магазин (решение владельца 08.11.2026).

  · карточки: категория, артикул, фото по желанию, бонус продавцу;
  · продажа без машины — пробивается как наряд, остаток списывается
    даже при выключенном складе;
  · товар магазина — в любой наряд, отдельной строкой «Магазин»;
  · с продаж — по настройке: никому, администратору, продавцу, обоим;
    от суммы или от наценки; бонус по карточке вместо процента;
  · «не давать продать», когда товара нет;
  · администратору магазин не считается дважды.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('shop')
_setup.silence_dialogs()

import os

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction
from services import EmployeeService, OrderService, SalaryService, directions
from services.employee_role_service import EmployeeRoleService
from services.salary_service import by_direction
from services.settings_service import SettingsService
from services.shift_service import ShiftService
from services.shop_service import ShopService, SALE_PLATE
from services.stock_service import StockError

init_db()
db = SessionLocal()
settings = SettingsService(db)
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
roles = EmployeeRoleService(db)
admin_role = next(r for r in roles.roles() if r.is_admin)
ShiftService(db).open_shift(open_posts=1)
staff = EmployeeService(db)
staff.register_employee(1)
staff.register_employee(2, role_id=admin_role.id)
for n in (1, 2):
    staff.start_shift(n)
db.query(Employee).get(1).shop_percent = 10
db.query(Employee).get(2).shop_percent = 4
db.query(Employee).get(2).admin_percent = 5
db.commit()

print('=== Включение ===')
check('по умолчанию выключен', not directions.shop_on(db))
directions.set_shop_on(db, True)
check('включается', directions.shop_on(db))

print('\n=== Карточки ===')
shop = ShopService(db)
scent = shop.save_card(name='Ароматизатор «Ёлочка»', category='Ароматизаторы', sku='EL-01',
                       price=150, purchase_price=50, quantity=10)
mats = shop.save_card(name='Коврики резиновые', category='Коврики', price=1900,
                      purchase_price=1200, quantity=2, bonus=100)
check('карточка — товар магазина в прайсе', scent.service_id and db.query(Service).get(
    scent.service_id).direction == 'shop')
check('поиск по артикулу', [c.name for c in shop.cards('el-0')] == ['Ароматизатор «Ёлочка»'])
check('фильтр по категории', [c.name for c in shop.cards(category='Коврики')] == ['Коврики резиновые'])
check('категории списком', shop.categories() == ['Ароматизаторы', 'Коврики'])
from PIL import Image
picture = os.path.join(shop.photo_folder(), 'source.png')
Image.new('RGB', (1200, 900), 'red').save(picture)
shop.save_card(scent, photo_from=picture)
check('фото уменьшено и лежит рядом с базой', shop.photo_path(scent) is not None
      and max(Image.open(shop.photo_path(scent)).size) <= 480)
try:
    shop.save_card(mats, photo_from=__file__)
    check('не картинка — понятная ошибка', False)
except StockError as e:
    check('не картинка — понятная ошибка', 'фото' in str(e))

print('\n=== Продажа без машины, с продаж никому ===')
salary = SalaryService(db)
orders = OrderService(db)
sale = shop.create_sale([(scent, 2)], seller_id=1)
check('продажа — на «машину» МАГАЗИН, без клиента', sale.car.license_plate == SALE_PLATE
      and sale.client_id is None and ShopService.is_sale(sale))
salary.process_payment(sale.id, 'card', orders.calculate_total(sale.id))
db.refresh(scent)
check('склад выключен — магазин всё равно списан', scent.quantity == 8, str(scent.quantity))
check('с продаж никому', not db.query(SalaryTransaction).filter_by(work_order_id=sale.id).count())

print('\n=== Продавцу и администратору ===')
settings.set('shop_salary_to', 'both')
sale = shop.create_sale([(scent, 2)], seller_id=1)
salary.process_payment(sale.id, 'cash', orders.calculate_total(sale.id))
pay = {t.employee_id: t.amount for t in db.query(SalaryTransaction).filter_by(work_order_id=sale.id)}
check('продавцу 10% от 300, администратору 4%', pay == {1: 30.0, 2: 12.0}, str(pay))
settings.set('shop_salary_base', 'margin')
sale = shop.create_sale([(scent, 1)], seller_id=1)
salary.process_payment(sale.id, 'cash', orders.calculate_total(sale.id))
pay = {t.employee_id: t.amount for t in db.query(SalaryTransaction).filter_by(work_order_id=sale.id)}
check('от наценки: 10% и 4% от (150 − 50)', pay == {1: 10.0, 2: 4.0}, str(pay))
settings.set('shop_salary_base', 'sale')
sale = shop.create_sale([(mats, 1)], seller_id=1)
salary.process_payment(sale.id, 'cash', orders.calculate_total(sale.id))
pay = {t.employee_id: t.amount for t in db.query(SalaryTransaction).filter_by(work_order_id=sale.id)}
check('бонус по карточке вместо процента — 100 ₽ каждому', pay == {1: 100.0, 2: 100.0}, str(pay))

print('\n=== Не давать продать, когда нет ===')
db.refresh(mats)
check('коврики остались: 1', mats.quantity == 1)
settings.set('stock_negative', 'block')
try:
    shop.create_sale([(mats, 2)], seller_id=1)
    check('больше, чем есть, — нельзя', False)
except StockError as e:
    check('больше, чем есть, — нельзя', 'на складе 1' in str(e), str(e))
settings.set('stock_negative', 'warn')
sale = shop.create_sale([(mats, 2)], seller_id=1)
check('«с предупреждением» — можно', sale is not None)

print('\n=== Товар магазина в наряде шиномонтажа ===')
settings.set('shop_salary_to', 'seller')
order = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
orders.add_service_to_order(order.id, 1)
line = orders.add_service_to_order(order.id, scent.service_id)
check('строка магазина, продавец — администратор на смене', line.direction == 'shop'
      and line.employee_id == 2, f'{line.direction} {line.employee_id}')
salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
rows = db.query(SalaryTransaction).filter_by(work_order_id=order.id).all()
admin_row = next(r for r in rows if r.employee_id == 2)
parts = dict(by_direction([admin_row]))[admin_row]
check('администратору: 5% шиномонтажа + 4% магазина, магазин не дважды',
      round(admin_row.amount, 2) == round(2000 * 0.05 + 150 * 0.04, 2), str(admin_row.amount))
check('в дашборд — по направлениям', parts == {'tire': 100.0, 'shop': 6.0}, str(parts))

print('\n=== Возврат продажи ===')
db.refresh(scent)
before = scent.quantity
sale = shop.create_sale([(scent, 3)], seller_id=1)
salary.process_payment(sale.id, 'cash', orders.calculate_total(sale.id))
ok, _ = orders.refund_order(sale.id, reason='вернули')
db.refresh(scent)
check('полный возврат — товар вернулся', ok and scent.quantity == before, f'{scent.quantity} {before}')

db.close()
finish()
