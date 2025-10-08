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
        services_data = [
            {
                'name': 'Шиномонтаж 4 колеса',
                'r13': 800, 'r14': 900, 'r15': 1000, 'r16': 1100,
                'r17': 1200, 'r18': 1300, 'r19': 1400, 'r20': 1500,
                'r21': 1600, 'r22': 1700
            },
            {
                'name': 'Балансировка 4 колеса',
                'r13': 600, 'r14': 700, 'r15': 800, 'r16': 900,
                'r17': 1000, 'r18': 1100, 'r19': 1200, 'r20': 1300,
                'r21': 1400, 'r22': 1500
            },
            {
                'name': 'Правка литого диска',
                'r13': 1500, 'r14': 1500, 'r15': 1500, 'r16': 1500,
                'r17': 1500, 'r18': 1500, 'r19': 1500, 'r20': 1500,
                'r21': 1500, 'r22': 1500
            },
            {
                'name': 'Правка штампованного диска',
                'r13': 800, 'r14': 800, 'r15': 800, 'r16': 800,
                'r17': 800, 'r18': 800, 'r19': 800, 'r20': 800,
                'r21': 800, 'r22': 800
            },
            {
                'name': 'Установка вентиля',
                'r13': 100, 'r14': 100, 'r15': 100, 'r16': 100,
                'r17': 100, 'r18': 100, 'r19': 100, 'r20': 100,
                'r21': 100, 'r22': 100
            },
            {
                'name': 'Грузики набивные (за 1 шт)',
                'r13': 5, 'r14': 5, 'r15': 5, 'r16': 5,
                'r17': 5, 'r18': 5, 'r19': 5, 'r20': 5,
                'r21': 5, 'r22': 5
            },
            {
                'name': 'Грузики клеющиеся (за 1 шт)',
                'r13': 10, 'r14': 10, 'r15': 10, 'r16': 10,
                'r17': 10, 'r18': 10, 'r19': 10, 'r20': 10,
                'r21': 10, 'r22': 10
            },
            {
                'name': 'Мойка колёс (4 шт)',
                'r13': 200, 'r14': 200, 'r15': 200, 'r16': 200,
                'r17': 200, 'r18': 200, 'r19': 200, 'r20': 200,
                'r21': 200, 'r22': 200
            },
            {
                'name': 'Утилизация старых шин (4 шт)',
                'r13': 200, 'r14': 200, 'r15': 200, 'r16': 200,
                'r17': 200, 'r18': 200, 'r19': 200, 'r20': 200,
                'r21': 200, 'r22': 200
            },
            {
                'name': 'Заварка бокового пореза',
                'r13': 1000, 'r14': 1000, 'r15': 1000, 'r16': 1000,
                'r17': 1000, 'r18': 1000, 'r19': 1000, 'r20': 1000,
                'r21': 1000, 'r22': 1000
            }
        ]
        
        for service_data in services_data:
            service = Service(
                name=service_data['name'],
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
                is_active=True
            )
            db.add(service)
        
        db.commit()
        print("Прайс-лист загружен успешно")
    
    db.close()

if __name__ == "__main__":
    from config import init_db
    init_db()
    initialize_data()
