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

    # Гарантийная переделка — бесплатный повторный визит по нашей вине.
    # В выручке и среднем чеке не участвует, но виден в отчётах.
    is_warranty = Column(Boolean, default=False)

    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_reason = Column(String(500), nullable=True)
    
    car = relationship("Car", backref="work_orders")
    client = relationship("Client", backref="work_orders")
