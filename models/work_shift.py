from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from config import Base
from utils import get_moscow_time

class WorkShift(Base):
    __tablename__ = 'work_shifts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False)
    start_time = Column(DateTime(timezone=True), default=get_moscow_time)
    end_time = Column(DateTime(timezone=True), nullable=True)
    
    employee = relationship("Employee", backref="work_shifts")
