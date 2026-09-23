from sqlalchemy import Column, Integer, String, Text, DateTime
from config import Base
from utils import get_moscow_time


class AuditLog(Base):
    """
    Журнал действий, затрагивающих деньги и настройки.

    Нужен, чтобы можно было ответить на вопрос «кто удалил наряд» или
    «когда поменяли цену». Раньше такие действия не оставляли следов.
    """
    __tablename__ = 'audit_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time, index=True)

    # Что произошло: короткий код вида 'order.delete', 'price.change'
    action = Column(String(50), nullable=False, index=True)

    # Понятное человеку описание для показа в интерфейсе
    description = Column(Text, nullable=True)

    # К какой записи относится: тип и номер (наряд, услуга, сотрудник)
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(Integer, nullable=True)

    # Кто действовал, если известно
    employee_id = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<AuditLog {self.created_at} {self.action}>"
