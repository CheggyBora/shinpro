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
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)


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

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False)

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
    Прошлый визит: что делали, за сколько и что посоветовал мастер.

    Копится на сервере, чтобы клиент видел свою историю. Состав работ
    держим строкой: приложению нужен читаемый список, а не таблица,
    по которой оно всё равно ничего не считает.
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

    client = relationship('Client')


Index('ix_visits_client_date', Visit.client_id, Visit.visited_at)


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

    taken_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    cars_in_work = Column(Integer, default=0, nullable=False)
    cars_waiting = Column(Integer, default=0, nullable=False)
    open_posts = Column(Integer, default=0, nullable=False)

    # Через сколько минут освободится ближайший пост
    free_in_minutes = Column(Integer, nullable=True)

    shift_is_open = Column(Boolean, default=False, nullable=False)
