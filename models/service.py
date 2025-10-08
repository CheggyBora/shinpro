from sqlalchemy import Column, Integer, String, Float, Boolean
from config import Base

class Service(Base):
    __tablename__ = 'services'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    price_r13 = Column(Float, default=0.0)
    price_r14 = Column(Float, default=0.0)
    price_r15 = Column(Float, default=0.0)
    price_r16 = Column(Float, default=0.0)
    price_r17 = Column(Float, default=0.0)
    price_r18 = Column(Float, default=0.0)
    price_r19 = Column(Float, default=0.0)
    price_r20 = Column(Float, default=0.0)
    price_r21 = Column(Float, default=0.0)
    price_r22 = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
