from models import Car, Client, WorkOrder, WorkOrderItem, Service
from sqlalchemy.orm import Session

class OrderService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_order(self, license_plate: str, wheel_diameter: str, 
                     vehicle_type: str = 'car', client_number: str = None, client_name: str = None) -> WorkOrder:
        car = self.db.query(Car).filter(Car.license_plate == license_plate).first()
        if not car:
            car = Car(license_plate=license_plate)
            self.db.add(car)
            self.db.flush()
        
        client_id = None
        if client_number or client_name:
            client = Client(client_number=client_number, name=client_name)
            self.db.add(client)
            self.db.flush()
            client_id = client.id
        
        auto_discount = bool(client_number and client_name)
        
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
    
    def add_service_to_order(self, order_id: int, service_id: int) -> WorkOrderItem:
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        service = self.db.query(Service).filter(Service.id == service_id).first()
        
        if not order or not service:
            raise ValueError("Наряд или услуга не найдены")
        
        diameter = order.wheel_diameter.lower()
        price_field = f'price_{diameter}'
        price = getattr(service, price_field, 0.0)
        
        item = WorkOrderItem(
            work_order_id=order_id,
            service_id=service_id,
            price=price,
            discount_percent=0
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item
    
    def update_item_discount(self, item_id: int, discount: int, comment: str = None):
        item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
        if item:
            item.discount_percent = discount
            if comment:
                item.comment = comment
            self.db.commit()
    
    def delete_item(self, item_id: int):
        item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
        if item:
            self.db.delete(item)
            self.db.commit()
    
    def update_general_discount(self, order_id: int, discount: int):
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if order:
            order.general_discount = discount
            self.db.commit()
    
    def calculate_total(self, order_id: int) -> float:
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            return 0.0
        
        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        
        subtotal = 0
        for item in items:
            item_price = item.price * (1 - item.discount_percent / 100)
            subtotal += item_price
        
        general_discount_amount = subtotal * (order.general_discount / 100)
        subtotal_after_general = subtotal - general_discount_amount
        
        auto_discount_amount = 0
        if order.auto_discount:
            auto_discount_amount = subtotal_after_general * 0.05
        
        total = subtotal_after_general - auto_discount_amount
        return round(total, 2)
    
    def get_order_items(self, order_id: int):
        return self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
    
    def get_all_services(self):
        return self.db.query(Service).filter(Service.is_active == True).all()
