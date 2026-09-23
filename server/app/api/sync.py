"""
Работа программы в цеху с сервером.

Делится не «база локально или на сервере», а по данным:

    живёт только в цеху   наряды, оплата, зарплата, смены, прайс,
                          расходники, печать, отчёты, клиенты, хранение

    живёт только здесь    запись и посты под запись

    уходит копией наверх  клиенты, машины, история визитов,
                          хранение, очередь

Запись — единственное, что клиент и цех меняют оба. Поэтому она живёт
в одном месте, и оба к ней обращаются: и приложение, и программа цеха.
Двух копий нет — значит, нечему и разойтись. Цена решения: без интернета
записать нельзя, и это осознанный выбор.

Всё остальное цех делает без интернета вообще: наряды, оплата и печать
чеков работают, даже когда связи нет неделю.

Закрыто отдельным ключом: программа цеха видит всю базу целиком,
и путать этот доступ с клиентским входом нельзя.
"""
from datetime import datetime, timedelta, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (Client, Car, Appointment, BookingDay, StoredSet,
                        Visit, VisitItem, SalaryAccrual, SalaryPayout,
                        ShopEmployee, ShopShift, QueueSnapshot, Shop,
                        PENDING, TAKEN, REJECTED)
from app.security import require_sync_key
from app.services import shop_settings
from app.services.booking_service import BookingService
from app.utils import normalize_phone, normalize_plate, normalize_email, now as shop_now

router = APIRouter(prefix='/sync', tags=['Обмен с цехом'])

# Точка, предъявившая ключ обмена. Она же — единственное, что этот
# запрос имеет право видеть и менять
Mine = Depends(require_sync_key)


# ----------------------------------------------------------------------
# Что цех присылает наверх
# ----------------------------------------------------------------------

class ClientIn(BaseModel):
    local_id: int
    phone: str
    name: Optional[str] = None


class CarIn(BaseModel):
    local_id: int
    license_plate: str
    client_local_id: Optional[int] = None
    vehicle_type: Optional[str] = None
    wheel_diameter: Optional[str] = None
    wheels_assembled: Optional[bool] = None


class AppointmentIn(BaseModel):
    local_id: int
    scheduled_at: datetime
    duration_minutes: int = 60
    license_plate: Optional[str] = None
    client_local_id: Optional[int] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    wheels_assembled: Optional[bool] = None
    status: str = 'scheduled'
    source: str = 'phone'
    comment: Optional[str] = None


class VisitItemIn(BaseModel):
    local_id: Optional[int] = None
    service_name: str
    quantity: int = 1
    unit_price: float = 0.0
    discount_percent: int = 0
    total: float = 0.0
    consumable_cost: float = 0.0
    comment: Optional[str] = None


class AccrualIn(BaseModel):
    employee_local_id: int
    amount: float = 0.0
    accrued_at: Optional[datetime] = None


class VisitIn(BaseModel):
    local_id: int
    client_local_id: Optional[int] = None
    license_plate: Optional[str] = None
    visited_at: datetime
    total_amount: float = 0.0
    services: Optional[str] = None
    recommendations: Optional[str] = None
    is_warranty: bool = False

    # Деньги и работа — для дашборда. Приложению клиента это не отдаётся
    changed_at: Optional[datetime] = None
    shift_local_id: Optional[int] = None
    vehicle_type: Optional[str] = None
    wheel_diameter: Optional[str] = None
    payment_method: Optional[str] = None
    consumables_amount: float = 0.0
    salary_base: float = 0.0
    general_discount: int = 0
    rim_discount: int = 0
    auto_discount: bool = False
    refunded_amount: float = 0.0
    refunded_at: Optional[datetime] = None
    refund_type: Optional[str] = None
    refund_reason: Optional[str] = None
    is_deleted: bool = False
    planned_minutes: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    items: List[VisitItemIn] = []
    accruals: List[AccrualIn] = []


class EmployeeIn(BaseModel):
    local_id: int
    name: Optional[str] = None
    salary_percent: float = 40.0
    is_active: bool = True


