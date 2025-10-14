from models import Car, Client, WorkOrder, WorkOrderItem, Service
from sqlalchemy.orm import Session
from typing import Optional

class OrderService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_order(self, license_plate: str, wheel_diameter: str, 
                     vehicle_type: str = 'car', client_number: Optional[str] = None, 
                     client_name: Optional[str] = None, client_phone: Optional[str] = None) -> WorkOrder:
        try:
            car = self.db.query(Car).filter(Car.license_plate == license_plate).first()
            if not car:
                car = Car(license_plate=license_plate)
                self.db.add(car)
                self.db.flush()
            
            client_id = None
            if client_number or client_name or client_phone:
                client = Client(client_number=client_number, name=client_name, phone=client_phone)
                self.db.add(client)
                self.db.flush()
                client_id = client.id
            
            auto_discount = bool(client_name and client_phone)
            
            order = WorkOrder(
                car_id=car.id,
                client_id=client_id,
                wheel_diameter=wheel_diameter,
                vehicle_type=vehicle_type,
                auto_discount=auto_discount,
                status='draft'
            )
            self.db.add(order)
            self.db.commit()
            self.db.refresh(order)
            return order
        except Exception as e:
            self.db.rollback()
            raise
    
    def add_service_to_order(self, order_id: int, service_id: int) -> WorkOrderItem:
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            service = self.db.query(Service).filter(Service.id == service_id).first()
            
            if not order or not service:
                raise ValueError("Наряд или услуга не найдены")
            
            # Проверяем существует ли уже такая услуга
            existing_item = self.db.query(WorkOrderItem).filter(
                WorkOrderItem.work_order_id == order_id,
                WorkOrderItem.service_id == service_id
            ).first()
            
            if existing_item:
                # Увеличиваем количество
                existing_item.quantity += 1
                self.db.commit()
                self.db.refresh(existing_item)
                return existing_item
            
            # Создаем новую позицию
            diameter = order.wheel_diameter.lower()
            price_field = f'price_{diameter}'
            price = getattr(service, price_field, 0.0)
            
            item = WorkOrderItem(
                work_order_id=order_id,
                service_id=service_id,
                quantity=1,
                price=price,
                discount_percent=0
            )
            self.db.add(item)
            self.db.commit()
            self.db.refresh(item)
            return item
        except Exception as e:
            self.db.rollback()
            raise
    
    def update_item_discount(self, item_id: int, discount: int, comment: str = None):
        try:
            item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
            if item:
                item.discount_percent = discount
                if comment:
                    item.comment = comment
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def update_item_price(self, item_id: int, new_price: float, discount: int = None, comment: str = None):
        try:
            item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
            if item:
                item.price = new_price
                if discount is not None:
                    item.discount_percent = discount
                if comment is not None:
                    item.comment = comment
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def delete_item(self, item_id: int):
        try:
            item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
            if item:
                self.db.delete(item)
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def update_rim_discount(self, order_id: int, discount: int):
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order:
                order.rim_discount = discount
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def update_general_discount(self, order_id: int, discount: int):
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order:
                order.general_discount = discount
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def calculate_total(self, order_id: int) -> float:
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            return 0.0
        
        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        
        subtotal = 0
        for item in items:
            # Учитываем количество и скидку на позицию
            item_price = item.price * item.quantity * (1 - item.discount_percent / 100)
            subtotal += item_price
        
        # Скидки заменяют друг друга, а не суммируются
        # Приоритет: general_discount > rim_discount > auto_discount
        final_discount = 0
        if order.general_discount > 0:
            final_discount = order.general_discount
        elif order.rim_discount > 0:
            final_discount = order.rim_discount
        elif order.auto_discount:
            final_discount = 5
        
        discount_amount = subtotal * (final_discount / 100)
        total = subtotal - discount_amount
        return round(total, 2)
    
    def get_order_items(self, order_id: int):
        return self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
    
    def get_all_services(self):
        return self.db.query(Service).filter(Service.is_active == True).all()
