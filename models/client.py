from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from config import Base
from utils import get_moscow_time

class Client(Base):
    __tablename__ = 'clients'

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_number = Column(String(50), nullable=True)
    name = Column(String(200), nullable=True)

    # Телефон хранится в нормализованном виде (только цифры, 79099018931).
    # Это ключ, по которому клиент опознаётся при повторном визите, поэтому
    # по нему стоит индекс. Для показа человеку используйте utils.format_phone().
    phone = Column(String(50), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=get_moscow_time)

    # Машины клиента: один клиент может обслуживать несколько автомобилей
    cars = relationship("Car", back_populates="client")

    def __repr__(self):
        return f"<Client #{self.id} {self.name or 'без имени'} {self.phone or ''}>"
