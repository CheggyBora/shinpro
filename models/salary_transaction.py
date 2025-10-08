from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from config import Base

class SalaryTransaction(Base):
    __tablename__ = 'salary_transactions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False)
    work_order_id = Column(Integer, ForeignKey('work_orders.id'), nullable=False)
    amount = Column(Float, nullable=False)
    transaction_date = Column(DateTime(timezone=True), server_default=func.now())
    
    employee = relationship("Employee", backref="salary_transactions")
    work_order = relationship("WorkOrder", backref="salary_transactions")
