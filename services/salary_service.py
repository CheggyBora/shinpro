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
        
        # Используем сохранённых сотрудников из наряда
        if not order.employee_ids:
            raise ValueError("Нет сотрудников в наряде")
        
        employee_ids = [int(id.strip()) for id in order.employee_ids.split(',')]
        num_employees = len(employee_ids)
        
        for employee_id in employee_ids:
            employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
            employee_percent = employee.salary_percent if employee else 40.0
            
            # Процент делится на количество сотрудников в наряде
            # Например: 40% / 2 сотрудника = 20% для каждого
            divided_percent = employee_percent / num_employees
            salary_amount = total_amount * (divided_percent / 100)
            
            transaction = SalaryTransaction(
                employee_id=employee_id,
                work_order_id=order_id,
                amount=round(salary_amount, 2)
            )
            self.db.add(transaction)
        
        order.paid_at = datetime.now()
        order.payment_method = payment_method
        order.total_amount = total_amount
        order.status = 'paid'
        
        self.db.commit()
