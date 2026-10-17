from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from config import Base
from utils import get_moscow_time

class SalaryTransaction(Base):
    __tablename__ = 'salary_transactions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False)
    work_order_id = Column(Integer, ForeignKey('work_orders.id'), nullable=False)
    amount = Column(Float, nullable=False)
    transaction_date = Column(DateTime(timezone=True), default=get_moscow_time)

    # Разбор «за что начислено» по услугам — JSON, см.
    # SalaryService.split. Нужен, чтобы ответить мастеру, почему у него
    # меньше, чем у напарника: на какой услуге и сколько человек делили.
    # Пусто у старых начислений и у откатов при возврате
    detail = Column(Text, nullable=True)
    
    employee = relationship("Employee", backref="salary_transactions")
    work_order = relationship("WorkOrder", backref="salary_transactions")
