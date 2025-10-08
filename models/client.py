from sqlalchemy import Column, Integer, String
from config import Base

class Client(Base):
    __tablename__ = 'clients'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_number = Column(String(50), nullable=True)
    name = Column(String(200), nullable=True)
