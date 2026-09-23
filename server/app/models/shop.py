"""
То, что сервер знает о работе цеха: записи, хранение, визиты, очередь.

Все эти таблицы — отражение базы шиномонтажа. Сервер их не выдумывает,
а получает при обмене. Исключение — заявки, пришедшие из приложения:
они рождаются здесь и ждут, пока цех их заберёт.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Date,
                        Float, Text, ForeignKey, Index)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now

# Заявка из приложения проходит три состояния: ждёт цеха, забрана
# цехом, отклонена. Пока не забрана — клиент видит «подтверждаем».
PENDING = 'pending'
TAKEN = 'taken'
REJECTED = 'rejected'


class ShopSetting(Base):
    """
    Настройки, присланные цехом.

    Сколько времени закладывать на запись, за сколько дней вперёд пускать
    клиента записываться — всё это решает шиномонтаж, а не сервер.
    Сервер только применяет присланное, чтобы приложение и программа
    в цеху считали одинаково.
    """
    __tablename__ = 'shop_settings'

    key = Column(String(64), primary_key=True)
    value = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=shop_now,
                        onupdate=shop_now, nullable=False)


class Appointment(Base):
    """
    Запись на обслуживание.

    Приходит двумя путями: из цеха (записали по телефону) или из
    приложения (клиент записался сам). Второй случай отличается тем,
    что shop_id пока пуст, а sync_state — «ждёт цеха».
    """
    __tablename__ = 'appointments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, nullable=True, unique=True, index=True)

    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True, index=True)
    car_id = Column(Integer, ForeignKey('cars.id'), nullable=True)

    scheduled_at = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer, default=60, nullable=False)

    license_plate = Column(String(20), nullable=True, index=True)
    client_name = Column(String(200), nullable=True)
    client_phone = Column(String(20), nullable=True)

    # Колёса в сборе или россыпью: от этого считается время
    wheels_assembled = Column(Boolean, nullable=True)
    comment = Column(Text, nullable=True)

    # Те же состояния, что в цеху: scheduled / arrived / cancelled / no_show
    status = Column(String(20), default='scheduled', nullable=False, index=True)
    source = Column(String(20), default='app', nullable=False)

    sync_state = Column(String(20), default=PENDING, nullable=False, index=True)
    reject_reason = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    updated_at = Column(DateTime, default=shop_now,
                        onupdate=shop_now, nullable=False)

    client = relationship('Client')
    car = relationship('Car')


class BookingDay(Base):
    """
    Сколько постов открыто под запись на день.

    Цех присылает это при обмене. Приложение по этим числам считает,
    какие окна показать клиенту свободными.
    """
    __tablename__ = 'booking_days'

    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(Date, nullable=False, unique=True, index=True)
    posts = Column(Integer, default=1, nullable=False)

    # Рабочие часы этого дня. Пусто — берём общие часы шиномонтажа
    # из настроек: своё расписание нужно редкому дню, а не каждому
    opens_at = Column(String(5), nullable=True)
    closes_at = Column(String(5), nullable=True)

    # Выходной: постов может быть сколько угодно, а цех закрыт
    is_closed = Column(Boolean, default=False, nullable=False)


class StoredSet(Base):
    """Комплект шин на хранении и заявка клиента привезти его к дате."""
    __tablename__ = 'stored_sets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, nullable=True, unique=True, index=True)

    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True, index=True)
    license_plate = Column(String(20), nullable=True, index=True)

    storage_type = Column(String(50), nullable=True)     # шины / шины с дисками
    wheel_type = Column(String(50), nullable=True)       # литые / штампованные
    diameter = Column(String(10), nullable=True)
    brand = Column(String(200), nullable=True)

    accepted_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='stored', nullable=False, index=True)

    # Заявка «привезите к этой дате». Пока цех её не забрал,
    # клиент видит «заявка отправлена»
    requested_for = Column(DateTime, nullable=True)
    request_state = Column(String(20), nullable=True, index=True)
    requested_at = Column(DateTime, nullable=True)

    client = relationship('Client')


class Visit(Base):
    """
    Оплаченный наряд: что делали, за сколько, кто работал.

    Одна строка — один наряд в цеху. Её читают двое, и видят разное:
    клиент в приложении — дату, услуги и рекомендации мастера; владелец
    на дашборде — ещё и деньги, расходники и зарплату.

    Двух таблиц под это нет намеренно. Наряд один, и если завести ему
    здесь две записи — «для клиента» и «для владельца», — они разойдутся
    после первого же возврата.

    Состав работ лежит и строкой (services), и позициями (items).
    Строка — для приложения: ему нужен читаемый список, а не таблица.
    Позиции — для дашборда, где по ним считают выручку по услугам.
    """
    __tablename__ = 'visits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, nullable=True, unique=True, index=True)

    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True, index=True)
    license_plate = Column(String(20), nullable=True, index=True)

    visited_at = Column(DateTime, nullable=False, index=True)
    total_amount = Column(Float, default=0.0, nullable=False)
    services = Column(Text, nullable=True)           # по услуге в строке
    recommendations = Column(Text, nullable=True)
    is_warranty = Column(Boolean, default=False, nullable=False)

    # --- Для дашборда ---------------------------------------------------
    # Когда наряд последний раз менялся в цеху: оплата, возврат, удаление.
    # По этой отметке цех досылает только новое, а не всю историю каждые
    # десять минут
    changed_at = Column(DateTime, nullable=True, index=True)

    shift_shop_id = Column(Integer, nullable=True, index=True)
    vehicle_type = Column(String(50), nullable=True)
    wheel_diameter = Column(String(10), nullable=True)

    payment_method = Column(String(20), nullable=True)
    consumables_amount = Column(Float, default=0.0, nullable=False)
    salary_base = Column(Float, default=0.0, nullable=False)

    general_discount = Column(Integer, default=0, nullable=False)
    rim_discount = Column(Integer, default=0, nullable=False)
    auto_discount = Column(Boolean, default=False, nullable=False)

    # Возврат и сторно. Деньги вычитаются из того дня, когда вернули,
    # а не когда работали: иначе вчерашняя выручка меняется задним числом
    refunded_amount = Column(Float, default=0.0, nullable=False)
    refunded_at = Column(DateTime, nullable=True, index=True)
    refund_type = Column(String(20), nullable=True)
    refund_reason = Column(String(500), nullable=True)

    # Удалённый наряд не исчезает, а помечается: в отчёты он не идёт,
    # но след того, что он был, остаётся
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)

    planned_minutes = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    client = relationship('Client')
    items = relationship('VisitItem', back_populates='visit',
                         cascade='all, delete-orphan')
    accruals = relationship('SalaryAccrual', back_populates='visit',
                            cascade='all, delete-orphan')


Index('ix_visits_client_date', Visit.client_id, Visit.visited_at)


class VisitItem(Base):
    """
    Позиция наряда: услуга, сколько раз, почём.

    Цена здесь — та, по которой продали, уже со скидкой на позицию.
    Пересчитывать её на сервере нельзя: скидку мог поставить руками
    приёмщик, и правило «10% на диски» такую цену не повторит.
    """
    __tablename__ = 'visit_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(Integer, ForeignKey('visits.id'), nullable=False, index=True)

    # Номер строки в базе цеха: по нему позиция обновляется, а не двоится
    shop_id = Column(Integer, nullable=True, index=True)

    service_name = Column(String(200), nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Float, default=0.0, nullable=False)
    discount_percent = Column(Integer, default=0, nullable=False)
    total = Column(Float, default=0.0, nullable=False)
    consumable_cost = Column(Float, default=0.0, nullable=False)
    comment = Column(Text, nullable=True)

    visit = relationship('Visit', back_populates='items')


class SalaryAccrual(Base):
    """
    Сколько мастер заработал на этом наряде.

    Считает цех и присылает готовым. Сервер не пересчитывает: правила
    начисления живут в одном месте, иначе дашборд и программа со
    временем начнут показывать разные суммы одному и тому же человеку.
    """
    __tablename__ = 'salary_accruals'

    id = Column(Integer, primary_key=True, autoincrement=True)
    visit_id = Column(Integer, ForeignKey('visits.id'), nullable=False, index=True)

    employee_shop_id = Column(Integer, nullable=False, index=True)
    amount = Column(Float, default=0.0, nullable=False)
    accrued_at = Column(DateTime, nullable=True, index=True)

    visit = relationship('Visit', back_populates='accruals')


class ShopEmployee(Base):
    """
    Сотрудник цеха.

    Имя нужно там, где речь о его деньгах: «Игорь — 18 400 ₽» читается,
    «№3 — 18 400 ₽» заставляет помнить номера. У старых сотрудников
    имени может не быть — тогда остаётся номер.
    """
    __tablename__ = 'shop_employees'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, nullable=False, unique=True, index=True)

    name = Column(String(100), nullable=True)
    salary_percent = Column(Float, default=40.0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    @property
    def title(self):
        if not self.name:
            return f"№{self.shop_id}"
        return f"{self.name} (№{self.shop_id})"


class ShopShift(Base):
    """Смена цеха: когда открыли, когда закрыли, сколько начислили."""
    __tablename__ = 'shop_shifts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, nullable=False, unique=True, index=True)

    started_at = Column(DateTime, nullable=True, index=True)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='open', nullable=False)
    open_posts = Column(Integer, default=1, nullable=False)
    total_salary = Column(Float, default=0.0, nullable=False)


class QueueSnapshot(Base):
    """
    Слепок очереди на текущий момент.

    Живая очередь — самое хрупкое место: она честна ровно настолько,
    насколько аккуратно мастера отмечают начало и конец работ. Поэтому
    храним ещё и время слепка: если цех давно не выходил на связь,
    приложение покажет «данные устарели», а не соврёт.
    """
    __tablename__ = 'queue_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)

    taken_at = Column(DateTime, default=shop_now, nullable=False, index=True)

    cars_in_work = Column(Integer, default=0, nullable=False)
    cars_waiting = Column(Integer, default=0, nullable=False)
    open_posts = Column(Integer, default=0, nullable=False)

    # Через сколько минут освободится ближайший пост
    free_in_minutes = Column(Integer, nullable=True)

    shift_is_open = Column(Boolean, default=False, nullable=False)
