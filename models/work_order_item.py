from sqlalchemy import Column, Integer, Float, Text, ForeignKey
from sqlalchemy.orm import relationship
from config import Base

class WorkOrderItem(Base):
    __tablename__ = 'work_order_items'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    work_order_id = Column(Integer, ForeignKey('work_orders.id'), nullable=False)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=False)
    quantity = Column(Integer, default=1)
    price = Column(Float, nullable=False)
    discount_percent = Column(Integer, default=0)
    comment = Column(Text, nullable=True)
    
    work_order = relationship("WorkOrder", backref="items")
    service = relationship("Service", backref="order_items")
