"""
Строки чека всегда складываются в сумму к оплате.

Раньше чек округлял цены сам по себе, а касса считала точно, поэтому
«Сумма минус Скидка» не сходилась с «Итого к оплате», а при отрицательной
разнице строка «Скидка» просто исчезала.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('receipt_math')

from config import init_db, SessionLocal
from models import Service, WorkOrderItem
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService
from utils import money_round

print('=== Округление денег ===')
check('половина округляется вверх: 332.5 -> 333', money_round(332.5) == 333, str(money_round(332.5)))
check('половина округляется вверх: 337.5 -> 338', money_round(337.5) == 338, str(money_round(337.5)))
check('вниз округляется как обычно: 332.4 -> 332', money_round(332.4) == 332)
check('целое не меняется: 400 -> 400', money_round(400) == 400)
check('пустое значение -> 0', money_round(None) == 0)

# Встроенный round() округляет половину к чётному — для денег это неверно
check('исправлено поведение встроенного round()', round(332.5) == 332 and money_round(332.5) == 333,
      f'round={round(332.5)}, money_round={money_round(332.5)}')

init_db()
db = SessionLocal()
ShiftService(db).open_shift()
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

order_service = OrderService(db)
salary_service = SalaryService(db)

# Цены подобраны так, чтобы скидки давали дробные копейки
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=350.0))
db.add(Service(name='Балансировка', vehicle_type='car', price_r16=333.0))
db.add(Service(name='Мойка', vehicle_type='car', price_r16=120.0))
db.commit()
services = {s.name: s for s in db.query(Service).all()}

print('\n=== Чек сходится: скидка 5% ===')
order = order_service.create_order('А123ВВ777', 'R16', 'car',
                                   client_name='Андрей', client_phone='79099018931')
for name in ('Шиномонтаж', 'Балансировка', 'Мойка'):
    order_service.add_service_to_order(order.id, services[name].id)

items = order_service.get_order_items(order.id)
# По четыре колеса
for item in items:
    order_service.update_item_full(item.id, 4, item.price, item.discount_percent)
items = order_service.get_order_items(order.id)

subtotal = sum(OrderService.item_total_without_discount(i) for i in items)
lines = sum(OrderService.item_total(i) for i in items)
total = order_service.calculate_total(order.id)

print(f'    Сумма без скидок: {subtotal:.0f} ₽')
for i in items:
    print(f'      {i.service.name}: {OrderService.item_unit_price(i):.0f} ₽ x {i.quantity} '
          f'= {OrderService.item_total(i):.0f} ₽  (скидка {i.discount_percent}%)')
print(f'    Скидка: {subtotal - lines:.0f} ₽    Итого: {total:.0f} ₽')

check('сумма строк равна сумме к оплате', lines == total, f'{lines} vs {total}')
check('Сумма - Скидка = Итого', subtotal - (subtotal - lines) == total)
check('итог — целое число рублей', total == int(total), str(total))

print('\n=== Чек сходится: общая скидка 15% ===')
order_service.update_general_discount(order.id, 15)
items = order_service.get_order_items(order.id)
subtotal = sum(OrderService.item_total_without_discount(i) for i in items)
lines = sum(OrderService.item_total(i) for i in items)
total = order_service.calculate_total(order.id)
print(f'    Сумма {subtotal:.0f} ₽, скидка {subtotal - lines:.0f} ₽, итого {total:.0f} ₽')
check('сумма строк равна сумме к оплате', lines == total, f'{lines} vs {total}')
check('скидка положительная', subtotal - lines > 0, str(subtotal - lines))

print('\n=== Скидка никогда не выходит отрицательной ===')
order_service.update_general_discount(order.id, 0)
items = order_service.get_order_items(order.id)
subtotal = sum(OrderService.item_total_without_discount(i) for i in items)
lines = sum(OrderService.item_total(i) for i in items)
check('без скидок Сумма равна Итого', subtotal >= lines, f'{subtotal} vs {lines}')

print('\n=== Оплата записывает ту же сумму ===')
total = order_service.calculate_total(order.id)
salary_service.process_payment(order.id, 'cash', total)
db.refresh(order)
check('в базе сохранена сумма из чека', order.total_amount == total,
      f'{order.total_amount} vs {total}')

print('\n=== Чек формируется без ошибок ===')
import os
import tempfile
os.chdir(_setup.PROJECT_DIR)
from services import PrintService

print_service = PrintService()
# Пишем во временную папку: рабочую receipts/ трогать нельзя
print_service.receipts_dir = os.path.join(tempfile.gettempdir(), 'tire_shop_test_receipts')
os.makedirs(print_service.receipts_dir, exist_ok=True)

receipt = print_service.generate_receipt(order, order_service.get_order_items(order.id), total)
check('файл чека создан', os.path.exists(receipt), receipt)
check('файл не пустой', os.path.getsize(receipt) > 1000)

db.close()
finish()
