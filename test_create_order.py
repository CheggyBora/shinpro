#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from services.order_service import OrderService

try:
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    order_service = OrderService(db)
    
    # Тест создания наряда как в UI
    print("Тестирование создания наряда...")
    order = order_service.create_order(
        license_plate="Т001ТТ77",
        wheel_diameter="R16",
        vehicle_type="car",
        client_number=None,
        client_name=None
    )
    
    print(f"✓ Наряд создан успешно: #{order.id}")
    print(f"  - Номер: {order.car.license_plate}")
    print(f"  - Диаметр: {order.wheel_diameter}")
    print(f"  - Тип ТС: {order.vehicle_type}")
    
    db.close()
    
except Exception as e:
    print(f"✗ ОШИБКА: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