class PayoutIn(BaseModel):
    local_id: int
    employee_local_id: int
    amount: float = 0.0
    method: str = 'cash'
    paid_at: Optional[datetime] = None
    comment: Optional[str] = None
    is_advance: bool = False
    source: str = 'shop'


class ShiftIn(BaseModel):
    local_id: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    status: str = 'open'
    open_posts: int = 1
    total_salary: float = 0.0


class StorageIn(BaseModel):
    local_id: int
    client_local_id: Optional[int] = None
    license_plate: Optional[str] = None
    storage_type: Optional[str] = None
    wheel_type: Optional[str] = None
    diameter: Optional[str] = None
    brand: Optional[str] = None
    accepted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: str = 'stored'


class BookingDayIn(BaseModel):
    day: str = Field(..., description='Дата как ГГГГ-ММ-ДД')
    posts: int = 1
    opens_at: str = '09:00'
    closes_at: str = '21:00'
    is_closed: bool = False


class QueueIn(BaseModel):
    cars_in_work: int = 0
    cars_waiting: int = 0
    open_posts: int = 0
    free_in_minutes: Optional[int] = None
    shift_is_open: bool = False


class PushIn(BaseModel):
    clients: List[ClientIn] = []
    cars: List[CarIn] = []
    visits: List[VisitIn] = []
    employees: List[EmployeeIn] = []
    shifts: List[ShiftIn] = []
    payouts: List[PayoutIn] = []
    storage: List[StorageIn] = []
    queue: Optional[QueueIn] = None
    settings: dict = {}


class PushOut(BaseModel):
    clients: int = 0
    cars: int = 0
    visits: int = 0
    employees: int = 0
    shifts: int = 0
    payouts: int = 0
    storage: int = 0
    queue: bool = False
    settings: int = 0


# ----------------------------------------------------------------------
# Что цех забирает вниз
# ----------------------------------------------------------------------

class NewAppointmentOut(BaseModel):
    """Заявка клиента, которую цех ещё не забрал."""
    server_id: int
    local_id: Optional[int] = None
    scheduled_at: datetime
    duration_minutes: int
    license_plate: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    wheels_assembled: Optional[bool] = None
    status: str
    comment: Optional[str] = None


class StorageRequestOut(BaseModel):
    server_id: int
    storage_local_id: Optional[int] = None
    license_plate: Optional[str] = None
    requested_for: Optional[datetime] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None


class PullOut(BaseModel):
    appointments: List[NewAppointmentOut] = []
    storage_requests: List[StorageRequestOut] = []


class AckAppointment(BaseModel):
    server_id: int
    # Номер, который запись получила в базе цеха
    local_id: Optional[int] = None
    accepted: bool = True
    reason: Optional[str] = None


class AckStorage(BaseModel):
    server_id: int
    accepted: bool = True
    reason: Optional[str] = None


class AckIn(BaseModel):
    appointments: List[AckAppointment] = []
    storage_requests: List[AckStorage] = []


# ----------------------------------------------------------------------
# Наверх
# ----------------------------------------------------------------------

def _client_by_local_id(db, local_id, cache, account_id=None):
    if local_id is None:
        return None
    if local_id in cache:
        return cache[local_id]

    row = db.query(Client).filter(
        Client.local_id == local_id,
        Client.account_id == account_id).first()
    cache[local_id] = row
    return row


