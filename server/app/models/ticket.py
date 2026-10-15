"""
Онлайн-очередь: место занимают из дома, а не стоя у ворот.

Это не запись. Запись — обещание на время: «ждём вас в 14:00», и под
неё держат пост. Очередь обещания не даёт: человек занимает место,
видит, когда примерно подойдёт его черёд, и едет.

Главное решение здесь — **порядок считается по времени прибытия, а
не по времени нажатия**. Иначе тот, кто в часе езды, занимает первую
позицию, пост стоит пустой, а тот, кто живёт в пяти минутах, ждёт
его. Человек говорит, через сколько будет, и встаёт на это время.

Соврать можно, но невыгодно: подошла очередь, а его нет на месте —
берут следующего. Место при этом не сгорает, он просто смещается.
"""
from sqlalchemy import (Column, Integer, String, DateTime, ForeignKey, Index,
                        Text)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now

# Что с талоном происходит
WAITING = 'waiting'       # едет или ждёт на месте
CALLED = 'called'         # приёмщик позвал на пост
SERVED = 'served'         # завели наряд, дальше работа как обычно
CANCELLED = 'cancelled'   # человек отказался сам
EXPIRED = 'expired'       # не приехал и перестал отвечать

OPEN_STATES = (WAITING, CALLED)

STATE_TITLES = {
    WAITING: 'Ждёт',
    CALLED: 'Позвали',
    SERVED: 'Обслужен',
    CANCELLED: 'Отменён',
    EXPIRED: 'Не приехал',
}


class QueueTicket(Base):
    """Место в онлайн-очереди."""
    __tablename__ = 'queue_tickets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True,
                       index=True)

    license_plate = Column(String(20), nullable=True)
    client_name = Column(String(120), nullable=True)
    client_phone = Column(String(20), nullable=True)

    # Колёса в сборе или россыпью — от этого зависит время работ, как
    # и при записи
    wheels_assembled = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False, index=True)

    # Когда человек обещал быть. По нему и строится порядок
    eta_at = Column(DateTime, nullable=False, index=True)

    # Когда отметился «я на месте». Пока пусто — звать его нельзя:
    # машины у ворот нет, и пост простоит зря
    arrived_at = Column(DateTime, nullable=True)

    # Время, которое мы человеку назвали в последний раз. Нужно, чтобы
    # заметить, что оно уехало: он построил на нём свои планы, и молча
    # сдвигать его нельзя. Сдвинулось — говорим
    promised_at = Column(DateTime, nullable=True)
    promise_told_at = Column(DateTime, nullable=True)

    # Сколько раз его пропустили, потому что не было на месте. Два
    # промаха — снимаем: место держат живые люди, которые стоят рядом
    missed = Column(Integer, default=0, nullable=False)

    state = Column(String(16), default=WAITING, nullable=False, index=True)
    called_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

    # Номер наряда в цеху, когда машину взяли в работу
    order_local_id = Column(Integer, nullable=True)

    shop = relationship('Shop')
    client = relationship('Client')

    @property
    def is_open(self):
        return self.state in OPEN_STATES

    @property
    def is_here(self):
        return self.arrived_at is not None


Index('ix_queue_tickets_shop_state', QueueTicket.shop_id, QueueTicket.state)
