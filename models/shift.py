from sqlalchemy import Column, Integer, Float, String, DateTime
from sqlalchemy.sql import func
from config import Base

class Shift(Base):
    __tablename__ = 'shifts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default='open')
    total_salary = Column(Float, default=0.0)
