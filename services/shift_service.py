from models import Shift, WorkOrder, SalaryTransaction, Employee
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from utils import get_moscow_time, as_naive

class ShiftService:
    def __init__(self, db: Session):
        self.db = db
    
    def open_shift(self, open_posts: int = None) -> Shift:
        """
        Открыть новую смену.

        open_posts — сколько постов работает сегодня. Если не указано,
        берётся значение по умолчанию из настроек. От этого числа зависит,
        сколько машин обслуживается одновременно, а значит расчёт
        очереди и записи.
        """
        # Проверяем, нет ли уже открытой смены
        existing_shift = self.db.query(Shift).filter(
            Shift.status == 'open'
        ).first()

        if existing_shift:
            raise ValueError("Уже есть открытая смена. Закройте текущую смену перед открытием новой.")

        if open_posts is None:
            from services.settings_service import SettingsService
            open_posts = SettingsService(self.db).get_int('default_posts')

        if open_posts < 1:
            raise ValueError("В смене должен быть открыт хотя бы один пост")

        # Создаём новую смену
        shift = Shift(status='open', open_posts=open_posts)
        self.db.add(shift)
        self.db.commit()
        self.db.refresh(shift)
        return shift

    def set_open_posts(self, shift_id: int, open_posts: int) -> Shift:
        """Изменить число открытых постов посреди смены."""
        if open_posts < 1:
            raise ValueError("В смене должен быть открыт хотя бы один пост")

        shift = self.db.query(Shift).filter(Shift.id == shift_id).first()
        if not shift:
            raise ValueError("Смена не найдена")

        shift.open_posts = open_posts
        self.db.commit()
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
    
    def get_shift_salary_details(self, shift_id: int) -> dict:
        """
        Начисления за смену с разбором по нарядам.

        Возвращает по каждому сотруднику: итог и строки нарядов, из
        которых он сложился. В строке только номер наряда, машина и
        сумма — этого хватает, чтобы мастер узнал свою работу, а
        разбираться в составе наряда надо не здесь.

            {employee_id: {'employee': Employee, 'salary': 1234.0,
                           'orders': [{'order_id': 412,
                                       'license_plate': 'А123ВВ777',
                                       'amount': 480.0}]}}
        """
        rows = self.db.query(SalaryTransaction, WorkOrder).join(
            WorkOrder, SalaryTransaction.work_order_id == WorkOrder.id
        ).filter(
            WorkOrder.shift_id == shift_id
        ).order_by(WorkOrder.id).all()

        details = {}
        for transaction, order in rows:
            emp_id = transaction.employee_id
            if emp_id not in details:
                employee = self.db.query(Employee).filter(
                    Employee.id == emp_id).first()
                details[emp_id] = {'employee': employee, 'salary': 0.0,
                                   'orders': []}

            details[emp_id]['salary'] += transaction.amount
            details[emp_id]['orders'].append({
                'order_id': order.id,
                'license_plate': order.car.license_plate if order.car else '',
                'amount': transaction.amount,
            })

        return details

    def get_all_employees_shift_salary(self, shift_id: int) -> dict:
        """Получить зарплату всех сотрудников за смену
        
        Returns:
            dict: {employee_id: {'employee': Employee, 'salary': float}}
        """
        # Считает get_shift_salary_details, здесь только отбрасываем
        # разбор по нарядам: два одинаковых подсчёта рано или поздно
        # разойдутся, и объяснять разницу придётся мастеру
        return {emp_id: {'employee': data['employee'], 'salary': data['salary']}
                for emp_id, data in self.get_shift_salary_details(shift_id).items()}
    
    def close_shift(self, shift_id: int) -> dict:
        """Закрыть смену и вернуть статистику
        
        Returns:
            dict: {
                'shift': Shift,
                'duration_hours': float,
                'employees': {employee_id: {'employee': Employee, 'salary': float,
                                            'orders': [...]}},
                'total_salary': float
            }
        """
        shift = self.db.query(Shift).filter(Shift.id == shift_id).first()
        if not shift:
            raise ValueError("Смена не найдена")
        
        if shift.status == 'closed':
            raise ValueError("Смена уже закрыта")
        
        # Начисления с разбором по нарядам: при закрытии смены мастер
        # первым делом спрашивает, за что вышла сумма
        employees_salary = self.get_shift_salary_details(shift_id)
        
        # Вычисляем общую сумму
        total_salary = sum(data['salary'] for data in employees_salary.values())
        
        # Закрываем смену
        shift.end_time = get_moscow_time()
        shift.status = 'closed'
        shift.total_salary = round(total_salary, 2)

        # Вычисляем продолжительность смены
        # as_naive защищает от старых записей, сохранённых с часовым поясом
        duration = as_naive(shift.end_time) - as_naive(shift.start_time)
        duration_hours = duration.total_seconds() / 3600
        
        self.db.commit()
        self.db.refresh(shift)
        
        return {
            'shift': shift,
            'duration_hours': duration_hours,
            'employees': employees_salary,
            'total_salary': total_salary
        }
