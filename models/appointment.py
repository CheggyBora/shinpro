from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from config import Base
from utils import get_moscow_time


class Appointment(Base):
    """
    Запись на обслуживание — местная копия для показа.

    Сама запись живёт на сервере: её меняют и приёмщик, и клиент из
    приложения, поэтому она должна быть в одном месте, иначе двум копиям
    нечему помешать разойтись. Программа цеха обращается к серверу по
    сети, а сюда складывает последний полученный ответ.

    Зачем копия, если она ничего не решает: интернет моргает. Приёмщик
    должен видеть, кого он ждёт сегодня, даже когда связь пропала на
    десять минут. Записать нового или отменить в это время нельзя —
    и программа честно говорит об этом, а не делает вид, что сохранила.

    Строки здесь одноразовые: при каждом успешном обращении к серверу
    день перезаписывается целиком. Править их бессмысленно — затрёт.
    """
    __tablename__ = 'appointments'

    # Откуда пришла запись
    SOURCE_PHONE = 'phone'
    SOURCE_WEB = 'web'
    SOURCE_WALKIN = 'walkin'
    SOURCE_LINK = 'link'

    SOURCE_TITLES = {
        SOURCE_PHONE: 'По телефону',
        SOURCE_WEB: 'Из приложения',
        SOURCE_WALKIN: 'Лично',
        SOURCE_LINK: 'По ссылке, не подтверждена',
    }

    # Что с записью происходит
    STATUS_SCHEDULED = 'scheduled'   # записан, ждём
    STATUS_ARRIVED = 'arrived'       # приехал, наряд заведён
    STATUS_CANCELLED = 'cancelled'   # отменена
    STATUS_NO_SHOW = 'no_show'       # не приехал

    STATUS_TITLES = {
        STATUS_SCHEDULED: 'Ожидается',
        STATUS_ARRIVED: 'Приехал',
        STATUS_CANCELLED: 'Отменена',
        STATUS_NO_SHOW: 'Не приехал',
    }

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Номер записи на сервере. Все действия идут по нему: местный id
    # живёт только до следующего обновления кэша
    server_id = Column(Integer, nullable=True, index=True)

    # В какой колонке-посту показывать. Считает сервер, чтобы
    # приложение и программа цеха рисовали одинаково
    post_column = Column(Integer, default=0)

    # Когда этот ответ получен от сервера — по нему видно, насколько
    # устарело то, что на экране
    fetched_at = Column(DateTime(timezone=True), nullable=True)

    # На какое время записан
    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # Сколько займёт по оценке: нужно, чтобы понимать загрузку постов
    duration_minutes = Column(Integer, default=30, nullable=False)

    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    car_id = Column(Integer, ForeignKey('cars.id'), nullable=True)

    # Снимок контактов на момент записи: клиент мог позвонить и не приехать,
    # заводить ради этого карточку не обязательно
    client_name = Column(String(200), nullable=True)
    client_phone = Column(String(50), nullable=True, index=True)
    license_plate = Column(String(50), nullable=True, index=True)

    # Что собираются делать — свободным текстом со слов клиента
    services_note = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)

    status = Column(String(20), default=STATUS_SCHEDULED, nullable=False, index=True)
    source = Column(String(20), default=SOURCE_PHONE, nullable=False)

    # Наряд, заведённый когда клиент приехал
    work_order_id = Column(Integer, ForeignKey('work_orders.id'), nullable=True)

    created_at = Column(DateTime(timezone=True), default=get_moscow_time)

    client = relationship("Client", backref="appointments")
    car = relationship("Car", backref="appointments")
    work_order = relationship("WorkOrder", backref="appointment")

    @property
    def source_title(self):
        return self.SOURCE_TITLES.get(self.source, self.source)

    @property
    def status_title(self):
        return self.STATUS_TITLES.get(self.status, self.status)

    def __repr__(self):
        return f"<Appointment #{self.id} {self.scheduled_at} {self.license_plate}>"