@router.post('/push', response_model=PushOut, summary='Цех отдаёт свои данные')
def push(payload: PushIn, db: Session = Depends(get_db),
         shop: Shop = Mine):
    """
    Принять всё, что цех накопил.

    Записи находятся по local_id — номеру строки в базе шиномонтажа.
    Повторная присылка того же не создаёт дубль, а обновляет: после
    долгого простоя цех присылает всё подряд, и это должно быть
    безопасно.
    """
    result = PushOut()
    cache = {}
    account_id = shop.account_id

    # --- Клиенты ------------------------------------------------------
    for item in payload.clients:
        phone = normalize_phone(item.phone)
        if not phone:
            continue

        row = db.query(Client).filter(
            Client.local_id == item.local_id,
            Client.account_id == account_id).first()
        if row is None:
            # Человек мог зарегистрироваться в приложении раньше, чем
            # приехал в цех. Тогда он уже есть — по телефону
            row = db.query(Client).filter(
                Client.phone == phone,
                Client.account_id == account_id).first()

        if row is None:
            row = Client(phone=phone, account_id=account_id)
            db.add(row)

        row.account_id = account_id
        row.local_id = item.local_id
        row.phone = phone
        # Имя из цеха главнее: там его записывал человек, а не
        # подставляло приложение
        if item.name:
            row.name = item.name
        db.flush()
        cache[item.local_id] = row
        result.clients += 1

    # --- Машины -------------------------------------------------------
    for item in payload.cars:
        plate = normalize_plate(item.license_plate)
        if not plate:
            continue

        row = db.query(Car).filter(
            Car.local_id == item.local_id,
            Car.account_id == account_id).first()
        if row is None:
            row = db.query(Car).filter(
                Car.license_plate == plate,
                Car.account_id == account_id).first()
        if row is None:
            row = Car(license_plate=plate, account_id=account_id)
            db.add(row)

        row.account_id = account_id

        owner = _client_by_local_id(db, item.client_local_id, cache, account_id)
        row.local_id = item.local_id
        row.license_plate = plate
        row.vehicle_type = item.vehicle_type
        row.wheel_diameter = item.wheel_diameter
        row.wheels_assembled = item.wheels_assembled
        if owner is not None:
            row.client_id = owner.id
        db.flush()
        result.cars += 1

    # --- Визиты -------------------------------------------------------
    for item in payload.visits:
        row = db.query(Visit).filter(
            Visit.local_id == item.local_id,
            Visit.shop_id == shop.id).first()
        if row is None:
            row = Visit(local_id=item.local_id, shop_id=shop.id,
                        visited_at=item.visited_at)
            db.add(row)

        owner = _client_by_local_id(db, item.client_local_id, cache, account_id)
        row.visited_at = item.visited_at
        row.license_plate = normalize_plate(item.license_plate) or None
        row.total_amount = item.total_amount
        row.services = item.services
        row.recommendations = item.recommendations
        row.is_warranty = item.is_warranty
        if owner is not None:
            row.client_id = owner.id

        row.changed_at = item.changed_at or item.visited_at
        row.shift_local_id = item.shift_local_id
        row.vehicle_type = item.vehicle_type
        row.wheel_diameter = item.wheel_diameter
        row.payment_method = item.payment_method
        row.consumables_amount = item.consumables_amount
        row.salary_base = item.salary_base
        row.general_discount = item.general_discount
        row.rim_discount = item.rim_discount
        row.auto_discount = item.auto_discount
        row.refunded_amount = item.refunded_amount
        row.refunded_at = item.refunded_at
        row.refund_type = item.refund_type
        row.refund_reason = item.refund_reason
        row.is_deleted = item.is_deleted
        row.planned_minutes = item.planned_minutes
        row.started_at = item.started_at
        row.finished_at = item.finished_at
        db.flush()

        # Позиции и начисления кладём заново. Наряд мог измениться как
        # угодно — позицию убрали, скидку поправили, — и сверять построчно
        # дороже, чем переписать: строк в наряде единицы
        if item.items:
            for old in list(row.items):
                db.delete(old)
            db.flush()
            for line in item.items:
                db.add(VisitItem(
                    visit_id=row.id,
                    local_id=line.local_id,
                    service_name=line.service_name,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    discount_percent=line.discount_percent,
                    total=line.total,
                    consumable_cost=line.consumable_cost,
                    comment=line.comment))

        if item.accruals:
            for old in list(row.accruals):
                db.delete(old)
            db.flush()
            for accrual in item.accruals:
                db.add(SalaryAccrual(
                    visit_id=row.id,
                    employee_local_id=accrual.employee_local_id,
                    amount=accrual.amount,
                    accrued_at=accrual.accrued_at or item.visited_at))

        db.flush()
        result.visits += 1

    # --- Выплаты ---------------------------------------------------
    for item in payload.payouts:
        row = db.query(SalaryPayout).filter(
            SalaryPayout.local_id == item.local_id,
            SalaryPayout.shop_id == shop.id).first()
        if row is None:
            row = SalaryPayout(local_id=item.local_id, shop_id=shop.id)
            db.add(row)

        row.employee_local_id = item.employee_local_id
        row.amount = item.amount
        row.method = item.method
        row.paid_at = item.paid_at
        row.comment = item.comment
        row.is_advance = item.is_advance
        row.source = item.source
        db.flush()
        result.payouts += 1

    # --- Сотрудники ---------------------------------------------------
    for item in payload.employees:
        row = db.query(ShopEmployee).filter(
            ShopEmployee.local_id == item.local_id,
            ShopEmployee.shop_id == shop.id).first()
        if row is None:
            row = ShopEmployee(local_id=item.local_id, shop_id=shop.id)
            db.add(row)

        row.name = item.name
        row.salary_percent = item.salary_percent
        row.is_active = item.is_active
        db.flush()
        result.employees += 1

    # --- Смены ----------------------------------------------------------
    for item in payload.shifts:
        row = db.query(ShopShift).filter(
            ShopShift.local_id == item.local_id,
            ShopShift.shop_id == shop.id).first()
        if row is None:
            row = ShopShift(local_id=item.local_id, shop_id=shop.id)
            db.add(row)

        row.started_at = item.started_at
        row.ended_at = item.ended_at
        row.status = item.status
        row.open_posts = item.open_posts
        row.total_salary = item.total_salary
        db.flush()
        result.shifts += 1

    # --- Хранение -----------------------------------------------------
    for item in payload.storage:
        row = db.query(StoredSet).filter(
            StoredSet.local_id == item.local_id,
            StoredSet.shop_id == shop.id).first()
        if row is None:
            row = StoredSet(local_id=item.local_id, shop_id=shop.id)
            db.add(row)

        owner = _client_by_local_id(db, item.client_local_id, cache, account_id)
        row.license_plate = normalize_plate(item.license_plate) or None
        row.storage_type = item.storage_type
        row.wheel_type = item.wheel_type
        row.diameter = item.diameter
        row.brand = item.brand
        row.accepted_at = item.accepted_at
        row.expires_at = item.expires_at
        row.status = item.status
        if owner is not None:
            row.client_id = owner.id
        db.flush()
        result.storage += 1

    # --- Очередь --------------------------------------------------------
    if payload.queue is not None:
        db.add(QueueSnapshot(
            shop_id=shop.id,
            taken_at=shop_now(),
            cars_in_work=payload.queue.cars_in_work,
            cars_waiting=payload.queue.cars_waiting,
            open_posts=payload.queue.open_posts,
            free_in_minutes=payload.queue.free_in_minutes,
            shift_is_open=payload.queue.shift_is_open))
        result.queue = True

    # --- Настройки ------------------------------------------------------
    for key, value in (payload.settings or {}).items():
        shop_settings.set_value(db, key, value, commit=False, shop=shop)
        result.settings += 1

    db.commit()
    _drop_old_snapshots(db)
    return result


