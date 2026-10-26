from models import Car, Client, WorkOrder, WorkOrderItem, Service, WorkShift
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from services.shift_service import ShiftService
from services.client_service import ClientService
from datetime import timedelta
from utils import normalize_plate, money_round, get_moscow_time, as_naive

class OrderService:
    def __init__(self, db: Session):
        self.db = db
        self.shift_service = ShiftService(db)
        self.client_service = ClientService(db)

    def create_order(self, license_plate: str, wheel_diameter: str,
                     vehicle_type: Optional[str] = 'car', client_number: Optional[str] = None,
                     client_name: Optional[str] = None, client_phone: Optional[str] = None,
                     client_id: Optional[int] = None,
                     create_client: bool = True,
                     wheels_assembled: Optional[bool] = None,
                     directions: Optional[list] = None,
                     wash_class: Optional[str] = None) -> WorkOrder:
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

            from services import directions as _directions
            chosen = _directions.parse(','.join(directions or ['tire']))

            car = self.db.query(Car).filter(Car.license_plate == plate).first()
            # None — «какой знаем»: наряд из записи или очереди тип не
            # спрашивает, и затирать джип «легковым» нельзя (ревью 26.10.2026)
            if vehicle_type is None:
                vehicle_type = (car.vehicle_type if car is not None and car.vehicle_type
                                else 'car')
            if not car:
                car = Car(license_plate=plate, vehicle_type=vehicle_type,
                          wheel_diameter=wheel_diameter or None)
                self.db.add(car)
                self.db.flush()
            else:
                # Обновляем параметры машины при каждом создании наряда.
                # Наряд только на мойку диаметр не спрашивает — известный
                # не затираем
                car.vehicle_type = vehicle_type
                if wheel_diameter:
                    car.wheel_diameter = wheel_diameter
                self.db.flush()

            # Класс для мойки запоминаем за машиной: спросили один раз
            if wash_class:
                car.wash_class = wash_class
                self.db.flush()
            if _directions.WASH in chosen and not (wash_class or car.wash_class):
                raise ValueError("Для мойки выберите класс машины")

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

            # Получаем список сотрудников на смене. Если мастеров выбирают
            # на наряд (тумблер в настройках), список пуст — его заполнят
            # в самом наряде теми, кто работает на посту
            active_shifts = self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
            employee_ids_list = [str(shift.employee_id) for shift in active_shifts]
            if _directions.tire_assign(self.db):
                employee_ids_list = []
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
                shift_id=shift_id,
                directions=_directions.join(chosen),
                wash_class=wash_class or car.wash_class
            )
            self.db.add(order)
            self.db.commit()
            self.db.refresh(order)

            # Мойка занимает свой пост — первый свободный
            if _directions.WASH in chosen:
                from services.wash_posts import WashPosts
                order.wash_post_number = WashPosts(self.db).first_free()
                self.db.commit()

            # Машина должна появиться на телефоне мастера сразу, а не
            # через десять минут: он подходит к ней прямо сейчас, и
            # пустой список для него значит «не работает»
            self._tell_server('машина заехала')

            return order
        except Exception as e:
            self.db.rollback()
            raise
    
    def add_service_to_order(self, order_id: int, service_id: int,
                             wheels=None) -> WorkOrderItem:
        """
        Добавить услугу в наряд.

        wheels — колёса, отмеченные на схеме (ремонт, правка). Сколько
        колёс отмечено, столько и выполнений: правка двух дисков — это
        две правки. Повтор той же услуги дописывает колёса к строке.
        """
        from services.wheel_service import parse, join

        wheels = parse(join(wheels or []))
        count = len(wheels) or 1
        try:
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            service = self.db.query(Service).filter(Service.id == service_id).first()
            
            if not order or not service:
                raise ValueError("Наряд или услуга не найдены")

            from services import directions as _directions
            wanted = getattr(service, 'direction', None) or 'tire'
            if wanted not in _directions.parse(order.directions):
                raise ValueError(
                    "Это услуга мойки — сначала «+ Мойка» в наряде" if wanted == 'wash'
                    else "Это услуга шиномонтажа — сначала «+ Шиномонтаж» в наряде")
            
            # Проверяем существует ли уже такая услуга
            existing_item = self.db.query(WorkOrderItem).filter(
                WorkOrderItem.work_order_id == order_id,
                WorkOrderItem.service_id == service_id
            ).first()
            
            if existing_item:
                # Увеличиваем количество
                existing_item.quantity += count
                if wheels:
                    existing_item.wheels = join(
                        parse(existing_item.wheels) + wheels)
                self.db.commit()
                self.db.refresh(existing_item)
                return existing_item
            
            # Создаем новую позицию. В гарантийной переделке работа — 0 ₽
            price = self.price_for(service, order.wheel_diameter, order.wash_class)
            if getattr(order, 'is_warranty', False) and not service.is_goods:
                price = 0.0
            
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
                quantity=count,
                wheels=join(wheels),
                price=price,
                discount_percent=initial_discount,
                # Снимок себестоимости: подорожание закупки не должно
                # менять уже начисленные зарплаты. У товара себестоимость —
                # это его закупочная цена
                consumable_cost=self._consumable_cost(service),
                is_goods=bool(service.is_goods),
                direction=getattr(service, 'direction', None) or 'tire',
            )
            # На смене один человек — назначаемая строка его, выбирать некого
            from services import directions as _directions
            if _directions.assigned(self.db, item.direction):
                from models import WorkShift
                on_shift = self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
                if len(on_shift) == 1:
                    item.employee_id = on_shift[0].employee_id
            self.db.add(item)
            self.db.commit()
            self.db.refresh(item)
            return item
        except Exception as e:
            self.db.rollback()
            raise
    
    @staticmethod
    def _tell_server(reason):
        """
        Позвать срочный обмен. Молча, если позвать не вышло.

        Досылка — ускорение, а не обязанность: уронить заведение наряда
        из-за того, что не получилось выйти на связь, было бы обменом
        наоборот.
        """
        try:
            from services import sync_nudge

            sync_nudge.request(reason)
        except Exception:
            pass

    def set_item_wheels(self, item_id: int, wheels) -> WorkOrderItem:
        """
        Переотметить колёса у строки. Количество — по числу колёс:
        ошиблись колесом — поправили, лишнее не оплачивается.

        Пустой список — «не знаем, какое колесо»: отметки снимаются,
        количество остаётся, как было.
        """
        from services.wheel_service import parse, join

        item = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.id == item_id).first()
        if item is None:
            raise ValueError('Позиция не найдена')
        wheels = parse(join(wheels or []))
        item.wheels = join(wheels)
        if wheels:
            item.quantity = len(wheels)
        self.db.commit()
        return item

    def _consumable_cost(self, service):
        """
        Снимок расходника строки. У товара — его закупка. Склад включён и
        у услуги прописан расход материалов — по расходу и отпускной цене;
        иначе — сумма у услуги, как было.
        """
        if service.is_goods:
            return service.purchase_price or 0.0
        from services.stock_service import StockService
        cost = StockService(self.db).consumable_cost_for(service)
        return cost if cost is not None else (service.consumable_cost or 0.0)

    @staticmethod
    def price_for(service, diameter, wash_class=None):
        """
        Цена позиции для этого диаметра.

        У товара цена одна: вентиль не стоит по-разному под R15 и R17.
        Единая цена разрешена и обычной услуге — мойка одного колеса
        тоже бывает без разбора диаметра. Мойка машины — по классу:
        седан, кроссовер, джип, минивэн.
        """
        if service.flat_price is not None:
            return service.flat_price

        if getattr(service, 'direction', None) == 'wash':
            if not wash_class:
                return 0.0
            return getattr(service, f'price_{wash_class}', 0.0) or 0.0

        return getattr(service, f'price_{(diameter or "").lower()}', 0.0) or 0.0

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
        База, от которой начисляется зарплата: работа минус расходники.

        Товары в базу не входят вовсе. Вентиль мастер не делал, он его
        достал с полки, и процент с перепродажи — это не зарплата за
        работу, а скидка себе в убыток.

        Не опускается ниже нуля: если материалы вышли дороже работы,
        механик не должен уходить в минус.
        """
        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id).all()

        from services.salary_service import SalaryService
        salary = SalaryService(self.db)
        base = 0.0
        for item in items:
            if getattr(item, 'is_goods', False):
                continue
            base += salary._base(item)

        return round(max(0.0, base), 2)

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
        # Машина из очереди или записи пришла с пакетом: на дисках —
        # полчаса, только шины — час. Меньше пакета план не бывает
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        package = (order.package_minutes or 0) if order else 0
        return int(max(base + services_minutes, package))

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

        # Клиент смотрит очередь в кабинете: «в работе» должно стать
        # видно тогда же, когда машина встала на пост
        self._tell_server('машина встала на пост')

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
    
    def add_direction(self, order_id, direction, wash_class=None, wheel_diameter=None):
        """
        Дополнить наряд вторым направлением: приехал на шиномонтаж и решил
        помыться, или наоборот. Мойке нужен класс машины, шиномонтажу —
        диаметр. Направление занимает свой первый свободный пост.
        """
        from services import directions as _directions
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if order is None:
            raise ValueError("Наряд не найден")
        have = _directions.parse(order.directions)
        if direction in have:
            return order
        if direction == _directions.WASH:
            wash_class = wash_class or order.wash_class or (order.car.wash_class if order.car else None)
            if not wash_class:
                raise ValueError("Для мойки выберите класс машины")
            order.wash_class = wash_class
            if order.car is not None:
                order.car.wash_class = wash_class
            from services.wash_posts import WashPosts
            order.wash_post_number = WashPosts(self.db).first_free()
        else:
            diameter = wheel_diameter or order.wheel_diameter or (order.car.wheel_diameter if order.car else None)
            if not diameter:
                raise ValueError("Для шиномонтажа выберите диаметр")
            order.wheel_diameter = diameter
            if order.car is not None and wheel_diameter:
                order.car.wheel_diameter = wheel_diameter
            from services.live_queue_service import LiveQueueService
            queue = LiveQueueService(self.db)
            if queue.enabled():
                order.post_number = queue.first_free_post()
        order.directions = _directions.join(have + [direction])
        self.db.commit()
        return order

    def set_item_employee(self, item_id, employee_id):
        """Кто делал строку мойки — ему и начислится."""
        item = self.db.query(WorkOrderItem).filter(WorkOrderItem.id == item_id).first()
        if item is None:
            raise ValueError("Позиция не найдена")
        item.employee_id = employee_id
        self.db.commit()
        return item

    def set_order_masters(self, order_id, employee_ids):
        """Мастера шиномонтажа этого наряда — те, кто работает на посту."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if order is None:
            raise ValueError("Наряд не найден")
        ids = [str(int(e)) for e in dict.fromkeys(employee_ids)]
        order.employee_ids = ','.join(ids) if ids else None
        self.db.commit()
        return order

    def assign_wash(self, order_id, employee_id, direction='wash'):
        """Все услуги направления в наряде — на одного сотрудника."""
        items = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.work_order_id == order_id,
            WorkOrderItem.direction == direction).all()
        for item in items:
            item.employee_id = employee_id
        self.db.commit()
        return len(items)

    def unpaid_orders(self, days=7):
        """
        Неоплаченные наряды за последние дни — их открываем при запуске:
        машину приняли вчера, а закрыть её должны иметь возможность и
        сегодня, после перезапуска программы.
        """
        since = get_moscow_time() - timedelta(days=days)
        return self.db.query(WorkOrder).filter(
            WorkOrder.status != 'paid',
            WorkOrder.is_deleted.isnot(True),
            WorkOrder.created_at >= since).order_by(WorkOrder.id).all()

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

            # Оплаченный наряд не удаляется — по нему только возврат:
            # зарплата пересчитывается, деньги возвращаются клиенту, склад
            # и касса остаются верными (решение владельца 26.10.2026)
            if order.status == 'paid':
                return False, (f"Наряд №{order_id} оплачен — удалить его нельзя. "
                               f"Оформите возврат: зарплата пересчитается, деньги "
                               f"вернутся клиенту")
            
            # Помечаем наряд как удалённый
            order.is_deleted = True
            order.deleted_at = get_moscow_time()
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

            from services.live_queue_service import LiveQueueService
            LiveQueueService(self.db).order_removed(order_id)

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

            # Наличные возвращаются из кассы — нужна открытая смена: в
            # ней и запишется расходный ордер (docs/cash.md)
            from services.cash_service import CashService
            cash = CashService(self.db)
            if order.payment_method == 'cash' and cash.current_shift() is None:
                return False, "Откройте смену: наличные возвращаются из кассы"

            # Откатываем зарплату соразмерно возвращаемой доле
            share = amount / paid if paid else 0
            # Последний возврат снимает весь остаток: округление долей
            # иначе оставляло мастеру копейку с полностью возвращённого
            final = round(already + amount, 2) >= round(paid, 2)
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
                back = round(current if final else min(current, accrued.get(employee_id, 0) * share), 2)
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
            if order.payment_method == 'cash':
                cash.from_refund(order, amount)

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
            # Вернули наряд целиком — списанное возвращается на склад
            if full:
                try:
                    from services.stock_service import StockService
                    StockService(self.db).return_order(order_id)
                except Exception as e:
                    self.db.rollback()
                    from logger import log
                    log.error(f"Склад не вернулся по наряду №{order_id}: {e}")
            message = (f"{title} проведён: {amount:.2f} руб."
                       + ("" if full else f"\nОстаток по наряду: "
                                          f"{paid - order.refunded_amount:.2f} руб."))
            if reversed_count:
                message += f"\nОткачено начислений ЗП: {reversed_count}"
            return True, message

        except Exception as e:
            self.db.rollback()
            return False, f"Ошибка при возврате: {str(e)}"

    def create_warranty(self, order_id: int, reason: str = ''):
        """
        Гарантийная переделка: новый наряд на ту же машину и того же
        клиента, с теми же услугами по 0 ₽ (решение владельца 26.10.2026).

        Исходный наряд не трогаем — за него заплатили, и он остаётся как
        был. Переделку пробивают как обычный наряд: работа бесплатна, а
        поставленный заново товар — по цене.
        """
        from services.wheel_service import parse as parse_wheels
        from services import directions as _directions

        original = self.db.query(WorkOrder).filter_by(id=order_id).first()
        if original is None:
            raise ValueError(f"Наряд №{order_id} не найден")
        if original.status != 'paid':
            raise ValueError(f"Наряд №{order_id} не оплачен — переделывать по гарантии нечего")
        if original.is_warranty:
            raise ValueError(f"Наряд №{order_id} сам гарантийный — выберите исходный наряд")
        plate = original.car.license_plate if original.car else None
        if not plate:
            raise ValueError("У наряда нет машины")

        order = self.create_order(
            plate, original.wheel_diameter or '', original.vehicle_type,
            client_id=original.client_id, create_client=False,
            directions=_directions.parse(original.directions),
            wash_class=original.wash_class)
        order.is_warranty = True
        order.warranty_of_id = original.id
        order.warranty_reason = (reason or '').strip()[:500] or None
        self.db.commit()

        for item in original.items:
            if item.service is None or getattr(item, 'is_goods', False):
                continue
            line = self.add_service_to_order(order.id, item.service_id,
                                             wheels=parse_wheels(item.wheels) or None)
            if line is not None and not item.wheels and (item.quantity or 1) > 1:
                line.quantity = item.quantity
        self.db.commit()

        from services.audit_service import AuditService
        AuditService(self.db).log(
            'order.warranty',
            f"Гарантийная переделка по наряду №{order_id} ({plate}): наряд №{order.id}"
            + (f". Причина: {order.warranty_reason}" if order.warranty_reason else ''),
            entity_type='work_order', entity_id=order.id)
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

            from services.live_queue_service import LiveQueueService
            LiveQueueService(self.db).order_removed(order_id)

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
