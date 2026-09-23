"""
Работа с клиентами.

Клиент опознаётся по номеру телефона: это единственное, что не меняется
от визита к визиту. Раньше на каждый наряд заводилась новая запись клиента,
из-за чего база заполнялась дублями и история клиента не собиралась.

Один клиент может обслуживать несколько машин (Car.client_id).
"""
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import Client, Car, WorkOrder
from utils import normalize_phone, normalize_plate, format_phone


class ClientService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------

    def find_by_phone(self, phone: str):
        """
        Найти клиента по номеру телефона (в любом написании).

        "+7 (909) 901-89-31", "8 909 901 89 31" и "9099018931" найдут
        одного и того же клиента.
        """
        normalized = normalize_phone(phone)
        if not normalized:
            return None

        return self.db.query(Client).filter(Client.phone == normalized).first()

    def find_by_plate(self, license_plate: str):
        """Найти клиента по госномеру его машины (в любом написании)."""
        car = self.get_car(license_plate)
        return car.client if car and car.client else None

    def search(self, query: str, limit: int = 50):
        """
        Универсальный поиск клиента: по телефону, имени или госномеру машины.

        Кассиру не нужно выбирать вид поиска — вводит что помнит.
        Телефон ищется по вхождению, поэтому достаточно последних цифр.

        Результат отсортирован по точности: сначала владелец найденной машины,
        затем совпадения по телефону, затем по имени.
        """
        query = (query or '').strip()
        if not query:
            return []

        # dict сохраняет порядок добавления и убирает повторы
        found = {}

        # 1. По госномеру машины — самое точное совпадение, ставим первым
        car_owner = self.find_by_plate(query)
        if car_owner:
            found[car_owner.id] = car_owner

        # 2. По телефону.
        # Ищем сразу по двум написаниям: как ввели и в нормализованном виде.
        # Телефоны хранятся начинающимися с 7, поэтому набранный целиком
        # "8 909 901-89-31" по сырым цифрам не нашёлся бы. А для обрывка
        # вроде "8931" нормализация ничего не меняет, и работает поиск по вхождению.
        digits = ''.join(ch for ch in query if ch.isdigit())
        patterns = {p for p in (digits, normalize_phone(query)) if p}
        if patterns:
            matches = self.db.query(Client).filter(
                or_(*[Client.phone.like(f'%{p}%') for p in patterns])
            ).limit(limit).all()
            for client in matches:
                found[client.id] = client

        # 3. По имени — сравниваем на стороне Python.
        # SQLite не умеет приводить кириллицу к другому регистру: и LIKE,
        # и lower() работают только с латиницей, поэтому запрос "андрей"
        # не нашёл бы клиента "Андрей". Клиентов в базе немного,
        # перебрать их дешевле, чем городить обходные пути в SQL.
        if len(found) < limit:
            needle = query.lower()
            for client in self.db.query(Client).filter(Client.name.isnot(None)).all():
                if needle in client.name.lower():
                    found[client.id] = client
                    if len(found) >= limit:
                        break

        return list(found.values())[:limit]

    # ------------------------------------------------------------------
    # Создание и обновление
    # ------------------------------------------------------------------

    def get_or_create(self, name: str = None, phone: str = None):
        """
        Найти клиента по телефону или завести нового.

        Возвращает (client, created), где created=True если клиент новый.
        Возвращает (None, False) если не передано ни имени, ни телефона.

        Если клиент найден по телефону, а имя пришло новое — имя обновляется
        (человек мог представиться полнее, чем в прошлый раз).
        """
        name = (name or '').strip() or None
        normalized_phone = normalize_phone(phone)

        if not name and not normalized_phone:
            return None, False

        if normalized_phone:
            existing = self.find_by_phone(normalized_phone)
            if existing:
                # Дополняем имя, если раньше его не знали или указано новое
                if name and existing.name != name:
                    existing.name = name
                    self.db.flush()
                return existing, False

        client = Client(name=name, phone=normalized_phone or None)
        self.db.add(client)
        self.db.flush()
        return client, True

    def update_client(self, client_id: int, name: str = None, phone: str = None):
        """Изменить имя и/или телефон клиента."""
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError(f"Клиент #{client_id} не найден")

        if name is not None:
            client.name = name.strip() or None

        if phone is not None:
            normalized = normalize_phone(phone)
            # Не даём назначить телефон, который уже занят другим клиентом
            if normalized:
                occupied = self.db.query(Client).filter(
                    Client.phone == normalized,
                    Client.id != client_id
                ).first()
                if occupied:
                    raise ValueError(
                        f"Телефон {format_phone(normalized)} уже принадлежит "
                        f"клиенту «{occupied.name or 'без имени'}» (#{occupied.id})"
                    )
            client.phone = normalized or None

        self.db.commit()
        return client

    # ------------------------------------------------------------------
    # Машины клиента
    # ------------------------------------------------------------------

    def get_car(self, license_plate: str):
        """Найти машину по госномеру в любом написании."""
        normalized = normalize_plate(license_plate)
        if not normalized:
            return None
        return self.db.query(Car).filter(Car.license_plate == normalized).first()

    def get_client_cars(self, client_id: int):
        """Все машины клиента."""
        return self.db.query(Car).filter(
            Car.client_id == client_id
        ).order_by(Car.license_plate).all()

    def attach_car(self, license_plate: str, client_id: int):
        """
        Привязать машину к клиенту. Машина создаётся, если её ещё нет.

        Если машина уже была привязана к другому клиенту — владелец меняется
        (машину продали, или в прошлый раз записали не того).
        """
        normalized = normalize_plate(license_plate)
        if not normalized:
            raise ValueError("Не указан номер автомобиля")

        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            raise ValueError(f"Клиент #{client_id} не найден")

        car = self.db.query(Car).filter(Car.license_plate == normalized).first()
        if not car:
            car = Car(license_plate=normalized)
            self.db.add(car)

        car.client_id = client_id
        self.db.commit()
        return car

    def detach_car(self, license_plate: str):
        """Отвязать машину от клиента, не удаляя ни машину, ни клиента."""
        car = self.get_car(license_plate)
        if car:
            car.client_id = None
            self.db.commit()
        return car

    def update_car(self, license_plate: str, vehicle_type: str = None,
                   wheel_diameter: str = None, wheels_assembled=None,
                   new_plate: str = None):
        """
        Изменить данные автомобиля.

        Переданы только те поля, которые нужно поменять; остальные
        остаются как были. wheels_assembled может быть True, False или
        None — поэтому «не менять» здесь передаётся строкой 'keep'.
        """
        car = self.get_car(license_plate)
        if not car:
            raise ValueError(f"Автомобиль {license_plate} не найден")

        if new_plate:
            normalized = normalize_plate(new_plate)
            if not normalized:
                raise ValueError("Не указан номер автомобиля")
            if normalized != car.license_plate:
                occupied = self.db.query(Car).filter(
                    Car.license_plate == normalized, Car.id != car.id
                ).first()
                if occupied:
                    raise ValueError(f"Автомобиль {normalized} уже есть в базе")
                car.license_plate = normalized

        if vehicle_type is not None:
            car.vehicle_type = vehicle_type
        if wheel_diameter is not None:
            car.wheel_diameter = wheel_diameter
        if wheels_assembled != 'keep':
            car.wheels_assembled = wheels_assembled

        self.db.commit()
        return car

    def count_car_orders(self, license_plate: str) -> int:
        """Сколько нарядов было по этой машине."""
        car = self.get_car(license_plate)
        if not car:
            return 0
        return self.db.query(WorkOrder).filter(WorkOrder.car_id == car.id).count()

    def delete_car(self, license_plate: str):
        """
        Удалить автомобиль из базы.

        Машину с историей нарядов удалять нельзя: наряды останутся
        без машины, а история и отчёты сломаются. В таком случае
        её нужно открепить от клиента, а не удалять.
        """
        car = self.get_car(license_plate)
        if not car:
            raise ValueError(f"Автомобиль {license_plate} не найден")

        orders = self.db.query(WorkOrder).filter(WorkOrder.car_id == car.id).count()
        if orders:
            raise ValueError(
                f"По автомобилю {car.license_plate} есть наряды ({orders}). "
                f"Удалить его нельзя — историю потеряем. Открепите его от клиента."
            )

        self.db.delete(car)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # История
    # ------------------------------------------------------------------

    def get_client_orders(self, client_id: int, include_deleted: bool = False):
        """
        Все наряды клиента по всем его машинам.

        Учитываются и наряды, оформленные напрямую на клиента, и наряды
        по машинам, которые сейчас за ним закреплены.
        """
        car_ids = [car.id for car in self.get_client_cars(client_id)]

        conditions = [WorkOrder.client_id == client_id]
        if car_ids:
            conditions.append(WorkOrder.car_id.in_(car_ids))

        query = self.db.query(WorkOrder).filter(or_(*conditions))
        if not include_deleted:
            query = query.filter(WorkOrder.is_deleted == False)

        return query.order_by(WorkOrder.created_at.desc()).all()

    def get_client_recommendations(self, client_id: int, limit: int = 30):
        """
        История рекомендаций мастера по всем машинам клиента.

        Клиент видит их на чеке, а здесь — весь список с датами, чтобы
        приёмщик мог напомнить: «в прошлый раз советовали заменить
        передние колодки». Эти же данные потом читает личный кабинет.
        """
        orders = self.get_client_orders(client_id)

        history = []
        for order in orders:
            if not order.recommendations or not order.recommendations.strip():
                continue
            history.append({
                'order_id': order.id,
                'date': order.paid_at or order.created_at,
                'license_plate': order.car.license_plate if order.car else '—',
                'text': order.recommendations.strip(),
            })

        # Свежие сверху
        history.sort(key=lambda row: row['date'] or datetime.min, reverse=True)
        return history[:limit]

    def get_client_summary(self, client_id: int):
        """
        Сводка по клиенту для показа в интерфейсе:
        сколько машин, сколько оплаченных визитов, на какую сумму.
        """
        client = self.db.query(Client).filter(Client.id == client_id).first()
        if not client:
            return None

        cars = self.get_client_cars(client_id)
        orders = [o for o in self.get_client_orders(client_id) if o.status == 'paid']

        return {
            'client': client,
            'phone_display': format_phone(client.phone) if client.phone else '',
            'cars': cars,
            'visits': len(orders),
            'total_spent': round(sum(o.total_amount or 0 for o in orders), 2),
            'last_visit': max((o.paid_at for o in orders if o.paid_at), default=None),
        }
