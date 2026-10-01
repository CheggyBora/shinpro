from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from config import Base
from utils import get_moscow_time

class TireStorage(Base):
    __tablename__ = 'tire_storage'
    
    id = Column(Integer, primary_key=True)
    car_number = Column(String(20), nullable=False)
    driver_license = Column(String(50))
    storage_type = Column(String(50), nullable=False)
    diameter = Column(String(10), nullable=False)
    brand = Column(String(100))
    damage = Column(String(500))
    wear = Column(String(100))
    comments = Column(String(1000))
    wheel_type = Column(String(20), nullable=True)
    price = Column(Float, nullable=False)
    status = Column(String(20), default='stored', nullable=False)
    work_order_id = Column(Integer, ForeignKey('work_orders.id'), nullable=True)
    accepted_date = Column(DateTime(timezone=True), default=get_moscow_time)

    # До какого числа комплект лежит по оплаченному сроку. Считается при
    # приёмке от срока из настроек, но правится руками: с человеком
    # можно договориться на другой срок, и тогда в базе должно стоять
    # то, о чём договорились, а не то, что посчиталось
    expires_at = Column(DateTime(timezone=True), nullable=True)

    released_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    
    work_order = relationship("WorkOrder", backref="tire_storage")
