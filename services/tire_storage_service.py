from datetime import datetime
from config import SessionLocal
from models import TireStorage, Settings

class TireStorageService:
    @staticmethod
    def calculate_price(diameter):
        diameter_num = int(diameter.replace('R', ''))
        
        db = SessionLocal()
        try:
            # Получаем цены из настроек
            if 13 <= diameter_num <= 15:
                price_setting = db.query(Settings).filter(Settings.key == 'storage_price_r13_r15').first()
                return float(price_setting.value) if price_setting else 4000.0
            elif 16 <= diameter_num <= 18:
                price_setting = db.query(Settings).filter(Settings.key == 'storage_price_r16_r18').first()
                return float(price_setting.value) if price_setting else 5000.0
            elif 19 <= diameter_num <= 20:
                price_setting = db.query(Settings).filter(Settings.key == 'storage_price_r19_r20').first()
                return float(price_setting.value) if price_setting else 6000.0
            elif 21 <= diameter_num <= 24:
                price_setting = db.query(Settings).filter(Settings.key == 'storage_price_r21_r24').first()
                return float(price_setting.value) if price_setting else 8000.0
            else:
                return 0.0
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
