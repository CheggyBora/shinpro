from models import Car, Client, WorkOrder, WorkOrderItem, Service, WorkShift
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from services.shift_service import ShiftService
from services.client_service import ClientService
from utils import normalize_plate, money_round, get_moscow_time, as_naive

class OrderService:
    def __init__(self, db: Session):
        self.db = db
        self.shift_service = ShiftService(db)
        self.client_service = ClientService(db)

    def create_order(self, license_plate: str, wheel_diameter: str,
                     vehicle_type: str = 'car', client_number: Optional[str] = None,
                     client_name: Optional[str] = None, client_phone: Optional[str] = None,
                     client_id: Optional[int] = None,
                     create_client: bool = True,
                     wheels_assembled: Optional[bool] = None) -> WorkOrder:
        """
        Создать наряд.

        Клиента можно задать двумя способами:
          - client_id — привязать к уже выбранному в интерфейсе клиенту;
          - client_name / client_phone — найти по телефону или завести нового.

        create_client=False создаёт наряд вообще без клиента (нужно для
        нарядов хранения шин, чтобы не засорять базу служебными записями).
        """
        try:
            # Номер приводим к единому виду, иначе "а123вв777" и "A123BB777"
            # заведут две разные машины и история визитов потеряется
            plate = normalize_plate(license_plate)
            if not plate:
                raise ValueError("Не указан номер автомобиля")

            car = self.db.query(Car).filter(Car.license_plate == plate).first()
            if not car:
                car = Car(license_plate=plate, vehicle_type=vehicle_type, wheel_diameter=wheel_diameter)
                self.db.add(car)
                self.db.flush()
            else:
                # Обновляем параметры машины при каждом создании наряда
                car.vehicle_type = vehicle_type
                car.wheel_diameter = wheel_diameter
                self.db.flush()

            # Колёса в сборе запоминаем за машиной. Если в этот раз не
            # выясняли, ранее известное значение не затираем.
            if wheels_assembled is not None:
                car.wheels_assembled = wheels_assembled
                self.db.flush()

            client = None
            if client_id is not None:
                # Клиент явно выбран в интерфейсе
                client = self.db.query(Client).filter(Client.id == client_id).first()
                if not client:
                    raise ValueError(f"Клиент #{client_id} не найден")
            elif create_client:
                # Ищем по телефону, заводим нового только если такого ещё нет
                client, _ = self.client_service.get_or_create(
                    name=client_name, phone=client_phone
                )

            if client is not None:
                if client_number and not client.client_number:
                    client.client_number = client_number
                # Закрепляем машину за клиентом, если она ещё ничья
                if car.client_id is None:
                    car.client_id = client.id
                self.db.flush()

            client_id = client.id if client else None

            # Автоскидка положена, когда о клиенте известно и имя, и телефон
            auto_discount = bool(client and client.name and client.phone)

            # Получаем список сотрудников на смене
            active_shifts = self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
            employee_ids_list = [str(shift.employee_id) for shift in active_shifts]
            employee_ids_str = ','.join(employee_ids_list) if employee_ids_list else None
            
            # Получаем текущую смену и присваиваем shift_id
            current_shift = self.shift_service.get_current_shift()
            shift_id = current_shift.id if current_shift else None
            
            order = WorkOrder(
                car_id=car.id,
                client_id=client_id,
                wheel_diameter=wheel_diameter,
                vehicle_type=vehicle_type,
                auto_discount=auto_discount,
                status='draft',
                employee_ids=employee_ids_str,
                shift_id=shift_id
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

            # Не превышаем максимум, разрешённый для этой услуги
            service_limit = 100 if service.max_discount_percent is None else service.max_discount_percent
            initial_discount = min(max(discount_candidates), service_limit)
            
            item = WorkOrderItem(
                work_order_id=order_id,
                service_id=service_id,
                quantity=1,
                price=price,
                discount_percent=initial_discount,
                # Снимок себестоимости: подорожание закупки не должно
                # менять уже начисленные зарплаты
                consumable_cost=service.consumable_cost or 0.0
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
    
    # ------------------------------------------------------------------
    # Скидки
    # ------------------------------------------------------------------

    @staticmethod
    def max_discount_for(item) -> int:
        """Наибольшая скидка, допустимая для услуги в этой позиции."""
        if not item or not item.service:
            return 100
        value = item.service.max_discount_percent
        return 100 if value is None else int(value)

    def set_item_discount(self, item_id: int, discount: int):
        """
        Поставить скидку по отдельной позиции вручную.

        Значение ограничено максимумом, заданным у услуги. Позиция
        помечается как заданная вручную, и общая скидка на наряд её
        больше не перезаписывает: кассир выставил число осознанно.
        """
        item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
        if not item:
            raise ValueError(f"Позиция №{item_id} не найдена")

        discount = int(discount)
        if discount < 0:
            raise ValueError("Скидка не может быть отрицательной")

        limit = self.max_discount_for(item)
        if discount > limit:
            raise ValueError(
                f"Для услуги «{item.service.name}» максимальная скидка {limit}%"
            )

        try:
            item.discount_percent = discount
            # Ноль вручную — это тоже осознанное решение «скидки нет»,
            # поэтому пометку не снимаем
            item.discount_manual = True
            self.db.commit()
            return item
        except Exception:
            self.db.rollback()
            raise

    def clear_item_discount_override(self, item_id: int):
        """Вернуть позицию под управление общими скидками наряда."""
        item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
        if item:
            item.discount_manual = False
            self.db.commit()
        return item

    def delete_item(self, item_id: int):
        try:
            item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
            if item:
                self.db.delete(item)
                self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
    
    def _apply_order_discounts(self, order):
        """
        Пересчитать скидку по всем позициям наряда.

        Общая логика для скидки на диски и общей скидки — раньше она была
        скопирована в двух местах и расходилась.

        Два правила:
          - позицию с ручной скидкой не трогаем: значение выставил человек;
          - результат ограничен максимумом, заданным у услуги, иначе смысл
            ограничения теряется.
        """
        items = self.db.query(WorkOrderItem).options(
            joinedload(WorkOrderItem.service)
        ).filter(WorkOrderItem.work_order_id == order.id).all()

        for item in items:
            if item.discount_manual:
                continue  # скидку по этой позиции задали вручную

            candidates = [0]

            # Автоскидка за полные данные клиента
            if order.auto_discount:
                candidates.append(5)

            # Общая скидка на наряд
            if order.general_discount and order.general_discount > 0:
                candidates.append(order.general_discount)

            # Скидка на диски — только для правки литого диска
            if (item.service and item.service.name == 'Правка литого диска'
                    and order.rim_discount and order.rim_discount > 0):
                candidates.append(order.rim_discount)

            item.discount_percent = min(max(candidates), self.max_discount_for(item))

    def update_rim_discount(self, order_id: int, discount: int):
        """Скидка на диски: применяется только к правке литого диска."""
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order:
                order.rim_discount = discount
                self._apply_order_discounts(order)
                self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def update_general_discount(self, order_id: int, discount: int):
        """Общая скидка на весь наряд."""
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            if order:
                order.general_discount = discount
                self._apply_order_discounts(order)
                self.db.commit()
        except Exception:
            self.db.rollback()
            raise
    
    # ------------------------------------------------------------------
    # Расчёт стоимости
    #
    # Эти три функции — единственное место, где считаются деньги.
    # И касса, и чек пользуются ими, поэтому строки чека всегда
    # складываются ровно в ту сумму, которую платит клиент.
    # Раньше чек округлял цены сам по себе, и «Сумма минус скидка»
    # не сходилась с «Итого к оплате».
    # ------------------------------------------------------------------

    @staticmethod
    def item_unit_price(item) -> float:
        """Цена за единицу со скидкой, округлённая до рубля."""
        return money_round(item.price * (1 - item.discount_percent / 100))

    @staticmethod
    def item_total(item) -> float:
        """Стоимость позиции: округлённая цена за единицу умножается на количество."""
        return OrderService.item_unit_price(item) * item.quantity

    @staticmethod
    def item_total_without_discount(item) -> float:
        """Стоимость позиции без всяких скидок — для строки «Сумма» в чеке."""
        return money_round(item.price) * item.quantity

    @staticmethod
    def item_consumables(item) -> float:
        """
        Себестоимость расходников по позиции.

        Считается от снимка, сохранённого при добавлении услуги в наряд,
        а не от текущей цены в справочнике. Скидка клиенту на неё не влияет:
        грибок не дешевеет от того, что клиенту дали 15%.
        """
        return round((item.consumable_cost or 0.0) * item.quantity, 2)

    def calculate_consumables(self, order_id: int) -> float:
        """Сумма расходников по всему наряду."""
        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id
        ).all()
        return round(sum(self.item_consumables(item) for item in items), 2)

    def calculate_salary_base(self, order_id: int) -> float:
        """
        База, от которой начисляется зарплата: итог к оплате минус расходники.

        Не опускается ниже нуля: если материалы вышли дороже работы,
        механик не должен уходить в минус.
        """
        total = self.calculate_total(order_id)
        consumables = self.calculate_consumables(order_id)
        return round(max(0.0, total - consumables), 2)

    def calculate_total(self, order_id: int) -> float:
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            return 0.0

        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()

        # Все скидки (автоскидка, общая, на диски) уже учтены
        # в discount_percent каждой позиции
        return sum(self.item_total(item) for item in items)
    
    # ------------------------------------------------------------------
    # Время работ
    # ------------------------------------------------------------------

    def calculate_planned_minutes(self, order_id: int) -> int:
        """
        Сколько минут займёт наряд по текущему составу.

        Базовое время (приём, оформление, заезд и выезд с поста)
        плюс длительность каждой услуги на её количество.
        От диаметра колеса не зависит.
        """
        from services.settings_service import SettingsService

        base = SettingsService(self.db).get_int('order_base_minutes')
        items = self.db.query(WorkOrderItem).options(
            joinedload(WorkOrderItem.service)
        ).filter(WorkOrderItem.work_order_id == order_id).all()

        services_minutes = sum(
            (item.service.duration_minutes or 0) * item.quantity for item in items
        )
        return int(base + services_minutes)

    def has_unsaved_time_changes(self, order_id: int) -> bool:
        """Отличается ли текущий состав от того, по которому считается очередь."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            return False
        return (order.planned_minutes or 0) != self.calculate_planned_minutes(order_id)

    def save_order_composition(self, order_id: int) -> int:
        """
        Зафиксировать состав наряда: пересчитать плановое время.

        Это НЕ запись в базу — позиции сохраняются сразу при добавлении.
        Кнопка означает «состав согласован с клиентом», и только после неё
        меняется время в очереди. Иначе прогноз для всех ожидающих скакал бы
        каждый раз, когда мастер забивает услугу, чтобы озвучить цену.
        """
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            raise ValueError(f"Наряд №{order_id} не найден")

        order.planned_minutes = self.calculate_planned_minutes(order_id)
        self.db.commit()
        return order.planned_minutes

    def start_work(self, order_id: int):
        """
        Взять наряд в работу: зафиксировать начало и согласовать состав.

        Согласование здесь массовое — обычный случай «машина приехала,
        мастер накидал услуги, начал работу» не требует лишних нажатий.
        """
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            raise ValueError(f"Наряд №{order_id} не найден")

        if order.started_at is None:
            order.started_at = get_moscow_time()
        order.paused_at = None
        order.planned_minutes = self.calculate_planned_minutes(order_id)
        order.status = 'in_progress' if order.status == 'draft' else order.status
        self.db.commit()
        return order

    def pause_work(self, order_id: int):
        """Приостановить: ждём деталь или клиента. Счётчик времени встаёт."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order or order.paused_at is not None:
            return order

        order.paused_at = get_moscow_time()
        self.db.commit()
        return order

    def resume_work(self, order_id: int):
        """Продолжить после паузы, прибавив простой к накопленному."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order or order.paused_at is None:
            return order

        pause = as_naive(get_moscow_time()) - as_naive(order.paused_at)
        order.paused_minutes = (order.paused_minutes or 0) + int(pause.total_seconds() // 60)
        order.paused_at = None
        self.db.commit()
        return order

    def finish_work(self, order_id: int):
        """Работы закончены. Время фиксируется для уточнения нормативов."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            raise ValueError(f"Наряд №{order_id} не найден")

        if order.paused_at is not None:
            self.resume_work(order_id)

        order.finished_at = get_moscow_time()
        self.db.commit()
        return order

    @staticmethod
    def actual_minutes(order):
        """
        Сколько на самом деле заняла работа, без времени пауз.

        Возвращает None, если работа не начиналась или не закончена.
        """
        if not order or not order.started_at or not order.finished_at:
            return None

        worked = as_naive(order.finished_at) - as_naive(order.started_at)
        minutes = worked.total_seconds() / 60 - (order.paused_minutes or 0)
        return max(0, int(round(minutes)))

    def get_order_items(self, order_id: int):
        # Явно подгружаем связанную таблицу service с актуальными данными
        return self.db.query(WorkOrderItem).options(joinedload(WorkOrderItem.service)).filter(WorkOrderItem.work_order_id == order_id).all()
    
    def get_all_services(self):
        return self.db.query(Service).filter(Service.is_active == True).all()
    
    def get_all_license_plates(self):
        """Получить список всех уникальных номеров машин"""
        cars = self.db.query(Car.license_plate).distinct().order_by(Car.license_plate).all()
        return [car.license_plate for car in cars]
    
    def get_car_by_license_plate(self, license_plate: str):
        """Получить машину по номеру для автоподстановки параметров.

        Номер ищется в любом написании: "а123вв777" найдёт "А123ВВ777".
        """
        plate = normalize_plate(license_plate)
        if not plate:
            return None
        return self.db.query(Car).filter(Car.license_plate == plate).first()

    def get_last_order_for_car(self, license_plate: str):
        """Получить последний наряд для машины по номеру (в любом написании)"""
        car = self.get_car_by_license_plate(license_plate)
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

            from services.audit_service import AuditService
            AuditService(self.db).log(
                AuditService.ORDER_DELETE,
                f"Наряд №{order_id} ({order.car.license_plate if order.car else '?'}) "
                f"на {order.total_amount or 0:.0f} руб. Причина: {order.deleted_reason}. "
                f"Отменено начислений ЗП: {reversed_count}",
                entity_type='work_order', entity_id=order_id
            )

            message = f"Наряд №{order_id} успешно удалён"
            if reversed_count > 0:
                message += f"\nОтменено начислений ЗП: {reversed_count}"

            return True, message
            
        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при удалении наряда: {str(e)}"
    
    # ------------------------------------------------------------------
    # Возврат и сторно
    # ------------------------------------------------------------------

    REFUND = 'refund'        # вернули деньги клиенту
    REVERSAL = 'reversal'    # сторно: пробили по ошибке

    def refund_order(self, order_id: int, amount: float = None,
                     reason: str = '', refund_type: str = REFUND):
        """
        Вернуть деньги по наряду полностью или частично.

        Наряд НЕ удаляется: работа выполнялась, и в истории это должно
        остаться видно. Уменьшается только сумма, попадающая в выручку,
        и соразмерно откатываются начисления зарплаты.

        Возвращает (успех, сообщение).
        """
        from models import SalaryTransaction

        try:
            order = self.db.query(WorkOrder).filter_by(id=order_id).first()
            if not order:
                return False, f"Наряд №{order_id} не найден"

            if order.status != 'paid':
                return False, f"Наряд №{order_id} не оплачен — возвращать нечего"

            paid = float(order.total_amount or 0)
            already = float(order.refunded_amount or 0)
            available = round(paid - already, 2)

            if available <= 0:
                return False, f"По наряду №{order_id} уже возвращена вся сумма"

            amount = available if amount is None else round(float(amount), 2)

            if amount <= 0:
                return False, "Сумма возврата должна быть больше нуля"
            if amount > available:
                return False, (f"К возврату доступно {available:.2f} руб., "
                               f"запрошено {amount:.2f} руб.")

            # Откатываем зарплату соразмерно возвращаемой доле
            share = amount / paid if paid else 0
            transactions = self.db.query(SalaryTransaction).filter_by(
                work_order_id=order_id).all()

            # По каждому мастеру нужны две величины:
            #   accrued — сколько ему изначально начислили по наряду,
            #   current — сколько осталось после прежних откатов.
            # Долю возврата считаем от ИЗНАЧАЛЬНОГО начисления, иначе при
            # втором частичном возврате процент берётся от уже урезанной
            # суммы и зарплата никогда не доходит до нуля.
            accrued = {}
            current_by_employee = {}
            for transaction in transactions:
                employee_id = transaction.employee_id
                current_by_employee[employee_id] = current_by_employee.get(
                    employee_id, 0) + transaction.amount
                if transaction.amount > 0:
                    accrued[employee_id] = accrued.get(employee_id, 0) + transaction.amount

            reversed_count = 0
            for employee_id, current in current_by_employee.items():
                if current <= 0:
                    continue
                # Снимаем ту же долю, что возвращаем клиенту,
                # но не больше, чем у мастера осталось
                back = round(min(current, accrued.get(employee_id, 0) * share), 2)
                if back <= 0:
                    continue
                self.db.add(SalaryTransaction(
                    employee_id=employee_id,
                    work_order_id=order_id,
                    amount=-back,
                ))
                reversed_count += 1

            order.refunded_amount = round(already + amount, 2)
            order.refunded_at = get_moscow_time()
            order.refund_type = refund_type
            order.refund_reason = (reason or '').strip() or 'Не указана'

            self.db.commit()

            from services.audit_service import AuditService
            title = 'Сторно' if refund_type == self.REVERSAL else 'Возврат'
            AuditService(self.db).log(
                'order.refund',
                f"{title} по наряду №{order_id} "
                f"({order.car.license_plate if order.car else '?'}): "
                f"{amount:.2f} руб. Причина: {order.refund_reason}. "
                f"Откачено начислений: {reversed_count}",
                entity_type='work_order', entity_id=order_id)

            full = order.refunded_amount >= paid
            message = (f"{title} проведён: {amount:.2f} руб."
                       + ("" if full else f"\nОстаток по наряду: "
                                          f"{paid - order.refunded_amount:.2f} руб."))
            if reversed_count:
                message += f"\nОткачено начислений ЗП: {reversed_count}"
            return True, message

        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при возврате: {str(e)}"

    def set_warranty(self, order_id: int, is_warranty: bool = True, reason: str = ''):
        """
        Отметить наряд как гарантийную переделку.

        Такой наряд не участвует в выручке и среднем чеке, но виден
        в отчётах: по нему считают качество работы.
        """
        order = self.db.query(WorkOrder).filter_by(id=order_id).first()
        if not order:
            raise ValueError(f"Наряд №{order_id} не найден")

        order.is_warranty = bool(is_warranty)
        self.db.commit()

        from services.audit_service import AuditService
        AuditService(self.db).log(
            'order.warranty',
            f"Наряд №{order_id} "
            f"{'отмечен как гарантийная переделка' if is_warranty else 'снят с гарантии'}"
            + (f". Причина: {reason}" if reason else ''),
            entity_type='work_order', entity_id=order_id)
        return order

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
            
            plate = order.car.license_plate if order.car else '?'

            # Удаляем все позиции наряда
            self.db.query(WorkOrderItem).filter_by(work_order_id=order_id).delete()

            # Удаляем сам наряд
            self.db.delete(order)

            # Сохраняем изменения
            self.db.commit()

            from services.audit_service import AuditService
            AuditService(self.db).log(
                AuditService.ORDER_HARD_DELETE,
                f"Черновик наряда №{order_id} ({plate}) удалён из базы",
                entity_type='work_order', entity_id=order_id
            )

            return True, f"Наряд №{order_id} успешно удалён"
            
        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при удалении наряда: {str(e)}"
