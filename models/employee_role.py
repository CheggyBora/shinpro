import json

from sqlalchemy import Column, Integer, String, Text
from config import Base


class EmployeeRole(Base):
    """
    Категория сотрудника: мастер, сезонный мастер, сезонный съёмщик.

    У категории — список услуг, с которых этой категории зарплата не
    начисляется. Съёмщик не делает ремонт и правку, и процент с них ему
    не положен: их доля делится только между теми, кому начисляется.

    Список хранится названиями услуг, а не номерами: в прайсе одна и
    та же «Правка литого диска» заведена отдельно для легковых, джипов
    и коммерческих, а исключать её надо целиком.
    """
    __tablename__ = 'employee_roles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(100), nullable=False, unique=True)

    # JSON-список названий услуг: ["Правка литого диска", ...]
    excluded_services = Column(Text, nullable=True)

    @property
    def excluded(self):
        """Названия услуг, с которых не начисляется, — множеством."""
        try:
            names = json.loads(self.excluded_services or '[]')
        except ValueError:
            names = []
        return {name for name in names if name}

    def set_excluded(self, names):
        self.excluded_services = json.dumps(
            sorted({(n or '').strip() for n in names if (n or '').strip()}),
            ensure_ascii=False)

    def __repr__(self):
        return f"<EmployeeRole {self.title}>"
