from models import WorkOrder, WorkShift, SalaryTransaction, Employee
from sqlalchemy.orm import Session
from datetime import datetime
from utils import get_moscow_time

class SalaryService:
    def __init__(self, db: Session):
        self.db = db
    
    def process_payment(self, order_id: int, payment_method: str, total_amount: float):
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if not order:
            raise ValueError("Наряд не найден")

        # Защита от повторной оплаты: если наряд уже оплачен, второй раз
        # начислять зарплату нельзя. Иначе при ошибке печати чека кассир
        # нажимал "Оплатить" ещё раз и ЗП начислялась дважды.
        if order.status == 'paid':
            raise ValueError(
                f"Наряд №{order_id} уже оплачен "
                f"({order.total_amount:.2f} руб.). Повторная оплата невозможна."
            )

        # Используем сохранённых сотрудников из наряда
        if not order.employee_ids:
            raise ValueError("Нет сотрудников в наряде")
        
        employee_ids = [int(id.strip()) for id in order.employee_ids.split(',')]
        num_employees = len(employee_ids)

        # Зарплата начисляется не со всей суммы, а с базы: итог минус
        # расходники. Материалы (грибки, жгуты, вентили, грузики) — это
        # затраты шиномонтажа, а не заработок механика.
        # Считаем сами, а не берём от вызывающего кода: так база всегда
        # соответствует фактическому составу наряда.
        from services.order_service import OrderService
        order_service = OrderService(self.db)
        consumables = order_service.calculate_consumables(order_id)
        salary_base = round(max(0.0, total_amount - consumables), 2)

        for employee_id in employee_ids:
            employee = self.db.query(Employee).filter(Employee.id == employee_id).first()
            employee_percent = employee.salary_percent if employee else 40.0

            # Процент делится на количество сотрудников в наряде
            # Например: 40% / 2 сотрудника = 20% для каждого
            divided_percent = employee_percent / num_employees
            salary_amount = salary_base * (divided_percent / 100)

            transaction = SalaryTransaction(
                employee_id=employee_id,
                work_order_id=order_id,
                amount=round(salary_amount, 2)
            )
            self.db.add(transaction)

        order.paid_at = get_moscow_time()
        order.payment_method = payment_method
        order.total_amount = total_amount
        order.consumables_amount = consumables
        order.salary_base = salary_base
        order.status = 'paid'

        self.db.commit()
