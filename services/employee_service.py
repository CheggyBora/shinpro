from models import Employee, WorkShift, SalaryTransaction
from sqlalchemy.orm import Session
from datetime import datetime
from utils import get_moscow_time

class EmployeeService:
    def __init__(self, db: Session):
        self.db = db
    
    def register_employee(self, employee_id: int, name: str = None,
                          role_id=None) -> Employee:
        """
        Завести сотрудника. Категорию можно выбрать сразу: новому ещё
        ничего не начислено, и PIN тут не нужен. Менять её потом — по PIN.
        """
        existing = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if existing:
            raise ValueError(f"Сотрудник с номером {employee_id} уже существует")

        if role_id is not None:
            from services.employee_role_service import EmployeeRoleService
            if EmployeeRoleService(self.db).get(role_id) is None:
                raise ValueError("Такой категории уже нет")

        employee = Employee(id=employee_id, salary_percent=40.0,
                            name=(name or '').strip() or None,
                            role_id=role_id)
        self.db.add(employee)
        self.db.commit()
        self.db.refresh(employee)
        return employee

    def set_name(self, employee_id: int, name: str) -> Employee:
        """
        Записать имя сотрудника.

        Имя не обязательно: у старых сотрудников его нет, и заставлять
        цех заполнять их разом незачем — где пусто, там останется номер.
        """
        employee = self.db.query(Employee).filter(
            Employee.id == employee_id).first()
        if employee is None:
            raise ValueError(f"Сотрудник №{employee_id} не найден")

        employee.name = (name or '').strip() or None
        self.db.commit()
        self.db.refresh(employee)
        return employee

    def get_all_employees(self):
        return self.db.query(Employee).filter(Employee.is_active == True).all()
    
    def update_role(self, employee_id: int, role_id, pin: str) -> Employee:
        """
        Сменить категорию сотрудника. От неё зависит, с каких услуг ему
        начисляется, — поэтому, как и ставка, только по админскому PIN.
        """
        from services.auth_service import AuthService
        from services.audit_service import AuditService
        from services.employee_role_service import EmployeeRoleService

        auth = AuthService(self.db)
        audit = AuditService(self.db)

        if not auth.verify_pin(pin):
            audit.log(AuditService.PIN_FAILED,
                      f"Неверный PIN при попытке сменить категорию "
                      f"сотрудника №{employee_id}")
            raise ValueError("Неверный PIN-код")

        roles = EmployeeRoleService(self.db)
        employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise ValueError("Сотрудник не найден")

        old_title = roles.role_title(employee)
        roles.set_employee_role(employee_id, role_id)
        new_title = roles.role_title(employee)

        audit.log('employee.role_change',
                  f"Сотрудник №{employee_id}: категория «{old_title}» -> "
                  f"«{new_title}»",
                  entity_type='employee', entity_id=employee_id)
        return employee

    def update_salary_percent(self, employee_id: int, new_percent: float, pin: str) -> Employee:
        from services.auth_service import AuthService
        from services.audit_service import AuditService

        auth = AuthService(self.db)
        audit = AuditService(self.db)

        if not auth.verify_pin(pin):
            audit.log(AuditService.PIN_FAILED,
                      f"Неверный PIN при попытке изменить ставку сотрудника №{employee_id}")
            raise ValueError("Неверный PIN-код")

        employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            raise ValueError("Сотрудник не найден")

        old_percent = employee.salary_percent
        employee.salary_percent = new_percent
        self.db.commit()
        self.db.refresh(employee)

        audit.log(AuditService.SALARY_PERCENT_CHANGE,
                  f"Сотрудник №{employee_id}: ставка {old_percent}% -> {new_percent}%",
                  entity_type='employee', entity_id=employee_id)
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

        # Съёмщик один на смене стоять не может: встаёт, когда мастер
        # уже там
        from services.employee_role_service import EmployeeRoleService
        roles = EmployeeRoleService(self.db)
        if not roles.can_work_alone(employee):
            if not any(roles.can_work_alone(other)
                       for other in self._on_shift(exclude=employee_id)):
                raise ValueError(
                    f"{roles.role_title(employee)} не может стоять на смене "
                    f"один. Сначала на смену встаёт мастер")

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

        # Последний мастер не уходит, пока на смене остаётся съёмщик:
        # иначе съёмщик окажется на смене один
        from services.employee_role_service import EmployeeRoleService
        roles = EmployeeRoleService(self.db)
        leaving = self.db.query(Employee).filter(
            Employee.id == employee_id).first()
        if roles.can_work_alone(leaving):
            staying = self._on_shift(exclude=employee_id)
            if staying and not any(roles.can_work_alone(e) for e in staying):
                numbers = ', '.join(f'№{e.id}' for e in staying)
                raise ValueError(
                    f"Нельзя: на смене останется без мастера {numbers}. "
                    f"Сначала закончите смену ему")

        shift.end_time = get_moscow_time()
        self.db.commit()
        self.db.refresh(shift)
        return shift
    
    def _on_shift(self, exclude=None):
        """Сотрудники, у которых сейчас открыта смена."""
        rows = self.db.query(Employee).join(
            WorkShift, WorkShift.employee_id == Employee.id).filter(
                WorkShift.end_time.is_(None)).all()
        return [e for e in rows if e.id != exclude]

    def get_active_shifts(self):
        return self.db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
    
    def get_salary_report(self, employee_id: int, date_from: datetime, date_to: datetime):
        transactions = self.db.query(SalaryTransaction).filter(
            SalaryTransaction.employee_id == employee_id,
            SalaryTransaction.transaction_date >= date_from,
            SalaryTransaction.transaction_date <= date_to
        ).all()
        
        return transactions
