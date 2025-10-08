from datetime import datetime
from config import SessionLocal
from models import TireStorage

class TireStorageService:
    @staticmethod
    def calculate_price(diameter):
        diameter_num = int(diameter.replace('R', ''))
        
        if 13 <= diameter_num <= 15:
            return 4000.0
        elif 16 <= diameter_num <= 18:
            return 5000.0
        elif 19 <= diameter_num <= 20:
            return 6000.0
        elif 21 <= diameter_num <= 24:
            return 8000.0
        else:
            return 0.0
    
    @staticmethod
    def accept_storage(car_number, storage_type, diameter, brand, damage, wear):
        db = SessionLocal()
        try:
            price = TireStorageService.calculate_price(diameter)
            
            storage = TireStorage(
                car_number=car_number,
                storage_type=storage_type,
                diameter=diameter,
                brand=brand,
                damage=damage,
                wear=wear,
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
            storages = db.query(TireStorage).filter(
                TireStorage.car_number == car_number,
                TireStorage.status == 'stored'
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
            storages = db.query(TireStorage).filter(TireStorage.status == 'stored').all()
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
