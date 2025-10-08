from config import engine, SessionLocal, Base
from models import Service
from models.settings import Settings

def init_database():
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    db.query(Service).delete()
    
    services_data = []
    
    # ЛЕГКОВОЙ ТРАНСПОРТ
    services_data.extend([
        {
            'name': 'Съем+Установка 4 колеса',
            'vehicle_type': 'car',
            'price_r13': 250, 'price_r14': 250, 'price_r15': 250,
            'price_r16': 300, 'price_r17': 300, 'price_r18': 350,
            'price_r19': 400, 'price_r20': 450, 'price_r21': 500,
            'price_r22': 600, 'price_r23': 650, 'price_r24': 700
        },
        {
            'name': 'Шиномонтаж 4 колеса',
            'vehicle_type': 'car',
            'price_r13': 350, 'price_r14': 350, 'price_r15': 350,
            'price_r16': 400, 'price_r17': 450, 'price_r18': 450,
            'price_r19': 500, 'price_r20': 550, 'price_r21': 600,
            'price_r22': 650, 'price_r23': 700, 'price_r24': 750
        },
        {
            'name': 'Балансировка 4 колеса',
            'vehicle_type': 'car',
            'price_r13': 300, 'price_r14': 300, 'price_r15': 300,
            'price_r16': 350, 'price_r17': 400, 'price_r18': 400,
            'price_r19': 450, 'price_r20': 450, 'price_r21': 500,
            'price_r22': 500, 'price_r23': 550, 'price_r24': 700
        },
        {
            'name': 'Мойка колёс 4 шт',
            'vehicle_type': 'car',
            'price_r13': 120, 'price_r14': 120, 'price_r15': 120,
            'price_r16': 120, 'price_r17': 120, 'price_r18': 120,
            'price_r19': 120, 'price_r20': 120, 'price_r21': 120,
            'price_r22': 120, 'price_r23': 120, 'price_r24': 120
        },
        {
            'name': 'Правка литого диска',
            'vehicle_type': 'car',
            'price_r13': 1800, 'price_r14': 1800, 'price_r15': 1800,
            'price_r16': 2000, 'price_r17': 2200, 'price_r18': 2800,
            'price_r19': 3000, 'price_r20': 3300, 'price_r21': 3500,
            'price_r22': 4000, 'price_r23': 5000, 'price_r24': 5000
        },
    ])
    
    # ДЖИП/КРОССОВЕР/ПИКАП/МИНИВЭН
    services_data.extend([
        {
            'name': 'Съем+Установка 4 колеса',
            'vehicle_type': 'suv',
            'price_r13': 300, 'price_r14': 300, 'price_r15': 300,
            'price_r16': 350, 'price_r17': 350, 'price_r18': 400,
            'price_r19': 450, 'price_r20': 500, 'price_r21': 550,
            'price_r22': 650, 'price_r23': 750, 'price_r24': 900
        },
        {
            'name': 'Шиномонтаж 4 колеса',
            'vehicle_type': 'suv',
            'price_r13': 350, 'price_r14': 350, 'price_r15': 350,
            'price_r16': 450, 'price_r17': 500, 'price_r18': 550,
            'price_r19': 600, 'price_r20': 650, 'price_r21': 650,
            'price_r22': 700, 'price_r23': 800, 'price_r24': 950
        },
        {
            'name': 'Балансировка 4 колеса',
            'vehicle_type': 'suv',
            'price_r13': 350, 'price_r14': 350, 'price_r15': 350,
            'price_r16': 400, 'price_r17': 450, 'price_r18': 500,
            'price_r19': 550, 'price_r20': 550, 'price_r21': 600,
            'price_r22': 650, 'price_r23': 750, 'price_r24': 900
        },
        {
            'name': 'Мойка колёс 4 шт',
            'vehicle_type': 'suv',
            'price_r13': 120, 'price_r14': 120, 'price_r15': 120,
            'price_r16': 120, 'price_r17': 120, 'price_r18': 120,
            'price_r19': 120, 'price_r20': 120, 'price_r21': 120,
            'price_r22': 120, 'price_r23': 120, 'price_r24': 120
        },
    ])
    
    # КАТЕГОРИЯ "С" (КОММЕРЧЕСКИЙ ТРАНСПОРТ)
    services_data.extend([
        {
            'name': 'Съем+Установка (внутр. колесо)',
            'vehicle_type': 'truck',
            'price_r13': 800, 'price_r14': 800, 'price_r15': 800,
            'price_r16': 800, 'price_r17': 800, 'price_r18': 800,
            'price_r19': 800, 'price_r20': 800, 'price_r21': 800,
            'price_r22': 800, 'price_r23': 800, 'price_r24': 800
        },
        {
            'name': 'Съем+Установка внутр. колесо (доплата)',
            'vehicle_type': 'truck',
            'price_r13': 1000, 'price_r14': 1000, 'price_r15': 1000,
            'price_r16': 1000, 'price_r17': 1000, 'price_r18': 1000,
            'price_r19': 1000, 'price_r20': 1000, 'price_r21': 1000,
            'price_r22': 1000, 'price_r23': 1000, 'price_r24': 1000
        },
        {
            'name': 'Шиномонтаж категория С',
            'vehicle_type': 'truck',
            'price_r13': 700, 'price_r14': 700, 'price_r15': 700,
            'price_r16': 700, 'price_r17': 700, 'price_r18': 700,
            'price_r19': 700, 'price_r20': 700, 'price_r21': 700,
            'price_r22': 700, 'price_r23': 700, 'price_r24': 700
        },
        {
            'name': 'Балансировка категория С',
            'vehicle_type': 'truck',
            'price_r13': 700, 'price_r14': 700, 'price_r15': 700,
            'price_r16': 700, 'price_r17': 700, 'price_r18': 700,
            'price_r19': 700, 'price_r20': 700, 'price_r21': 700,
            'price_r22': 700, 'price_r23': 700, 'price_r24': 700
        },
        {
            'name': 'Мойка колёс категория С',
            'vehicle_type': 'truck',
            'price_r13': 120, 'price_r14': 120, 'price_r15': 120,
            'price_r16': 120, 'price_r17': 120, 'price_r18': 120,
            'price_r19': 120, 'price_r20': 120, 'price_r21': 120,
            'price_r22': 120, 'price_r23': 120, 'price_r24': 120
        },
    ])
    
    # ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ (фиксированные цены, не зависят от диаметра и типа ТС)
    fixed_services = [
        {'name': 'Доплата за Runflat', 'price': 300},
        {'name': 'Доплата за оптимизацию балансировки', 'price': 300},
        {'name': 'Грязевая покрышка АТ/МТ', 'price': 500},
        {'name': 'Замена вентиля', 'price': 50},
        {'name': 'Подкачка/проверка давления', 'price': 50},
        {'name': 'Установка датчика давления', 'price': 400},
        {'name': 'Ремонт жгутом', 'price': 800},
        {'name': 'Устранение негерметичности диска', 'price': 300},
        {'name': 'Шлифовка бортов диска', 'price': 300},
        {'name': 'Шлифовка ступицы', 'price': 300},
        {'name': 'Обработка смазкой', 'price': 150},
        {'name': 'Косметический ремонт шины', 'price': 1500},
        {'name': 'Зачистка диска от скотча', 'price': 300},
        {'name': 'Слесарные работы', 'price': 500},
        {'name': 'Открутить секретный болт', 'price': 2000},
        {'name': 'Открутить поврежденный болт', 'price': 1500},
        {'name': 'Дошиповка за 1 шип', 'price': 40},
        {'name': 'Прочие услуги', 'price': 500},
    ]
    
    for service in fixed_services:
        price = service['price']
        services_data.append({
            'name': service['name'],
            'vehicle_type': 'all',
            'price_r13': price, 'price_r14': price, 'price_r15': price,
            'price_r16': price, 'price_r17': price, 'price_r18': price,
            'price_r19': price, 'price_r20': price, 'price_r21': price,
            'price_r22': price, 'price_r23': price, 'price_r24': price
        })
    
    # РАСХОДНЫЕ МАТЕРИАЛЫ
    materials = [
        {'name': 'Вентиль под датчик', 'price': 700},
        {'name': 'Вентиль черный', 'price': 100},
        {'name': 'Пакет', 'price': 100},
    ]
    
    for material in materials:
        price = material['price']
        services_data.append({
            'name': material['name'],
            'vehicle_type': 'all',
            'price_r13': price, 'price_r14': price, 'price_r15': price,
            'price_r16': price, 'price_r17': price, 'price_r18': price,
            'price_r19': price, 'price_r20': price, 'price_r21': price,
            'price_r22': price, 'price_r23': price, 'price_r24': price
        })
    
    # РЕМОНТ ГРИБКОМ (зависит от диаметра, для всех типов ТС)
    services_data.append({
        'name': 'Ремонт грибком/кордовой заплаткой',
        'vehicle_type': 'all',
        'price_r13': 1200, 'price_r14': 1200, 'price_r15': 1200,
        'price_r16': 1200, 'price_r17': 1200, 'price_r18': 1500,
        'price_r19': 1500, 'price_r20': 1500, 'price_r21': 1500,
        'price_r22': 1500, 'price_r23': 1500, 'price_r24': 1500
    })
    
    # РЕМОНТ БОКОВОГО ПОРЕЗА (зависит от диаметра, для всех типов ТС)
    services_data.append({
        'name': 'Ремонт бокового пореза',
        'vehicle_type': 'all',
        'price_r13': 2900, 'price_r14': 2900, 'price_r15': 2900,
        'price_r16': 3800, 'price_r17': 3800, 'price_r18': 3800,
        'price_r19': 4800, 'price_r20': 4800, 'price_r21': 4800,
        'price_r22': 6000, 'price_r23': 6000, 'price_r24': 6000
    })
    
    # Добавляем все услуги в базу
    for service_data in services_data:
        service = Service(**service_data)
        db.add(service)
    
    # Проверяем и добавляем настройки
    admin_pin = db.query(Settings).filter(Settings.key == 'admin_pin').first()
    if not admin_pin:
        admin_pin = Settings(key='admin_pin', value='0000')
        db.add(admin_pin)
    
    db.commit()
    db.close()
    
    print("База данных успешно инициализирована!")
    print(f"Добавлено услуг: {len(services_data)}")

if __name__ == "__main__":
    init_database()
