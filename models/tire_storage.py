from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from config import Base

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
    accepted_date = Column(DateTime(timezone=True), server_default=func.now())
    released_date = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    work_order = relationship("WorkOrder", backref="tire_storage")
