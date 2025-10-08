from config import SessionLocal
from models import Service
from models.settings import Settings

def update_services():
    db = SessionLocal()
    
    # Обновляем существующие услуги - добавляем vehicle_type
    existing_services = db.query(Service).all()
    for service in existing_services:
        service.vehicle_type = 'car'  # Старые услуги считаем легковыми
    
    db.commit()
    
    # Добавляем новые услуги для других типов транспорта
    new_services = []
    
    # ДЖИП/КРОССОВЕР/ПИКАП/МИНИВЭН
    new_services.extend([
        Service(
            name='Съем+Установка 4 колеса',
            vehicle_type='suv',
            price_r13=300, price_r14=300, price_r15=300,
            price_r16=350, price_r17=350, price_r18=400,
            price_r19=450, price_r20=500, price_r21=550,
            price_r22=650, price_r23=750, price_r24=900
        ),
        Service(
            name='Шиномонтаж 4 колеса',
            vehicle_type='suv',
            price_r13=350, price_r14=350, price_r15=350,
            price_r16=450, price_r17=500, price_r18=550,
            price_r19=600, price_r20=650, price_r21=650,
            price_r22=700, price_r23=800, price_r24=950
        ),
        Service(
            name='Балансировка 4 колеса',
            vehicle_type='suv',
            price_r13=350, price_r14=350, price_r15=350,
            price_r16=400, price_r17=450, price_r18=500,
            price_r19=550, price_r20=550, price_r21=600,
            price_r22=650, price_r23=750, price_r24=900
        ),
        Service(
            name='Мойка колёс 4 шт',
            vehicle_type='suv',
            price_r13=120, price_r14=120, price_r15=120,
            price_r16=120, price_r17=120, price_r18=120,
            price_r19=120, price_r20=120, price_r21=120,
            price_r22=120, price_r23=120, price_r24=120
        ),
    ])
    
    # КАТЕГОРИЯ "С" (КОММЕРЧЕСКИЙ ТРАНСПОРТ)
    new_services.extend([
        Service(
            name='Съем+Установка (категория С)',
            vehicle_type='truck',
            price_r13=800, price_r14=800, price_r15=800,
            price_r16=800, price_r17=800, price_r18=800,
            price_r19=800, price_r20=800, price_r21=800,
            price_r22=800, price_r23=800, price_r24=800
        ),
        Service(
            name='Шиномонтаж категория С',
            vehicle_type='truck',
            price_r13=700, price_r14=700, price_r15=700,
            price_r16=700, price_r17=700, price_r18=700,
            price_r19=700, price_r20=700, price_r21=700,
            price_r22=700, price_r23=700, price_r24=700
        ),
        Service(
            name='Балансировка категория С',
            vehicle_type='truck',
            price_r13=700, price_r14=700, price_r15=700,
            price_r16=700, price_r17=700, price_r18=700,
            price_r19=700, price_r20=700, price_r21=700,
            price_r22=700, price_r23=700, price_r24=700
        ),
    ])
    
    # ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ
    additional_services = [
        {'name': 'Доплата за Runflat', 'price': 300},
        {'name': 'Грязевая покрышка АТ/МТ', 'price': 500},
        {'name': 'Ремонт жгутом', 'price': 800},
        {'name': 'Косметический ремонт шины', 'price': 1500},
    ]
    
    for serv_data in additional_services:
        price = serv_data['price']
        new_services.append(Service(
            name=serv_data['name'],
            vehicle_type='all',
            price_r13=price, price_r14=price, price_r15=price,
            price_r16=price, price_r17=price, price_r18=price,
            price_r19=price, price_r20=price, price_r21=price,
            price_r22=price, price_r23=price, price_r24=price
        ))
    
    # Добавляем новые услуги
    for service in new_services:
        db.add(service)
    
    db.commit()
    db.close()
    
    print(f"Обновлено! Добавлено {len(new_services)} новых услуг")

if __name__ == "__main__":
    update_services()
