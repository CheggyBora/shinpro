from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from config import Base

class WorkOrder(Base):
    __tablename__ = 'work_orders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    car_id = Column(Integer, ForeignKey('cars.id'), nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True)
    wheel_diameter = Column(String(10), nullable=False)
    auto_discount = Column(Boolean, default=False)
    general_discount = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True), nullable=True)
    payment_method = Column(String(20), nullable=True)
    total_amount = Column(Float, default=0.0)
    status = Column(String(20), default='draft')
    
    car = relationship("Car", backref="work_orders")
    client = relationship("Client", backref="work_orders")
