from config import get_db
from models import Service, Settings

def initialize_data():
    db = get_db()
    
    existing_settings = db.query(Settings).filter(Settings.key == 'admin_pin').first()
    if not existing_settings:
        admin_pin = Settings(key='admin_pin', value='0000')
        db.add(admin_pin)
        db.commit()
    
    existing_services = db.query(Service).count()
    if existing_services == 0:
        services_data = []
        
        # 1. ОСНОВНЫЕ УСЛУГИ - ЛЕГКОВЫЕ (за 1 колесо)
        services_data.extend([
            {
                'name': 'Съем+Установка', 'vehicle_type': 'car', 'editable': False,
                'r13': 250, 'r14': 250, 'r15': 250, 'r16': 300, 'r17': 300, 'r18': 350,
                'r19': 400, 'r20': 450, 'r21': 500, 'r22': 600, 'r23': 650, 'r24': 700
            },
            {
                'name': 'Шиномонтаж', 'vehicle_type': 'car', 'editable': False,
                'r13': 350, 'r14': 350, 'r15': 350, 'r16': 400, 'r17': 450, 'r18': 450,
                'r19': 500, 'r20': 550, 'r21': 600, 'r22': 650, 'r23': 700, 'r24': 750
            },
            {
                'name': 'Балансировка', 'vehicle_type': 'car', 'editable': False,
                'r13': 300, 'r14': 300, 'r15': 300, 'r16': 350, 'r17': 400, 'r18': 400,
                'r19': 450, 'r20': 450, 'r21': 500, 'r22': 500, 'r23': 550, 'r24': 700
            },
            {
                'name': 'Мойка', 'vehicle_type': 'car', 'editable': False,
                'r13': 120, 'r14': 120, 'r15': 120, 'r16': 120, 'r17': 120, 'r18': 120,
                'r19': 120, 'r20': 120, 'r21': 120, 'r22': 120, 'r23': 120, 'r24': 120
            }
        ])
        
        # 1. ОСНОВНЫЕ УСЛУГИ - ДЖИП/КРОССОВЕР (за 1 колесо)
        services_data.extend([
            {
                'name': 'Съем+Установка', 'vehicle_type': 'suv', 'editable': False,
                'r13': 300, 'r14': 300, 'r15': 300, 'r16': 350, 'r17': 350, 'r18': 400,
                'r19': 450, 'r20': 500, 'r21': 550, 'r22': 650, 'r23': 750, 'r24': 900
            },
            {
                'name': 'Шиномонтаж', 'vehicle_type': 'suv', 'editable': False,
                'r13': 350, 'r14': 350, 'r15': 350, 'r16': 450, 'r17': 500, 'r18': 550,
                'r19': 600, 'r20': 650, 'r21': 650, 'r22': 700, 'r23': 800, 'r24': 950
            },
            {
                'name': 'Балансировка', 'vehicle_type': 'suv', 'editable': False,
                'r13': 350, 'r14': 350, 'r15': 350, 'r16': 400, 'r17': 450, 'r18': 500,
                'r19': 550, 'r20': 550, 'r21': 600, 'r22': 650, 'r23': 750, 'r24': 900
            },
            {
                'name': 'Мойка', 'vehicle_type': 'suv', 'editable': False,
                'r13': 120, 'r14': 120, 'r15': 120, 'r16': 120, 'r17': 120, 'r18': 120,
                'r19': 120, 'r20': 120, 'r21': 120, 'r22': 120, 'r23': 120, 'r24': 120
            }
        ])
        
        # 1. ОСНОВНЫЕ УСЛУГИ - КАТЕГОРИЯ С (от R15)
        services_data.extend([
            {
                'name': 'Съем+Установка', 'vehicle_type': 'truck', 'editable': False,
                'r13': 0, 'r14': 0, 'r15': 800, 'r16': 800, 'r17': 800, 'r18': 800,
                'r19': 800, 'r20': 800, 'r21': 800, 'r22': 800, 'r23': 800, 'r24': 800
            },
            {
                'name': 'Съем+Установка внутреннего колеса', 'vehicle_type': 'truck', 'editable': False,
                'r13': 0, 'r14': 0, 'r15': 1000, 'r16': 1000, 'r17': 1000, 'r18': 1000,
                'r19': 1000, 'r20': 1000, 'r21': 1000, 'r22': 1000, 'r23': 1000, 'r24': 1000
            },
            {
                'name': 'Шиномонтаж', 'vehicle_type': 'truck', 'editable': False,
                'r13': 0, 'r14': 0, 'r15': 700, 'r16': 700, 'r17': 700, 'r18': 700,
                'r19': 700, 'r20': 700, 'r21': 700, 'r22': 700, 'r23': 700, 'r24': 700
            },
            {
                'name': 'Балансировка', 'vehicle_type': 'truck', 'editable': False,
                'r13': 0, 'r14': 0, 'r15': 700, 'r16': 700, 'r17': 700, 'r18': 700,
                'r19': 700, 'r20': 700, 'r21': 700, 'r22': 700, 'r23': 700, 'r24': 700
            },
            {
                'name': 'Мойка', 'vehicle_type': 'truck', 'editable': False,
                'r13': 0, 'r14': 0, 'r15': 120, 'r16': 120, 'r17': 120, 'r18': 120,
                'r19': 120, 'r20': 120, 'r21': 120, 'r22': 120, 'r23': 120, 'r24': 120
            }
        ])
        
        # 2. ПРАВКА ЛИТЫХ ДИСКОВ (от, редактируемые)
        services_data.append({
            'name': 'Правка литого диска', 'vehicle_type': 'all', 'editable': True,
            'r13': 1800, 'r14': 1800, 'r15': 1800, 'r16': 2000, 'r17': 2200, 'r18': 2800,
            'r19': 3000, 'r20': 3300, 'r21': 3500, 'r22': 4000, 'r23': 5000, 'r24': 5000
        })
        
        # 3. ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ (фиксированные)
        fixed_services = [
            {'name': 'Runflat', 'price': 300},
            {'name': 'Оптимизация балансировки', 'price': 300},
            {'name': 'Замена вентиля', 'price': 50},
            {'name': 'Подкачка/проверка давления', 'price': 50},
            {'name': 'Установка датчика давления', 'price': 400},
            {'name': 'Ремонт жгутом', 'price': 800},
            {'name': 'Герметик обода', 'price': 300},
            {'name': 'Шлифовка бортов диска', 'price': 300},
            {'name': 'Шлифовка ступицы', 'price': 300},
            {'name': 'Обработка смазкой', 'price': 150},
            {'name': 'Косметический ремонт шины', 'price': 1500},
            {'name': 'Дошиповка (за 1 шип)', 'price': 40},
            {'name': 'Грязевая покрышка АТ/МТ', 'price': 500}
        ]
        
        for svc in fixed_services:
            services_data.append({
                'name': svc['name'], 'vehicle_type': 'all', 'editable': False,
                'r13': svc['price'], 'r14': svc['price'], 'r15': svc['price'],
                'r16': svc['price'], 'r17': svc['price'], 'r18': svc['price'],
                'r19': svc['price'], 'r20': svc['price'], 'r21': svc['price'],
                'r22': svc['price'], 'r23': svc['price'], 'r24': svc['price']
            })
        
        # 4. ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ (редактируемые "от")
        editable_services = [
            {'name': 'Зачистка диска от скотча', 'price': 300},
            {'name': 'Слесарные работы', 'price': 500},
            {'name': 'Открутка секретного болта', 'price': 2000},
            {'name': 'Срыв болта/гайки', 'price': 1500},
            {'name': 'Прочие услуги', 'price': 500}
        ]
        
        for svc in editable_services:
            services_data.append({
                'name': svc['name'], 'vehicle_type': 'all', 'editable': True,
                'r13': svc['price'], 'r14': svc['price'], 'r15': svc['price'],
                'r16': svc['price'], 'r17': svc['price'], 'r18': svc['price'],
                'r19': svc['price'], 'r20': svc['price'], 'r21': svc['price'],
                'r22': svc['price'], 'r23': svc['price'], 'r24': svc['price']
            })
        
        # 5. РАСХОДНЫЕ МАТЕРИАЛЫ
        materials = [
            {'name': 'Вентиль под датчик', 'price': 700},
            {'name': 'Вентиль черный', 'price': 100},
            {'name': 'Пакет', 'price': 100},
            {'name': 'Золотник', 'price': 0},
            {'name': 'Колпочки', 'price': 0}
        ]
        
        for mat in materials:
            services_data.append({
                'name': mat['name'], 'vehicle_type': 'all', 'editable': False,
                'r13': mat['price'], 'r14': mat['price'], 'r15': mat['price'],
                'r16': mat['price'], 'r17': mat['price'], 'r18': mat['price'],
                'r19': mat['price'], 'r20': mat['price'], 'r21': mat['price'],
                'r22': mat['price'], 'r23': mat['price'], 'r24': mat['price']
            })
        
        # 6. ПРОВЕРКИ (бесплатно)
        checks = [
            'Проверка на герметичность',
            'Проверка на балансировку',
            'Проверка затяжки болтов'
        ]
        
        for check in checks:
            services_data.append({
                'name': check, 'vehicle_type': 'all', 'editable': False,
                'r13': 0, 'r14': 0, 'r15': 0, 'r16': 0, 'r17': 0, 'r18': 0,
                'r19': 0, 'r20': 0, 'r21': 0, 'r22': 0, 'r23': 0, 'r24': 0
            })
        
        # 7. РЕМОНТ ГРИБКОМ (зависит от диаметра)
        services_data.append({
            'name': 'Ремонт грибком', 'vehicle_type': 'all', 'editable': False,
            'r13': 1200, 'r14': 1200, 'r15': 1200, 'r16': 1200, 'r17': 1200,
            'r18': 1500, 'r19': 1500, 'r20': 1500, 'r21': 1500, 'r22': 1500,
            'r23': 1500, 'r24': 1500
        })
        
        # 8. РЕМОНТ БОКОВОГО ПОРЕЗА (зависит от диаметра)
        services_data.append({
            'name': 'Ремонт бокового пореза', 'vehicle_type': 'all', 'editable': False,
            'r13': 2900, 'r14': 2900, 'r15': 2900, 'r16': 3800, 'r17': 3800,
            'r18': 3800, 'r19': 4800, 'r20': 4800, 'r21': 4800, 'r22': 6000,
            'r23': 6000, 'r24': 6000
        })
        
        # 9. ХРАНЕНИЕ ШИН (услуга для работы с модулем хранения)
        # Цены соответствуют логике в TireStorageService.calculate_price()
        services_data.append({
            'name': 'Хранение шин', 'vehicle_type': 'all', 'editable': False,
            'r13': 4000, 'r14': 4000, 'r15': 4000, 'r16': 5000, 'r17': 5000,
            'r18': 5000, 'r19': 6000, 'r20': 6000, 'r21': 8000, 'r22': 8000,
            'r23': 8000, 'r24': 8000
        })
        
        for service_data in services_data:
            service = Service(
                name=service_data['name'],
                vehicle_type=service_data['vehicle_type'],
                price_r13=service_data['r13'],
                price_r14=service_data['r14'],
                price_r15=service_data['r15'],
                price_r16=service_data['r16'],
                price_r17=service_data['r17'],
                price_r18=service_data['r18'],
                price_r19=service_data['r19'],
                price_r20=service_data['r20'],
                price_r21=service_data['r21'],
                price_r22=service_data['r22'],
                price_r23=service_data['r23'],
                price_r24=service_data['r24'],
                is_active=True,
                editable_price=service_data['editable']
            )
            db.add(service)
        
        db.commit()
        print("Прайс-лист загружен успешно")
    
    # ВАЖНО: Проверка наличия услуги "Хранение шин" (необходима для модуля хранения)
    # Добавляется отдельно, чтобы создаваться даже в существующих базах данных
    # Цены соответствуют логике в TireStorageService.calculate_price():
    # R13-R15: 4000₽, R16-R18: 5000₽, R19-R20: 6000₽, R21-R24: 8000₽
    storage_service = db.query(Service).filter(Service.name == 'Хранение шин').first()
    if not storage_service:
        print("Добавление услуги 'Хранение шин'...")
        storage_service = Service(
            name='Хранение шин',
            vehicle_type='all',
            price_r13=4000, price_r14=4000, price_r15=4000, price_r16=5000,
            price_r17=5000, price_r18=5000, price_r19=6000, price_r20=6000,
            price_r21=8000, price_r22=8000, price_r23=8000, price_r24=8000,
            is_active=True,
            editable_price=False
        )
        db.add(storage_service)
        db.commit()
        print("Услуга 'Хранение шин' добавлена успешно")
    
    db.close()

if __name__ == "__main__":
    from config import init_db
    init_db()
    initialize_data()
