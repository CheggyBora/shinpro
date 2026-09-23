from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean
from config import Base
from utils import get_moscow_time

class Employee(Base):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)

    # Имя нужно там, где речь о деньгах человека: «Игорь — 18 400 ₽»
    # понятнее, чем «№3 — 18 400 ₽». В остальных местах — наряды,
    # чеки, смены — сотрудник по-прежнему номер: так он подписывается
    # в наряде, и менять этот порядок в цеху незачем
    name = Column(String(100), nullable=True)

    salary_percent = Column(Float, default=40.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
    is_active = Column(Boolean, default=True)

    @property
    def title(self):
        """Как называть сотрудника там, где показываем зарплату."""
        if not self.name:
            return f"№{self.id}"
        # Номер оставляем рядом: по нему сотрудник подписан в нарядах,
        # и при разборе «за что начислили» связать одно с другим надо
        # без расспросов
        return f"{self.name} (№{self.id})"
