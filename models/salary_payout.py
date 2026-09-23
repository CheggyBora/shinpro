from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean
from config import Base
from utils import get_moscow_time

# Чем выдали
METHOD_CASH = 'cash'
METHOD_CARD = 'card'

METHOD_TITLES = {
    METHOD_CASH: 'Наличные',
    METHOD_CARD: 'На карту',
}


class SalaryPayout(Base):
    """
    Выдача зарплаты: кому, сколько, чем и кто выдал.

    Начисления (salary_transactions) и выдачи — разные вещи, и держать
    их в одной таблице нельзя. Начисление появляется само при оплате
    наряда, выдача — только когда деньги отдали человеку в руки или
    перевели. Остаток к выдаче считается как разница.

    Выплату по карте может отметить владелец из дашборда. Такая запись
    приходит в цех при обмене и помечается server_id: по нему видно,
    что она уже учтена, и повторная присылка не создаст вторую выдачу.
    """
    __tablename__ = 'salary_payouts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=False,
                         index=True)

    amount = Column(Float, nullable=False)
    method = Column(String(20), default=METHOD_CASH, nullable=False)
    paid_at = Column(DateTime(timezone=True), default=get_moscow_time,
                     index=True)
    comment = Column(String(500), nullable=True)

    # Выдача сверх начисленного. Отмечаем, чтобы в ведомости было видно,
    # где аванс, а не гадать по отрицательному остатку
    is_advance = Column(Boolean, default=False, nullable=False)

    # Откуда пришла выдача: shop — выдали в цеху, dashboard — отметил
    # владелец переводом на карту
    source = Column(String(20), default='shop', nullable=False)
    server_id = Column(Integer, nullable=True, unique=True, index=True)

    def __repr__(self):
        return (f"<SalaryPayout #{self.id} сотрудник {self.employee_id} "
                f"{self.amount:.2f} {self.method}>")
