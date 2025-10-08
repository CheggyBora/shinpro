#!/usr/bin/env python
# -*- coding: utf-8 -*-

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from models import Service, WorkOrder, Car
from services.order_service import OrderService

# Подключение к БД
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
db = Session()

order_service = OrderService(db)

# Проверяем услуги
print("=== Услуги в базе данных ===")
services = db.query(Service).all()
unique_names = list(dict.fromkeys([s.name for s in services]))
print(f"Уникальных названий услуг: {len(unique_names)}")
print(f"Всего услуг: {len(services)}")

for name in unique_names[:3]:
    print(f"\nУслуга: {name}")
    service_variants = db.query(Service).filter(Service.name == name).all()
    for s in service_variants:
        print(f"  - vehicle_type: {s.vehicle_type}, R13: {s.price_r13}, R23: {s.price_r23}, R24: {s.price_r24}")

# Создаём тестовые наряды
print("\n=== Создание тестовых нарядов ===")

test_cases = [
    ("А001АА01", "R13", "car", "Легковой R13"),
    ("В002ВВ02", "R23", "suv", "Джип R23"),
    ("С003СС03", "R24", "truck", "Коммерческий R24"),
]

for license, diameter, vehicle_type, desc in test_cases:
    try:
        order = order_service.create_order(license, diameter, vehicle_type)
        print(f"✓ Создан наряд #{order.id}: {desc}")
        print(f"  - Номер: {order.car.license_plate}")
        print(f"  - Диаметр: {order.wheel_diameter}")
        print(f"  - Тип ТС: {order.vehicle_type}")
        
        # Проверим что услуга добавляется правильно
        service_name = "Шиномонтаж 4 колеса"
        service = db.query(Service).filter(
            Service.name == service_name,
            Service.vehicle_type == vehicle_type
        ).first()
        
        if service:
            order_service.add_service_to_order(order.id, service.id)
            print(f"  - Добавлена услуга: {service.name} (цена для {diameter}: {getattr(service, f'price_{diameter.lower()}', 0)})")
        
    except Exception as e:
        print(f"✗ Ошибка: {e}")

print("\n=== Список нарядов ===")
orders = db.query(WorkOrder).all()
for order in orders[-3:]:
    print(f"Наряд #{order.id}: {order.car.license_plate} ({order.vehicle_type}) - {order.wheel_diameter}")
    for item in order.items:
        print(f"  - {item.service.name}: {item.price} руб.")

db.close()
print("\nГотово!")
