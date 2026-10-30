"""
Живая очередь: место берут на месте, по QR у въезда.

Очередью управляет программа цеха — она раздаёт посты и работает без
интернета (docs/live_queue.md). Здесь только то, что нужно человеку с
телефоном: занять место по QR, видеть своё место и примерное время и
узнать, на какой пост ехать. Цех забирает новые места при обмене и
присылает обратно, что с каждым происходит.
"""
from sqlalchemy import (Column, Integer, String, Boolean, DateTime,
                        ForeignKey, Index)

from app.database import Base
from app.utils import now as shop_now

WAITING = 'waiting'     # ждёт
CALLED = 'called'       # позвали на пост
SERVING = 'serving'     # стоит на посту, наряд открыт
DONE = 'done'           # обслужили
LEFT = 'left'           # ушёл или убрали

ACTIVE = (WAITING, CALLED)


class LiveTicket(Base):
    __tablename__ = 'live_tickets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False, index=True)
    # Вошёл в кабинет — вызов уйдёт ему в Telegram или браузер
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)

    # Пропуск к своему месту: лежит в куке телефона
    token = Column(String(64), nullable=False, unique=True, index=True)

    license_plate = Column(String(50), nullable=False)
    phone = Column(String(20), nullable=True)
    wheel_diameter = Column(String(10), nullable=True)
    wheels_assembled = Column(Boolean, nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    state = Column(String(10), default=WAITING, nullable=False)

    # Что прислал цех
    local_id = Column(Integer, nullable=True)       # место в программе цеха
    place = Column(Integer, nullable=True)          # какой по счёту
    eta_at = Column(DateTime, nullable=True)        # примерно когда
    post_number = Column(Integer, nullable=True)
    called_at = Column(DateTime, nullable=True)
    told_at = Column(DateTime, nullable=True)       # когда сообщили о вызове
    # Человек ушёл сам — цех узнает при обмене
    left_by_client = Column(Boolean, default=False, nullable=False,
                            server_default='0')
    updated_at = Column(DateTime, default=shop_now, onupdate=shop_now,
                        nullable=False)

    __table_args__ = (Index('ix_live_tickets_shop_state', 'shop_id', 'state'),)
