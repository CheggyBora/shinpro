"""
Чей это номер строки: точка + номер строки в её базе → клиент или машина.

У каждой точки своя база, и номера строк в них совпадают: клиент №5
в одной точке и клиент №5 в другой — разные люди. Пока связь держали
в самом клиенте (account + local_id), вторая точка сети переписывала
клиентов первой (ревью 26.10.2026). Теперь у каждой точки свои связи,
а человек на сервере один — его узнают по телефону, машину — по номеру.
"""
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint

from app.database import Base


class ShopClient(Base):
    __tablename__ = 'shop_clients'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False, index=True)
    local_id = Column(Integer, nullable=False)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False, index=True)


class ShopCar(Base):
    __tablename__ = 'shop_cars'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False, index=True)
    local_id = Column(Integer, nullable=False)
    car_id = Column(Integer, ForeignKey('cars.id'), nullable=False, index=True)


UniqueConstraint(ShopClient.shop_id, ShopClient.local_id, name='uq_shop_clients_local')
UniqueConstraint(ShopCar.shop_id, ShopCar.local_id, name='uq_shop_cars_local')