def _drop_old_snapshots(db, keep=200):
    """
    Слепков очереди накапливается по одному в минуту.

    Нужен только последний, но несколько прошлых полезны, когда
    разбираешься, что происходило. Остальное — мусор в базе.
    """
    total = db.query(QueueSnapshot).count()
    if total <= keep:
        return

    edge = db.query(QueueSnapshot).order_by(
        QueueSnapshot.taken_at.desc()).offset(keep).first()
    if edge is not None:
        db.query(QueueSnapshot).filter(
            QueueSnapshot.taken_at < edge.taken_at).delete()
        db.commit()


# ----------------------------------------------------------------------
# Вниз
# ----------------------------------------------------------------------

@router.get('/appointments', summary='Записи на день — то, что видит приёмщик')
def day_appointments(day: str, db: Session = Depends(get_db),
                     shop: Shop = Mine):
    """
    Все записи дня, откуда бы они ни пришли, и разложенные по постам.

    Это тот же список, что видит клиент в приложении: база одна.
    Раскладку по колонкам считаем здесь, чтобы цех и приложение
    показывали одинаково.
    """
    try:
        target = datetime.strptime(day, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Дату нужно как ГГГГ-ММ-ДД')

    start = datetime.combine(target, time.min)
    end = start + timedelta(days=1)

    rows = db.query(Appointment).filter(
        Appointment.shop_id == shop.id,
        Appointment.scheduled_at >= start,
        Appointment.scheduled_at < end).order_by(
        Appointment.scheduled_at).all()

    settings = BookingService(db, shop).day_settings(target)
    posts = settings['posts']

    # Первая свободная колонка на это время. Записи сверх постов
    # получают номер за сеткой — приёмщик увидит их отдельно
    free_at = [None] * posts
    result = []
    for row in rows:
        column = posts
        if row.status in ('scheduled', 'arrived'):
            finish = row.scheduled_at + timedelta(minutes=row.duration_minutes or 0)
            for index in range(posts):
                if free_at[index] is None or free_at[index] <= row.scheduled_at:
                    column = index
                    free_at[index] = finish
                    break

        result.append({
            'id': row.id,
            'scheduled_at': row.scheduled_at,
            'duration_minutes': row.duration_minutes,
            'license_plate': row.license_plate,
            'client_name': row.client_name or (row.client.name if row.client else None),
            'client_phone': row.client_phone or (row.client.phone if row.client else None),
            'wheels_assembled': row.wheels_assembled,
            'status': row.status,
            'source': row.source,
            'comment': row.comment,
            'column': column,
        })

    return {'day': target.isoformat(), 'posts': posts,
            'is_closed': settings['is_closed'], 'appointments': result}


class ShopBookingIn(BaseModel):
    scheduled_at: datetime
    duration_minutes: int = 60
    license_plate: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    wheels_assembled: Optional[bool] = None
    comment: Optional[str] = None
    # Приёмщик решает сам: он видит цех и может втиснуть машину
    force: bool = True


@router.post('/appointments', summary='Приёмщик записывает клиента')
def create_appointment(payload: ShopBookingIn, db: Session = Depends(get_db),
                       shop: Shop = Mine):
    """
    Записать клиента со стороны цеха.

    В отличие от приложения, здесь можно записать сверх постов: приёмщик
    видит, что происходит в боксе, и решение за ним. Но занятость всё
    равно возвращаем — программа предупредит.
    """
    plate = normalize_plate(payload.license_plate)
    phone = normalize_phone(payload.client_phone)
    name = (payload.client_name or '').strip() or None

    service = BookingService(db, shop)
    settings = service.day_settings(payload.scheduled_at.date())
    free = service._slot_is_free(payload.scheduled_at,
                                 payload.duration_minutes, settings['posts'])

    if not free and not payload.force:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail='На это время все посты заняты')

    client = None
    if phone or name:
        client = _client_for(db, phone, name, shop.account_id)

    car = None
    if plate:
        car = db.query(Car).filter(
            Car.license_plate == plate,
            Car.account_id == shop.account_id).first()
        if car is None:
            car = Car(license_plate=plate, account_id=shop.account_id)
            db.add(car)
            db.flush()
        if client is not None and car.client_id is None:
            car.client_id = client.id
        if payload.wheels_assembled is not None and car.wheels_assembled is None:
            car.wheels_assembled = payload.wheels_assembled
        if client is None and car.client_id:
            client = car.client

    row = Appointment(
        shop_id=shop.id,
        client_id=client.id if client else None,
        car_id=car.id if car else None,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        license_plate=plate or None,
        client_name=name or (client.name if client else None),
        client_phone=phone or (client.phone if client else None),
        wheels_assembled=(payload.wheels_assembled
                          if payload.wheels_assembled is not None
                          else (car.wheels_assembled if car else None)),
        comment=(payload.comment or '').strip() or None,
        status='scheduled',
        source='phone',
        sync_state=TAKEN)

    db.add(row)
    db.commit()
    db.refresh(row)
    return {'id': row.id, 'was_free': free, 'posts': settings['posts']}


