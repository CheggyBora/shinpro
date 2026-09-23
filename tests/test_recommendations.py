"""
Рекомендации мастера: попадают на чек и собираются в историю клиента.

Раньше мастер их записывал, а клиент никогда не видел — текст оставался
только внутри программы.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('recommendations')

import os
import tempfile

from config import init_db, SessionLocal
from models import Service
from services import OrderService, SalaryService, EmployeeService, ClientService, PrintService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()

ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.commit()
service = db.query(Service).first()

order_service = OrderService(db)
client_service = ClientService(db)

RECOMMENDATION = ('Через 5000 км заменить передние колодки. '
                  'Правое переднее колесо биение — рекомендуем балансировку.')


def paid_order(plate, recommendation=None, **kwargs):
    order = order_service.create_order(plate, 'R16', 'car', **kwargs)
    order_service.add_service_to_order(order.id, service.id)
    if recommendation:
        order.recommendations = recommendation
        db.commit()
    SalaryService(db).process_payment(order.id, 'cash', order_service.calculate_total(order.id))
    return order


print('=== Рекомендация сохраняется в наряде ===')
order = paid_order('А123ВВ777', RECOMMENDATION,
                   client_name='Андрей', client_phone='79099018931')
db.refresh(order)
check('текст сохранён', order.recommendations == RECOMMENDATION)

print('\n=== Рекомендация печатается на чеке ===')
os.chdir(_setup.PROJECT_DIR)
print_service = PrintService()
print_service.receipts_dir = os.path.join(tempfile.gettempdir(), 'tire_shop_test_receipts')
os.makedirs(print_service.receipts_dir, exist_ok=True)

items = order_service.get_order_items(order.id)
path = print_service.generate_receipt(order, items, order_service.calculate_total(order.id))
check('чек создан', os.path.exists(path), path)

with open(path, 'rb') as handle:
    content = handle.read()
check('чек не пустой', len(content) > 1000, str(len(content)))

# Наряд без рекомендаций тоже должен печататься
plain = paid_order('К900ОР99')
plain_path = print_service.generate_receipt(
    plain, order_service.get_order_items(plain.id),
    order_service.calculate_total(plain.id))
check('чек без рекомендаций печатается', os.path.exists(plain_path))

print('\n=== Длинный текст не ломает печать ===')
long_order = paid_order('М777ММ199', 'Очень длинная рекомендация. ' * 40)
long_path = print_service.generate_receipt(
    long_order, order_service.get_order_items(long_order.id),
    order_service.calculate_total(long_order.id))
check('чек с длинным текстом создан', os.path.exists(long_path))

print('\n=== Перенос строк по ширине ===')
lines = print_service._wrap_text(RECOMMENDATION, 500, 10)
check('текст разбит на несколько строк', len(lines) > 1, str(len(lines)))
check('слова не разрезаны',
      all(len(line) < 200 for line in lines) and
      ' '.join(lines).replace('  ', ' ') == RECOMMENDATION.replace('\n', ' '),
      str(lines))

check('пустой абзац не роняет разбор', print_service._wrap_text('строка\n\nвторая', 500, 10))

print('\n=== История рекомендаций у клиента ===')
client = client_service.find_by_phone('79099018931')
# Ещё один визит на ту же машину с другой рекомендацией
paid_order('А123ВВ777', 'Проверить давление через месяц', client_id=client.id)

history = client_service.get_client_recommendations(client.id)
check('обе рекомендации в истории', len(history) == 2, str(len(history)))
check('свежая сверху', 'давление' in history[0]['text'], history[0]['text'][:40])
check('указан автомобиль', history[0]['license_plate'] == 'А123ВВ777')
check('указана дата', history[0]['date'] is not None)
check('указан номер наряда', history[0]['order_id'] is not None)

print('\n=== Пустые рекомендации в историю не попадают ===')
paid_order('А123ВВ777', '   ', client_id=client.id)
check('пробелы не считаются рекомендацией',
      len(client_service.get_client_recommendations(client.id)) == 2,
      str(len(client_service.get_client_recommendations(client.id))))

other = client_service.find_by_phone('79099018931')
check('у клиента без рекомендаций история пуста',
      client_service.get_client_recommendations(999999) == [])

db.close()
finish()
