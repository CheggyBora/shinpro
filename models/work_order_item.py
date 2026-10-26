from sqlalchemy import Column, Integer, Float, Text, Boolean, ForeignKey, String
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

    # Снимок «это товар, а не работа». Снимок, а не взгляд в прайс:
    # позицию могут потом переделать из товара в услугу, и закрытые
    # наряды вместе с начисленными зарплатами от этого не должны
    # поменяться задним числом
    is_goods = Column(Boolean, default=False, nullable=False)

    # Скидку по этой позиции поставили вручную. Общая скидка на наряд
    # такую позицию не трогает: значение выставил человек осознанно,
    # и затирать его автоматикой нельзя.
    discount_manual = Column(Boolean, default=False, nullable=False)
    
    # На каких колёсах делали ремонт или правку: «ПЛ,ЗП». Пусто — услуга
    # колесо не спрашивает или наряд старый. См. services/wheel_service.py
    wheels = Column(String(100), nullable=True)

    # Направление строки — снимок с услуги: наряд бывает «и то и то», и
    # выручка в отчётах делится по строкам. Строке мойки назначают, кто её
    # делал: начисляется ему, а не всем на смене
    direction = Column(String(10), default='tire', server_default='tire', nullable=False)
    employee_id = Column(Integer, nullable=True)

    work_order = relationship("WorkOrder", backref="items")
    service = relationship("Service", backref="order_items")
