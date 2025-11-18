from models import Employee, WorkShift, SalaryTransaction, Settings
from sqlalchemy.orm import Session
from datetime import datetime
from utils import get_moscow_time

class EmployeeService:
    def __init__(self, db: Session):
        self.db = db
    
    def register_employee(self, employee_id: int) -> Employee:
        existing = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if existing:
            raise ValueError(f"Сотрудник с номером {employee_id} уже существует")
        
        employee = Employee(id=employee_id, salary_percent=40.0)
        self.db.add(employee)
        self.db.commit()
        self.db.refresh(employee)
        return employee
    
    def get_all_employees(self):
        return self.db.query(Employee).filter(Employee.is_active == True).all()
    
    def update_salary_percent(self, employee_id: int, new_percent: float, pin: str) -> Employee:
        admin_pin = self.db.query(Settings).filter(Settings.key == 'admin_pin').first()
        correct_pin = admin_pin.value if admin_pin else "0000"
        
        if pin != correct_pin:
            raise ValueError("Неверный PIN-код")
        
        employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise ValueError("Сотрудник не найден")
        
        employee.salary_percent = new_percent
        self.db.commit()
        self.db.refresh(employee)
        return employee
    
    def start_shift(self, employee_id: int) -> WorkShift:
        employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise ValueError("Сотрудник не найден")
        
        active_shift = self.db.query(WorkShift).filter(
            WorkShift.employee_id == employee_id,
            WorkShift.end_time.is_(None)
        ).first()
        
        if active_shift:
            raise ValueError("У сотрудника уже есть открытая смена")
        
        shift = WorkShift(employee_id=employee_id)
        self.db.add(shift)
        self.db.commit()
        self.db.refresh(shift)
        return shift
    
    def end_shift(self, employee_id: int) -> WorkShift:
        shift = self.db.query(WorkShift).filter(
            WorkShift.employee_id == employee_id,
            WorkShift.end_time.is_(None)
        ).first()
        
        if not shift:
            raise ValueError("Открытая смена не найдена")
        
        shift.end_time = get_moscow_time()
        self.db.commit()
        self.db.refresh(shift)
        return shift
    
    def get_active_shifts(self):
        return self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
    
    def get_salary_report(self, employee_id: int, date_from: datetime, date_to: datetime):
        transactions = self.db.query(SalaryTransaction).filter(
            SalaryTransaction.employee_id == employee_id,
            SalaryTransaction.transaction_date >= date_from,
            SalaryTransaction.transaction_date <= date_to
        ).all()
        
        return transactions