def _client_for(db, phone, name, account_id=None):
    """Найти клиента по телефону или завести. Имя из цеха главнее."""
    client = None
    if phone:
        # Ищем среди клиентов своего аккаунта: тот же номер в другой
        # сети — другой человек, и путать их нельзя
        client = db.query(Client).filter(
            Client.phone == phone,
            Client.account_id == account_id).first()

    if client is None:
        if not phone:
            return None
        client = Client(phone=phone, name=name, account_id=account_id)
        db.add(client)
        db.flush()
    elif name:
        client.name = name

    return client


class AppointmentPatchIn(BaseModel):
    scheduled_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    license_plate: Optional[str] = None
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    status: Optional[str] = None
    comment: Optional[str] = None


@router.patch('/appointments/{appointment_id}', summary='Изменить запись')
def patch_appointment(appointment_id: int, payload: AppointmentPatchIn,
                      db: Session = Depends(get_db),
                      shop: Shop = Mine):
    row = db.query(Appointment).filter(
        Appointment.id == appointment_id,
        Appointment.shop_id == shop.id).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Запись не найдена')

    if payload.scheduled_at is not None:
        row.scheduled_at = payload.scheduled_at
    if payload.duration_minutes is not None:
        row.duration_minutes = payload.duration_minutes
    if payload.license_plate is not None:
        row.license_plate = normalize_plate(payload.license_plate) or None
    if payload.client_name is not None:
        row.client_name = payload.client_name.strip() or None
    if payload.client_phone is not None:
        row.client_phone = normalize_phone(payload.client_phone) or None
    if payload.status is not None:
        row.status = payload.status
    if payload.comment is not None:
        row.comment = payload.comment.strip() or None

    db.commit()
    return {'ok': True, 'id': row.id, 'status': row.status}


