from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from config import Base

class Car(Base):
    __tablename__ = 'cars'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Номер хранится в нормализованном виде (utils.normalize_plate):
    # верхний регистр, без пробелов, латинские буквы заменены на кириллические.
    # Иначе "а123вв777" и "A123BB777" создавали бы разные машины.
    license_plate = Column(String(50), unique=True, nullable=False, index=True)

    vehicle_type = Column(String(20))
    wheel_diameter = Column(String(10))

    # Колёса в сборе (второй комплект на своих дисках) или только шины.
    # От этого втрое отличается время работы: перекидка готовых колёс
    # против разбортовки, забортовки и балансировки каждого колеса.
    # None — ещё не выяснили.
    wheels_assembled = Column(Boolean, nullable=True)

    # Владелец машины. Один клиент может иметь несколько машин.
    # nullable=True: машину можно обслужить и без указания клиента.
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True, index=True)

    client = relationship("Client", back_populates="cars")

    def __repr__(self):
        return f"<Car #{self.id} {self.license_plate}>"
