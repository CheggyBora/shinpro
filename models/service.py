from sqlalchemy import Column, Integer, String, Float, Boolean
from config import Base

class Service(Base):
    __tablename__ = 'services'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    vehicle_type = Column(String(50), default='car')
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
    price_r23 = Column(Float, default=0.0)
    price_r24 = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    editable_price = Column(Boolean, default=False)

    # Себестоимость расходников на ЕДИНИЦУ услуги: грибок, жгут, вентиль,
    # грузики. Вычитается из суммы наряда до расчёта зарплаты, чтобы механик
    # получал процент с работы, а не с материалов.
    # Ноль по умолчанию: пока значения не заполнены, зарплата считается
    # ровно так же, как считалась раньше.
    consumable_cost = Column(Float, default=0.0, nullable=False)

    # Сколько минут занимает услуга на одно выполнение. Нужно, чтобы
    # оценивать время в живой очереди и при записи.
    # От диаметра колеса не зависит.
    duration_minutes = Column(Integer, default=0, nullable=False)

    # Наибольшая скидка, допустимая для этой услуги, в процентах.
    # Ограничивает и ручную скидку по позиции, и общую скидку на наряд:
    # иначе смысл ограничения теряется.
    # 100 по умолчанию — то есть без ограничений, пока не задали своё.
    max_discount_percent = Column(Integer, default=100, nullable=False)
