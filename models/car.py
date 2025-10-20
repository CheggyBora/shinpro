from sqlalchemy import Column, Integer, String
from config import Base

class Car(Base):
    __tablename__ = 'cars'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    license_plate = Column(String(50), unique=True, nullable=False)
    vehicle_type = Column(String(20))
    wheel_diameter = Column(String(10))
