from sqlalchemy import Column, Integer, String, DateTime
from config import Base
from utils import get_moscow_time


class Settings(Base):
    __tablename__ = 'settings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), nullable=True)

    # Когда настройку поменяли. Нужно для обмена: часть настроек меняют
    # и в цеху, и в дашборде, и когда они разъехались — прав тот, кто
    # поставил позже. Без метки «позже» определить нечем, и правка из
    # дашборда затиралась бы при следующем обмене
    changed_at = Column(DateTime, default=get_moscow_time,
                        onupdate=get_moscow_time)
