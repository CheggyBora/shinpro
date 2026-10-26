"""
Склад: позиции, расход по услугам и движения (docs/stock.md).

Включается в настройках и по умолчанию выключен. Пока выключен,
таблицы просто пустуют, а расходник у услуги — сумма в рублях, как было.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text

from config import Base
from utils import get_moscow_time

GOODS, MATERIAL = 'goods', 'material'
KIND_TITLES = {GOODS: 'товар', MATERIAL: 'материал'}
UNITS = ['шт', 'л', 'кг', 'м', 'уп']


class StockItem(Base):
    __tablename__ = 'stock_items'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uid = Column(String(40), nullable=False, unique=True, index=True)
    direction = Column(String(10), nullable=False, default='tire', server_default='tire')
    kind = Column(String(10), nullable=False, default=MATERIAL, server_default=MATERIAL)
    name = Column(String(200), nullable=False)
    unit = Column(String(10), nullable=False, default='шт', server_default='шт')

    # Остаток может уйти в минус: на полке бывает то, что забыли
    # оприходовать, и продажу из-за этого не останавливаем
    quantity = Column(Float, nullable=False, default=0.0, server_default='0')
    min_quantity = Column(Float, nullable=False, default=0.0, server_default='0')

    # Отпускная — обязательна: по ней продаётся товар и вычитается расход
    # материалов. Закупка — по желанию, чтобы видеть наценку товара
    price = Column(Float, nullable=False, default=0.0, server_default='0')
    purchase_price = Column(Float, nullable=True)

    # Товар продаётся в наряде как позиция прайса — вот она
    service_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default='1')
    updated_at = Column(DateTime(timezone=True), default=get_moscow_time)

    @property
    def state(self):
        if (self.quantity or 0) < 0:
            return 'neg'
        if (self.quantity or 0) < (self.min_quantity or 0):
            return 'low'
        return 'ok'


class ServiceMaterial(Base):
    """Сколько материала уходит на одно выполнение услуги."""
    __tablename__ = 'service_materials'

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Float, nullable=False, default=1.0)


class StockMove(Base):
    """Движение по складу: приход, списание по наряду, возврат, правка."""
    __tablename__ = 'stock_moves'

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(Integer, nullable=False, index=True)
    change = Column(Float, nullable=False)
    reason = Column(String(20), nullable=False)          # receive / order / refund / correct
    order_id = Column(Integer, nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=get_moscow_time)
