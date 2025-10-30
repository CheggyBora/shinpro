from models import Shift, WorkOrder, SalaryTransaction, Employee
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime

class ShiftService:
    def __init__(self, db: Session):
        self.db = db
    
    def open_shift(self) -> Shift:
        """Открыть новую смену"""
        # Проверяем, нет ли уже открытой смены
        existing_shift = self.db.query(Shift).filter(
            Shift.status == 'open'
        ).first()
        
        if existing_shift:
            raise ValueError("Уже есть открытая смена. Закройте текущую смену перед открытием новой.")
        
        # Создаём новую смену
        shift = Shift(status='open')
        self.db.add(shift)
        self.db.commit()
        self.db.refresh(shift)
        return shift
    
    def get_current_shift(self):
        """Получить текущую открытую смену"""
        return self.db.query(Shift).filter(Shift.status == 'open').first()
    
    def get_employee_shift_salary(self, shift_id: int, employee_id: int) -> float:
        """Получить зарплату конкретного сотрудника за смену"""
        # Получаем все транзакции сотрудника за наряды в этой смене
        total = self.db.query(func.sum(SalaryTransaction.amount)).join(
            WorkOrder, SalaryTransaction.work_order_id == WorkOrder.id
        ).filter(
            WorkOrder.shift_id == shift_id,
            SalaryTransaction.employee_id == employee_id
        ).scalar()
        
        return float(total) if total else 0.0
    
    def get_all_employees_shift_salary(self, shift_id: int) -> dict:
        """Получить зарплату всех сотрудников за смену
        
        Returns:
            dict: {employee_id: {'employee': Employee, 'salary': float}}
        """
        # Получаем всех сотрудников, которые работали в эту смену
        employee_salaries = {}
        
        # Находим все транзакции за смену
        transactions = self.db.query(SalaryTransaction).join(
            WorkOrder, SalaryTransaction.work_order_id == WorkOrder.id
        ).filter(
            WorkOrder.shift_id == shift_id
        ).all()
        
        # Группируем по сотрудникам
        for transaction in transactions:
            emp_id = transaction.employee_id
            if emp_id not in employee_salaries:
                employee = self.db.query(Employee).filter(Employee.id == emp_id).first()
                employee_salaries[emp_id] = {
                    'employee': employee,
                    'salary': 0.0
                }
            employee_salaries[emp_id]['salary'] += transaction.amount
        
        return employee_salaries
    
    def close_shift(self, shift_id: int) -> dict:
        """Закрыть смену и вернуть статистику
        
        Returns:
            dict: {
                'shift': Shift,
                'duration_hours': float,
                'employees': {employee_id: {'employee': Employee, 'salary': float}},
                'total_salary': float
            }
        """
        shift = self.db.query(Shift).filter(Shift.id == shift_id).first()
        if not shift:
            raise ValueError("Смена не найдена")
        
        if shift.status == 'closed':
            raise ValueError("Смена уже закрыта")
        
        # Получаем зарплату всех сотрудников
        employees_salary = self.get_all_employees_shift_salary(shift_id)
        
        # Вычисляем общую сумму
        total_salary = sum(data['salary'] for data in employees_salary.values())
        
        # Закрываем смену
        shift.end_time = datetime.now()
        shift.status = 'closed'
        shift.total_salary = round(total_salary, 2)
        
        # Вычисляем продолжительность смены
        duration = shift.end_time - shift.start_time
        duration_hours = duration.total_seconds() / 3600
        
        self.db.commit()
        self.db.refresh(shift)
        
        return {
            'shift': shift,
            'duration_hours': duration_hours,
            'employees': employees_salary,
            'total_salary': total_salary
        }
