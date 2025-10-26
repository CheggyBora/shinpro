from datetime import datetime
from config import SessionLocal
from models import TireStorage, Settings

class TireStorageService:
    @staticmethod
    def calculate_price(diameter):
        """Получить цену хранения для конкретного размера шин"""
        diameter_num = int(diameter.replace('R', ''))
        
        # Дефолтные цены по размерам
        default_prices = {
            13: 4000, 14: 4000, 15: 4000,
            16: 5000, 17: 5000, 18: 5000,
            19: 6000, 20: 6000,
            21: 8000, 22: 8000, 23: 8000, 24: 8000
        }
        
        # Если размер не поддерживается
        if diameter_num not in default_prices:
            return 0.0
        
        db = SessionLocal()
        try:
            # Формируем ключ настройки: storage_price_r13, storage_price_r14 и т.д.
            setting_key = f'storage_price_r{diameter_num}'
            price_setting = db.query(Settings).filter(Settings.key == setting_key).first()
            
            # Возвращаем цену из БД или дефолтную
            return float(price_setting.value) if price_setting else default_prices[diameter_num]
        finally:
            db.close()
    
    @staticmethod
    def accept_storage(car_number, driver_license, storage_type, diameter, brand, damage, wear, comments='', wheel_type=None):
        db = SessionLocal()
        try:
            price = TireStorageService.calculate_price(diameter)
            
            storage = TireStorage(
                car_number=car_number,
                driver_license=driver_license,
                storage_type=storage_type,
                diameter=diameter,
                brand=brand,
                damage=damage,
                wear=wear,
                comments=comments,
                wheel_type=wheel_type,
                price=price,
                status='stored'
            )
            
            db.add(storage)
            db.commit()
            db.refresh(storage)
            return storage
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    
    @staticmethod
    def search_by_car_number(car_number):
        db = SessionLocal()
        try:
            # Возвращаем все комплекты (и на хранении, и выданные)
            # Сортируем: сначала на хранении (stored), потом выданные (released)
            storages = db.query(TireStorage).filter(
                TireStorage.car_number == car_number
            ).order_by(
                TireStorage.status.desc(),  # 'stored' идёт после 'released' в алфавите, поэтому desc()
                TireStorage.accepted_date.desc()
            ).all()
            return storages
        finally:
            db.close()
    
    @staticmethod
    def release_storage(storage_id):
        db = SessionLocal()
        try:
            storage = db.query(TireStorage).filter(TireStorage.id == storage_id).first()
            if storage:
                storage.status = 'released'
                storage.released_date = datetime.now()
                db.commit()
                db.refresh(storage)
                return storage
            return None
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
    
    @staticmethod
    def get_all_stored():
        db = SessionLocal()
        try:
            # Возвращаем все комплекты (и на хранении, и выданные)
            # Сортируем: сначала на хранении (stored), потом выданные (released)
            storages = db.query(TireStorage).order_by(
                TireStorage.status.desc(),  # 'stored' идёт после 'released' в алфавите, поэтому desc()
                TireStorage.accepted_date.desc()
            ).all()
            return storages
        finally:
            db.close()
    
    @staticmethod
    def get_storage_by_id(storage_id):
        db = SessionLocal()
        try:
            storage = db.query(TireStorage).filter(TireStorage.id == storage_id).first()
            return storage
        finally:
            db.close()
