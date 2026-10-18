from sqlalchemy import Column, Integer, String, Boolean, DateTime
from config import Base
from utils import get_moscow_time

# Состояния места в живой очереди
WAITING = 'waiting'     # ждёт
CALLED = 'called'       # позвали на пост, едет
SERVING = 'serving'     # наряд открыт, машина на посту
DONE = 'done'           # обслужили
LEFT = 'left'           # ушёл, не дождался, убрали

ACTIVE = (WAITING, CALLED)


class LiveQueueEntry(Base):
    """
    Место в живой очереди.

    Встать можно только приехав: по QR у въезда или через приёмщика.
    Очередь живёт в программе цеха — она раздаёт посты и работает без
    интернета. Сервер только принимает QR-заявки и сообщает людям, что
    их позвали (см. docs/live_queue.md).
    """
    __tablename__ = 'live_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Номер места на сервере — у заявок по QR. У добавленных в цеху
    # без связи пусто, пока обмен их не отправит
    server_id = Column(Integer, nullable=True, index=True)

    license_plate = Column(String(50), nullable=False, index=True)
    phone = Column(String(50), nullable=True)
    client_name = Column(String(200), nullable=True)

    # Для наряда: цена зависит от диаметра, состав — от колёс
    wheel_diameter = Column(String(10), nullable=True)
    wheels_assembled = Column(Boolean, nullable=True)
    vehicle_type = Column(String(50), default='car', nullable=False)

    # Откуда: 'qr' — сам по коду у въезда, 'shop' — приёмщик
    source = Column(String(10), default='shop', nullable=False)

    joined_at = Column(DateTime(timezone=True), default=get_moscow_time,
                       nullable=False, index=True)
    status = Column(String(10), default=WAITING, nullable=False, index=True)

    post_number = Column(Integer, nullable=True)
    called_at = Column(DateTime(timezone=True), nullable=True)
    # Сколько раз звали, а машина не подъехала
    misses = Column(Integer, default=0, nullable=False)

    order_id = Column(Integer, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<LiveQueueEntry {self.license_plate} {self.status}>"
