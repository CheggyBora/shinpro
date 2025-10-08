from sqlalchemy import Column, Integer, Float, DateTime, Boolean
from sqlalchemy.sql import func
from config import Base

class Employee(Base):
    __tablename__ = 'employees'
    
    id = Column(Integer, primary_key=True)
    salary_percent = Column(Float, default=40.0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)
