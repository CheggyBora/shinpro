"""
Склад точки — снимок из цеха (docs/stock.md).

Склад ведут в цеху: там пробивают наряды, списывают материалы и
принимают товар. Сюда приезжает копия остатков целиком, чтобы владелец
видел с телефона, чего мало и что ушло в минус. Править склад отсюда
нельзя — поэтому и слияния правок, как у задач, нет: каждый снимок
заменяет предыдущий.

Позицию узнаём по uid цеха, а не по номеру строки: номер у цеха свой,
и после переустановки программы он поедет, а uid — нет.
"""
from sqlalchemy import (Column, Integer, String, Float, DateTime, ForeignKey,
                        UniqueConstraint)

from app.database import Base
from app.utils import now as shop_now

# Направление — то же, что у задач и записи
TIRE = 'tire'
WASH = 'wash'
DIRECTIONS = (TIRE, WASH)

# goods — товар на продажу, material — уходит на услуги
GOODS = 'goods'
MATERIAL = 'material'
KINDS = (GOODS, MATERIAL)


class StockItem(Base):
    __tablename__ = 'stock_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    uid = Column(String(40), nullable=False)

    name = Column(String(200), nullable=False)
    direction = Column(String(10), default=TIRE, nullable=False,
                       server_default=TIRE)
    kind = Column(String(10), default=MATERIAL, nullable=False,
                  server_default=MATERIAL)
    unit = Column(String(10), default='шт', nullable=False)

    # Остаток может быть отрицательным: пробили наряд раньше, чем
    # оприходовали поставку. Это не ошибка, а сигнал владельцу
    quantity = Column(Float, default=0, nullable=False)
    min_quantity = Column(Float, default=0, nullable=False)
    price = Column(Float, default=0, nullable=False)
    purchase_price = Column(Float, nullable=True)

    # Время правки в цеху, а не время, когда строка доехала
    updated_at = Column(DateTime, default=shop_now, nullable=False)


# uid уникален внутри точки: у другой точки может быть свой «Герметик»
# с тем же uid, и затирать его чужим снимком нельзя
UniqueConstraint(StockItem.shop_id, StockItem.uid,
                 name='uq_stock_items_shop_uid')
