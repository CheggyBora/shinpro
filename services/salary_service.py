from models import WorkOrder, WorkShift, SalaryTransaction, Employee
from sqlalchemy.orm import Session
from datetime import datetime

class SalaryService:
    def __init__(self, db: Session):
        self.db = db
    
    def process_payment(self, order_id: int, payment_method: str, total_amount: float):
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            raise ValueError("Наряд не найден")
        
        active_shifts = self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
        
        if not active_shifts:
            raise ValueError("Нет сотрудников на смене")
        
        num_employees = len(active_shifts)
        
        for shift in active_shifts:
            employee = self.db.query(Employee).filter(Employee.id == shift.employee_id).first()
            employee_percent = employee.salary_percent if employee else 40.0
            
            salary_amount = (total_amount * (employee_percent / 100)) / num_employees
            
            transaction = SalaryTransaction(
                employee_id=shift.employee_id,
                work_order_id=order_id,
                amount=round(salary_amount, 2)
            )
            self.db.add(transaction)
        
        order.paid_at = datetime.now()
        order.payment_method = payment_method
        order.total_amount = total_amount
        order.status = 'paid'
        
        self.db.commit()
