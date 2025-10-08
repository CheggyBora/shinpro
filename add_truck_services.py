#!/usr/bin/env python
# -*- coding: utf-8 -*-

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import DATABASE_URL
from models import Service

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
db = Session()

# Услуги для коммерческого транспорта (Категория С)
truck_services = [
    {
        'name': 'Шиномонтаж 4 колеса',
        'vehicle_type': 'truck',
        'price_r13': 0, 'price_r14': 0, 'price_r15': 0,
        'price_r16': 800, 'price_r17': 900, 'price_r18': 1000,
        'price_r19': 1100, 'price_r20': 1200, 'price_r21': 1300,
        'price_r22': 1400, 'price_r23': 1500, 'price_r24': 1600
    },
    {
        'name': 'Балансировка 4 колеса',
        'vehicle_type': 'truck',
        'price_r13': 0, 'price_r14': 0, 'price_r15': 0,
        'price_r16': 750, 'price_r17': 850, 'price_r18': 950,
        'price_r19': 1050, 'price_r20': 1150, 'price_r21': 1250,
        'price_r22': 1350, 'price_r23': 1450, 'price_r24': 1550
    },
    {
        'name': 'Правка литого диска',
        'vehicle_type': 'truck',
        'price_r13': 0, 'price_r14': 0, 'price_r15': 0,
        'price_r16': 2500, 'price_r17': 2700, 'price_r18': 2900,
        'price_r19': 3100, 'price_r20': 3300, 'price_r21': 3500,
        'price_r22': 3700, 'price_r23': 3900, 'price_r24': 4100
    },
    {
        'name': 'Правка штампованного диска',
        'vehicle_type': 'truck',
        'price_r13': 0, 'price_r14': 0, 'price_r15': 0,
        'price_r16': 900, 'price_r17': 1000, 'price_r18': 1100,
        'price_r19': 1200, 'price_r20': 1300, 'price_r21': 1400,
        'price_r22': 1500, 'price_r23': 1600, 'price_r24': 1700
    },
]

print("Добавление услуг для коммерческого транспорта...")

for service_data in truck_services:
    existing = db.query(Service).filter(
        Service.name == service_data['name'],
        Service.vehicle_type == service_data['vehicle_type']
    ).first()
    
    if not existing:
        service = Service(**service_data)
        db.add(service)
        print(f"✓ Добавлена: {service_data['name']} (truck)")
    else:
        print(f"- Уже есть: {service_data['name']} (truck)")

db.commit()
print("\nГотово! Услуги для категории С добавлены.")
db.close()
