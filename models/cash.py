"""
Касса: приходные и расходные ордера (docs/cash.md).

Остаток наличных отдельно не хранится — он считается: на начало смены
плюс оплаты наличными, плюс приходные, минус расходные. Хранимый
остаток рано или поздно разошёлся бы с тем, из чего он сложен.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey

from config import Base
from utils import get_moscow_time

KIND_IN, KIND_OUT = 'in', 'out'
KIND_TITLES = {KIND_IN: 'Приходный', KIND_OUT: 'Расходный'}
METHOD_CASH, METHOD_NONCASH = 'cash', 'noncash'

DEFAULT_CATEGORIES = {
    KIND_OUT: ['Зарплата', 'Расходники', 'Вода', 'Аренда', 'Инкассация', 'Прочее'],
    KIND_IN: ['Внесение', 'Прочее'],
}
# Статья выдачи зарплаты. Её могут убрать из списка — ордера о выдаче
# всё равно идут под ней: иначе зарплата растворится в «Прочем»
SALARY_CATEGORY = 'Зарплата'


class CashOrder(Base):
    __tablename__ = 'cash_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(40), nullable=False, unique=True, index=True)
    kind = Column(String(4), nullable=False)
    # Номер подряд, у приходных и расходных свой
    number = Column(Integer, nullable=False)
    category = Column(String(60), nullable=False)
    amount = Column(Float, nullable=False)
    # Безнал в списке виден, но наличные в кассе не меняет
    method = Column(String(10), nullable=False, default=METHOD_CASH, server_default=METHOD_CASH)
    note = Column(String(300), nullable=True)
    employee_id = Column(Integer, ForeignKey('employees.id'), nullable=True)
    shift_id = Column(Integer, ForeignKey('shifts.id'), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    # Ошибочный ордер не удаляют: проводят обратный, и в списке видны оба
    reverses_id = Column(Integer, ForeignKey('cash_orders.id'), nullable=True)
    # Ордер о выдаче зарплаты — какая это выдача
    payout_id = Column(Integer, nullable=True, index=True)
    changed_at = Column(DateTime(timezone=True), default=get_moscow_time)

    @property
    def sign(self):
        """+1 — деньги пришли, −1 — ушли. Отмена переворачивает знак."""
        value = 1 if self.kind == KIND_IN else -1
        return -value if self.reverses_id else value

    @property
    def cash_effect(self):
        """На сколько ордер меняет наличные в кассе."""
        return self.sign * (self.amount or 0) if self.method == METHOD_CASH else 0.0
