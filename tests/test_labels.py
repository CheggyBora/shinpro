"""
Наклейки на комплекты шин и чек для термопринтера.

Обе печати подключаемые: пока принтера нет, они выключены и ничего
не меняют — чек печатается на A4, кнопки наклейки не появляются.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('labels')

import os
import tempfile

from config import init_db, SessionLocal
from models import Service, TireStorage
from services import OrderService, SalaryService, EmployeeService, ClientService, PrintService
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.label_service import LabelService, parse_size, LABEL_SIZES

init_db()
db = SessionLocal()
settings = SettingsService(db)
settings.ensure_defaults()

ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.commit()
service = db.query(Service).first()

order_service = OrderService(db)

print('=== Разбор размера наклейки ===')
check('58x40 разбирается', parse_size('58x40') == (58.0, 40.0), str(parse_size('58x40')))
check('100x50 разбирается', parse_size('100x50') == (100.0, 50.0))
check('мусор даёт размер по умолчанию', parse_size('абв') == (58.0, 40.0),
      str(parse_size('абв')))
check('пустое значение не роняет', parse_size(None) == (58.0, 40.0))
check('в списке есть ходовые размеры', '58x40' in LABEL_SIZES and '100x50' in LABEL_SIZES)

print('\n=== По умолчанию печать наклеек выключена ===')
label_service = LabelService(db)
check('наклейки выключены', label_service.is_enabled() is False)
check('термочек выключен', settings.get('thermal_receipt_enabled', '0') == '0')

print('\n=== Включение через настройки ===')
settings.set('label_printing_enabled', '1')
check('наклейки включились', LabelService(db).is_enabled() is True)

settings.set('label_size', '100x50')
check('размер берётся из настроек', LabelService(db).get_size() == (100.0, 50.0),
      str(LabelService(db).get_size()))

print('\n=== Наклейка собирается ===')
order = order_service.create_order('А123ВВ777', 'R17', 'car',
                                   client_name='Андрей Дюпин', client_phone='79099018931')
client = ClientService(db).find_by_phone('79099018931')

storage = TireStorage(car_number='А123ВВ777', storage_type='Шины с дисками',
                      diameter='R17', brand='Nokian Hakkapeliitta',
                      wheel_type='Литые', price=5000.0, status='stored')
db.add(storage)
db.commit()
db.refresh(storage)

service_labels = LabelService(db)
# Пишем во временную папку, чтобы не сорить рядом с программой
service_labels.labels_dir = os.path.join(tempfile.gettempdir(), 'tire_shop_labels')
path = service_labels.generate_storage_label(storage, client=client)
check('файл наклейки создан', os.path.exists(path), path)
check('файл не пустой', os.path.getsize(path) > 500, str(os.path.getsize(path)))

print('\n=== Наклейка без клиента тоже печатается ===')
lonely = TireStorage(car_number='К900ОР99', storage_type='Шины',
                     diameter='R16', price=4000.0, status='stored')
db.add(lonely)
db.commit()
db.refresh(lonely)
path2 = service_labels.generate_storage_label(lonely, client=None)
check('файл создан без владельца', os.path.exists(path2))

print('\n=== Несколько копий в одном файле ===')
# Файл наклейки перезаписывается по номеру комплекта, поэтому размер
# одиночной запоминаем ДО повторной сборки — иначе сравним файл сам с собой
single_size = os.path.getsize(path)
path3 = service_labels.generate_storage_label(storage, client=client, copies=4)
check('файл на несколько наклеек создан', os.path.exists(path3))
check('он больше одиночного', os.path.getsize(path3) > single_size,
      f'{os.path.getsize(path3)} против {single_size}')

print('\n=== Маленький размер не ломает макет ===')
settings.set('label_size', '58x40')
small = LabelService(db)
small.labels_dir = service_labels.labels_dir
check('маленькая наклейка собирается',
      os.path.exists(small.generate_storage_label(storage, client=client)))

print('\n=== Длинные данные обрезаются, а не вылезают ===')
long_storage = TireStorage(
    car_number='М777ММ199',
    storage_type='Шины с дисками очень длинное название типа хранения',
    diameter='R21', brand='Очень длинное название марки шины и модели ' * 3,
    wheel_type='Штампованные', price=8000.0, status='stored')
db.add(long_storage)
db.commit()
db.refresh(long_storage)
check('наклейка с длинными данными собирается',
      os.path.exists(small.generate_storage_label(long_storage, client=client)))

print('\n=== Чек для термопринтера ===')
order_service.add_service_to_order(order.id, service.id)
order.recommendations = 'Через 5000 км заменить передние колодки'
db.commit()
SalaryService(db).process_payment(order.id, 'cash', order_service.calculate_total(order.id))

os.chdir(_setup.PROJECT_DIR)
print_service = PrintService()
print_service.receipts_dir = os.path.join(tempfile.gettempdir(), 'tire_shop_thermal')
os.makedirs(print_service.receipts_dir, exist_ok=True)

items = order_service.get_order_items(order.id)
total = order_service.calculate_total(order.id)

for width in (58, 80):
    thermal = print_service.generate_thermal_receipt(order, items, total, width_mm=width)
    check(f'чек шириной {width} мм создан', os.path.exists(thermal), thermal)
    check(f'чек {width} мм не пустой', os.path.getsize(thermal) > 500)

print('\n=== Обычный чек по-прежнему работает ===')
a4 = print_service.generate_receipt(order, items, total)
check('чек A4 создан', os.path.exists(a4))

db.close()
finish()