@router.get('/posts', summary='Постов под запись по дням')
def get_posts(day: str, days: int = 1, db: Session = Depends(get_db),
              shop: Shop = Mine):
    try:
        start = datetime.strptime(day, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Дату нужно как ГГГГ-ММ-ДД')

    service = BookingService(db, shop)
    answer = {}
    for offset in range(max(1, min(days, 400))):
        target = start + timedelta(days=offset)
        answer[target.isoformat()] = service.day_settings(target)['posts']
    return answer


class PostsIn(BaseModel):
    day: str
    days: int = 1
    posts: int = 1
    opens_at: Optional[str] = None
    closes_at: Optional[str] = None
    is_closed: Optional[bool] = None


@router.put('/posts', summary='Задать постов под запись')
def set_posts(payload: PostsIn, db: Session = Depends(get_db),
              shop: Shop = Mine):
    try:
        start = datetime.strptime(payload.day, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Дату нужно как ГГГГ-ММ-ДД')

    posts = max(1, min(3, payload.posts))
    changed = 0
    for offset in range(max(1, min(payload.days, 400))):
        target = start + timedelta(days=offset)
        row = db.query(BookingDay).filter(
            BookingDay.day == target,
            BookingDay.shop_id == shop.id).first()
        if row is None:
            row = BookingDay(day=target, shop_id=shop.id)
            db.add(row)

        row.posts = posts
        if payload.opens_at:
            row.opens_at = payload.opens_at
        if payload.closes_at:
            row.closes_at = payload.closes_at
        if payload.is_closed is not None:
            row.is_closed = payload.is_closed
        changed += 1

    db.commit()
    return {'ok': True, 'days': changed, 'posts': posts}


@router.get('/storage-requests', response_model=List[StorageRequestOut],
            summary='Заявки клиентов привезти комплект')
def storage_requests(db: Session = Depends(get_db),
                     shop: Shop = Mine):
    """
    Заявка висит здесь, пока цех не подтвердит приём.

    Это единственное, что до сих пор ходит очередью: комплект лежит
    на складе в цеху, и сервер про него ничего решить не может.
    """
    rows = db.query(StoredSet).filter(StoredSet.request_state == PENDING).all()
    return [StorageRequestOut(
        server_id=row.id,
        storage_local_id=row.local_id,
        license_plate=row.license_plate,
        requested_for=row.requested_for,
        client_name=row.client.name if row.client else None,
        client_phone=row.client.phone if row.client else None) for row in rows]


@router.post('/storage-requests/ack', summary='Цех принял заявки на комплекты')
def ack_storage(payload: AckIn, db: Session = Depends(get_db),
                shop: Shop = Mine):
    taken = 0
    for item in payload.storage_requests:
        row = db.query(StoredSet).filter(
            StoredSet.id == item.server_id,
            StoredSet.shop_id == shop.id).first()
        if row is None:
            continue

        row.request_state = TAKEN if item.accepted else REJECTED
        if not item.accepted:
            row.requested_for = None
        taken += 1

    db.commit()
    return {'ok': True, 'taken': taken}


class PayoutOut(BaseModel):
    """Выплата, отмеченная владельцем и ещё не учтённая цехом."""
    server_id: int
    employee_local_id: int
    amount: float
    method: str
    comment: Optional[str] = None
    paid_at: Optional[datetime] = None


class AckPayout(BaseModel):
    server_id: int
    local_id: Optional[int] = None
    accepted: bool = True
    reason: Optional[str] = None


class AckPayoutsIn(BaseModel):
    payouts: List[AckPayout] = []


@router.get('/payouts', response_model=List[PayoutOut],
            summary='Выплаты, которые цех ещё не забрал')
def pending_payouts(db: Session = Depends(get_db),
                    shop: Shop = Mine):
    rows = db.query(SalaryPayout).filter(
        SalaryPayout.shop_id == shop.id,
        SalaryPayout.sync_state == PENDING).order_by(SalaryPayout.id).all()

    return [PayoutOut(
        server_id=row.id,
        employee_local_id=row.employee_local_id,
        amount=row.amount,
        method=row.method,
        comment=row.comment,
        paid_at=row.paid_at) for row in rows]


@router.post('/payouts/ack', summary='Цех подтверждает, что выплату учёл')
def ack_payouts(payload: AckPayoutsIn, db: Session = Depends(get_db),
                shop: Shop = Mine):
    """
    Пока цех не подтвердил, выплата остаётся в очереди и придёт снова.

    Лучше повторить дважды, чем потерять один раз: потерянная выплата —
    это деньги, которые человек получил, а программа об этом не знает.
    """
    taken = 0
    for item in payload.payouts:
        row = db.query(SalaryPayout).filter(
            SalaryPayout.id == item.server_id,
            SalaryPayout.shop_id == shop.id).first()
        if row is None:
            continue

        if item.accepted:
            row.sync_state = TAKEN
            row.local_id = item.local_id
            taken += 1
        else:
            row.sync_state = REJECTED
            row.reject_reason = (item.reason or '')[:255]

    db.commit()
    return {'taken': taken}


@router.get('/state', summary='Что сейчас на сервере')
def state(db: Session = Depends(get_db),
          shop: Shop = Mine):
    """
    Короткая сводка — по ней программа показывает состояние связи.

    Здесь же отметка visits_changed_until: до какого момента сервер знает
    наряды. Цех смотрит на неё и досылает только то, что изменилось
    после. Хранить эту отметку у себя цех не может: сервер могли поднять
    заново из пустой базы, и тогда местная отметка врала бы, а история
    на сервере так и осталась бы дырявой.
    """
    last = db.query(QueueSnapshot).filter(
        QueueSnapshot.shop_id == shop.id).order_by(
        QueueSnapshot.taken_at.desc()).first()

    changed_until = db.query(func.max(Visit.changed_at)).filter(
        Visit.shop_id == shop.id).scalar()

    return {
        'shop': {'id': shop.id, 'name': shop.name, 'slug': shop.slug},
        'visits_changed_until': changed_until,
        'clients': db.query(Client).filter(
            Client.account_id == shop.account_id).count(),
        'appointments': db.query(Appointment).filter(
            Appointment.shop_id == shop.id).count(),
        'visits': db.query(Visit).filter(Visit.shop_id == shop.id).count(),
        'storage': db.query(StoredSet).filter(
            StoredSet.shop_id == shop.id).count(),
        'pending_appointments': db.query(Appointment).filter(
            Appointment.shop_id == shop.id,
            Appointment.sync_state == PENDING).count(),
        'pending_storage_requests': db.query(StoredSet).filter(
            StoredSet.shop_id == shop.id,
            StoredSet.request_state == PENDING).count(),
        'pending_payouts': db.query(SalaryPayout).filter(
            SalaryPayout.shop_id == shop.id,
            SalaryPayout.sync_state == PENDING).count(),
        'queue_taken_at': last.taken_at if last else None,
    }
