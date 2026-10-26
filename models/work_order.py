from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from config import Base
from utils import get_moscow_time

class WorkOrder(Base):
    __tablename__ = 'work_orders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    car_id = Column(Integer, ForeignKey('cars.id'), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    shift_id = Column(Integer, ForeignKey('shifts.id'), nullable=True)
    wheel_diameter = Column(String(10), nullable=False)
    vehicle_type = Column(String(50), default='car')
    auto_discount = Column(Boolean, default=False)
    general_discount = Column(Integer, default=0)
    rim_discount = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payment_method = Column(String(20), nullable=True)
    total_amount = Column(Float, default=0.0)
    status = Column(String(20), default='draft')
    employee_ids = Column(String(200), nullable=True)
    recommendations = Column(Text, nullable=True)
    
    # Плановое время работ в минутах. Меняется ТОЛЬКО по кнопке
    # «Сохранить наряд»: пока мастер прикидывает стоимость и добавляет
    # услуги для обсуждения с клиентом, время в очереди не должно скакать.
    planned_minutes = Column(Integer, default=0)

    # Колонка on_queue_post (пост онлайн-очереди) была здесь до отмены
    # той очереди. В старых базах она осталась, но всегда с DEFAULT 0 —
    # и от create_all, и от add_missing_columns, — поэтому наряды, где
    # её больше нет, SQLite записывает без ошибок

    # Когда сказали клиенту, что машина готова. Нужно, чтобы приёмщик
    # видел: уже позвали или ещё нет. Иначе в запарке клиента зовут
    # дважды или не зовут вовсе — каждый думает, что это сделал другой
    client_told_at = Column(DateTime(timezone=True), nullable=True)

    # На каком посту стоит машина (1, 2, 3…). По нему программа знает,
    # какие посты заняты и когда освободятся, и раздаёт их записи и
    # живой очереди. Пусто — старые наряды и наряды без поста
    post_number = Column(Integer, nullable=True)

    # На что приехал человек: «tire», «wash» или «tire,wash». Каждое
    # направление занимает свой пост: шиномонтаж — post_number, мойка —
    # wash_post_number. Класс машины — для цены мойки
    directions = Column(String(20), default='tire', server_default='tire', nullable=False)
    wash_post_number = Column(Integer, nullable=True)
    wash_class = Column(String(16), nullable=True)
    # Обложка: снимок машины с телефона при приезде (docs/order_photo.md).
    # Имя файла в папке photos/covers рядом с базой
    cover_path = Column(String(200), nullable=True)

    # Время пакета, с которым машина пришла из очереди или записи:
    # на дисках 30 минут, только шины — час (настройки booking_minutes_*).
    # Плановое время наряда не меньше пакета, даже если у услуг в прайсе
    # длительность не заполнена
    package_minutes = Column(Integer, nullable=True)

    # Фактическое время: нужно, чтобы уточнять нормативы по реальным данным
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # Пауза: ждём деталь, клиент уехал за деньгами. Пост занят,
    # но работа не идёт — это время не должно портить статистику.
    paused_at = Column(DateTime(timezone=True), nullable=True)
    paused_minutes = Column(Integer, default=0)

    # Расходники и база для зарплаты — сохраняются в момент оплаты,
    # чтобы через полгода можно было объяснить механику, откуда взялась
    # цифра в его начислении
    consumables_amount = Column(Float, default=0.0)
    salary_base = Column(Float, default=0.0)

    # Возврат денег клиенту или сторно кассовой ошибки.
    # Наряд при этом НЕ удаляется: он был, работа выполнялась,
    # и в истории это должно остаться видно.
    refunded_amount = Column(Float, default=0.0)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    refund_reason = Column(String(500), nullable=True)
    refund_type = Column(String(20), nullable=True)  # refund | reversal

    # Гарантийная переделка — отдельный наряд на ту же машину, услуги в
    # нём по 0 ₽ (решение владельца 26.10.2026). Товары — по цене: вентиль
    # при переделке ставят новый. В отчётах виден, сколько было переделок
    is_warranty = Column(Boolean, default=False)
    # По какому наряду переделка и почему
    warranty_of_id = Column(Integer, nullable=True)
    warranty_reason = Column(String(500), nullable=True)

    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_reason = Column(String(500), nullable=True)
    
    car = relationship("Car", backref="work_orders")
    client = relationship("Client", backref="work_orders")
