from sqlalchemy import Column, Integer, Float, Text, Boolean, ForeignKey
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

    # Снимок себестоимости на момент добавления в наряд — так же, как price.
    # Когда подорожает закупка, уже закрытые наряды и начисленные
    # зарплаты не должны измениться задним числом.
    consumable_cost = Column(Float, default=0.0, nullable=False)

    # Скидку по этой позиции поставили вручную. Общая скидка на наряд
    # такую позицию не трогает: значение выставил человек осознанно,
    # и затирать его автоматикой нельзя.
    discount_manual = Column(Boolean, default=False, nullable=False)
    
    work_order = relationship("WorkOrder", backref="items")
    service = relationship("Service", backref="order_items")
