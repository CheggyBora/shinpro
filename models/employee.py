from sqlalchemy import Column, Integer, Float, DateTime, Boolean
from config import Base
from utils import get_moscow_time

class Employee(Base):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    salary_percent = Column(Float, default=40.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    is_active = Column(Boolean, default=True)
