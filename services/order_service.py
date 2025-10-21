from models import Car, Client, WorkOrder, WorkOrderItem, Service, WorkShift
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
                car = Car(license_plate=license_plate, vehicle_type=vehicle_type, wheel_diameter=wheel_diameter)
                self.db.add(car)
                self.db.flush()
            else:
                # Обновляем параметры машины при каждом создании наряда
                car.vehicle_type = vehicle_type
                car.wheel_diameter = wheel_diameter
                self.db.flush()
            
            client_id = None
            if client_number or client_name or client_phone:
                client = Client(client_number=client_number, name=client_name, phone=client_phone)
                self.db.add(client)
                self.db.flush()
                client_id = client.id
            
            auto_discount = bool(client_name and client_phone)
            
            # Получаем список сотрудников на смене
            active_shifts = self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
            employee_ids_list = [str(shift.employee_id) for shift in active_shifts]
            employee_ids_str = ','.join(employee_ids_list) if employee_ids_list else None
            
            order = WorkOrder(
                car_id=car.id,
                client_id=client_id,
                wheel_diameter=wheel_diameter,
                vehicle_type=vehicle_type,
                auto_discount=auto_discount,
                status='draft',
                employee_ids=employee_ids_str
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
            
            # Определяем начальную скидку для новой позиции
            # Выбираем максимум из всех доступных скидок
            discount_candidates = [0]
            
            # Автоскидка 5%
            if order.auto_discount:
                discount_candidates.append(5)
            
            # Общая скидка
            if order.general_discount > 0:
                discount_candidates.append(order.general_discount)
            
            # Скидка на диски (только для "Правка литого диска")
            if service.name == 'Правка литого диска' and order.rim_discount > 0:
                discount_candidates.append(order.rim_discount)
            
            initial_discount = max(discount_candidates)
            
            item = WorkOrderItem(
                work_order_id=order_id,
                service_id=service_id,
                quantity=1,
                price=price,
                discount_percent=initial_discount
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
    
    def update_item_full(self, item_id: int, quantity: int, price: float, discount: int, comment: str = None):
        try:
            item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
            if item:
                item.quantity = quantity
                item.price = price
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
        """
        Применяет скидку на диски только к услуге 'Правка литого диска'.
        Скидка на диски применяется с учётом других скидок (автоскидка 5%, общая скидка).
        """
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order:
                order.rim_discount = discount
                
                # Применяем скидку к услугам "Правка литого диска"
                items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
                for item in items:
                    if item.service.name == 'Правка литого диска':
                        # Собираем все доступные скидки для этой позиции
                        discount_candidates = [discount]
                        
                        # Автоскидка 5%
                        if order.auto_discount:
                            discount_candidates.append(5)
                        
                        # Общая скидка
                        if order.general_discount > 0:
                            discount_candidates.append(order.general_discount)
                        
                        # Выбираем максимальную скидку
                        item.discount_percent = max(discount_candidates)
                
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def update_general_discount(self, order_id: int, discount: int):
        """
        Применяет общую скидку ко всем позициям наряда.
        Общая скидка применяется с учётом индивидуальных скидок (автоскидка 5%, скидка на диски).
        """
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order:
                order.general_discount = discount
                
                # Применяем скидку ко всем позициям
                items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
                for item in items:
                    # Собираем все доступные скидки для этой позиции
                    discount_candidates = [discount]
                    
                    # Автоскидка 5%
                    if order.auto_discount:
                        discount_candidates.append(5)
                    
                    # Скидка на диски (только для "Правка литого диска")
                    if item.service.name == 'Правка литого диска' and order.rim_discount > 0:
                        discount_candidates.append(order.rim_discount)
                    
                    # Выбираем максимальную скидку
                    item.discount_percent = max(discount_candidates)
                
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def calculate_total(self, order_id: int) -> float:
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            return 0.0
        
        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        
        total = 0
        for item in items:
            # Учитываем количество и скидку на позицию
            # Все скидки (автоскидка, общая, на диски) уже учтены в discount_percent каждой позиции
            item_price = item.price * item.quantity * (1 - item.discount_percent / 100)
            total += item_price
        
        return round(total, 2)
    
    def get_order_items(self, order_id: int):
        from sqlalchemy.orm import joinedload
        # Явно подгружаем связанную таблицу service с актуальными данными
        return self.db.query(WorkOrderItem).options(joinedload(WorkOrderItem.service)).filter(WorkOrderItem.work_order_id == order_id).all()
    
    def get_all_services(self):
        return self.db.query(Service).filter(Service.is_active == True).all()
    
    def get_all_license_plates(self):
        """Получить список всех уникальных номеров машин"""
        cars = self.db.query(Car.license_plate).distinct().order_by(Car.license_plate).all()
        return [car.license_plate for car in cars]
    
    def get_car_by_license_plate(self, license_plate: str):
        """Получить машину по номеру для автоподстановки параметров"""
        return self.db.query(Car).filter(Car.license_plate == license_plate).first()
    
    def get_last_order_for_car(self, license_plate: str):
        """Получить последний наряд для машины по номеру"""
        car = self.db.query(Car).filter(Car.license_plate == license_plate).first()
        if not car:
            return None
        
        # Получаем последний наряд для этой машины
        last_order = self.db.query(WorkOrder).filter(
            WorkOrder.car_id == car.id
        ).order_by(WorkOrder.created_at.desc()).first()
        
        return last_order
    
    def delete_work_order(self, order_id: int, reason: str = ""):
        """
        Мягкое удаление наряда с откатом начислений ЗП
        
        Args:
            order_id: ID наряда для удаления
            reason: Причина удаления (опционально)
        
        Returns:
            tuple: (success: bool, message: str)
        """
        from models import SalaryTransaction
        from datetime import datetime
        
        try:
            # Находим наряд
            order = self.db.query(WorkOrder).filter_by(id=order_id).first()
            if not order:
                return False, f"Наряд №{order_id} не найден"
            
            # Проверяем, не удалён ли уже
            if order.is_deleted:
                return False, f"Наряд №{order_id} уже удалён"
            
            # Помечаем наряд как удалённый
            order.is_deleted = True
            order.deleted_at = datetime.now()
            order.deleted_reason = reason if reason else "Не указана"
            
            # Находим все начисления ЗП по этому наряду
            salary_transactions = self.db.query(SalaryTransaction).filter_by(
                work_order_id=order_id
            ).all()
            
            # Создаём обратные транзакции (откат начислений)
            reversed_count = 0
            for transaction in salary_transactions:
                # Создаём транзакцию с отрицательной суммой
                reversal = SalaryTransaction(
                    employee_id=transaction.employee_id,
                    amount=-transaction.amount,  # Отрицательная сумма
                    work_order_id=order_id
                )
                self.db.add(reversal)
                reversed_count += 1
            
            # Сохраняем изменения
            self.db.commit()
            
            message = f"Наряд №{order_id} успешно удалён"
            if reversed_count > 0:
                message += f"\nОтменено начислений ЗП: {reversed_count}"
            
            return True, message
            
        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при удалении наряда: {str(e)}"
    
    def get_active_orders(self):
        """Получить все активные (неудалённые) наряды"""
        return self.db.query(WorkOrder).filter_by(is_deleted=False).all()
    
    def get_order_by_id(self, order_id: int, include_deleted: bool = False):
        """
        Получить наряд по ID
        
        Args:
            order_id: ID наряда
            include_deleted: Включать ли удалённые наряды
        """
        query = self.db.query(WorkOrder).filter_by(id=order_id)
        if not include_deleted:
            query = query.filter_by(is_deleted=False)
        return query.first()
    
    def hard_delete_unpaid_order(self, order_id: int):
        """
        Полное удаление непробитого наряда из базы данных
        
        Args:
            order_id: ID наряда для удаления
        
        Returns:
            tuple: (success: bool, message: str)
        """
        from models import SalaryTransaction
        
        try:
            # Находим наряд
            order = self.db.query(WorkOrder).filter_by(id=order_id).first()
            if not order:
                return False, f"Наряд №{order_id} не найден"
            
            # Проверяем, что наряд не оплачен (только draft можно удалять)
            if order.status != 'draft':
                return False, f"Наряд №{order_id} уже в работе или оплачен. Можно удалять только черновики."
            
            # Проверяем, что нет транзакций ЗП
            salary_transactions = self.db.query(SalaryTransaction).filter_by(
                work_order_id=order_id
            ).count()
            
            if salary_transactions > 0:
                return False, f"Наряд №{order_id} имеет начисления ЗП. Используйте функцию отмены."
            
            # Удаляем все позиции наряда
            self.db.query(WorkOrderItem).filter_by(work_order_id=order_id).delete()
            
            # Удаляем сам наряд
            self.db.delete(order)
            
            # Сохраняем изменения
            self.db.commit()
            
            return True, f"Наряд №{order_id} успешно удалён"
            
        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при удалении наряда: {str(e)}"
