"""
Касса точки: приходные и расходные ордера (docs/cash.md).

Ордера рождаются в цеху — там касса, там выдают деньги и пересчитывают
ящик. Сюда приезжает копия, чтобы владелец видел с телефона, сколько
ушло на воду и расходники и сошлась ли касса при закрытии смены.
Править ордера отсюда нельзя.

Ордер узнаём по uid цеха, а не по номеру: номер у цеха свой, и после
переустановки программы он может пойти заново, а uid — нет.

Ошибочный ордер не удаляют: его отменяет обратный ордер того же вида
и на ту же сумму со ссылкой reverses_uid. В итогах обратный ордер
идёт с минусом, и пара даёт ноль, а в списке видны оба.
"""
from sqlalchemy import (Column, Integer, String, Float, DateTime, Text,
                        ForeignKey, UniqueConstraint, text)

from app.database import Base
from app.utils import now as shop_now

# in — приходный, out — расходный
KIND_IN = 'in'
KIND_OUT = 'out'
KINDS = (KIND_IN, KIND_OUT)

# cash — из кассы или в кассу, noncash — безнал: касса не меняется
METHOD_CASH = 'cash'
METHOD_NONCASH = 'noncash'
METHODS = (METHOD_CASH, METHOD_NONCASH)


class CashOrder(Base):
    __tablename__ = 'cash_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    uid = Column(String(40), nullable=False)

    kind = Column(String(4), default=KIND_OUT, nullable=False,
                  server_default=KIND_OUT)
    # Номер подряд, свой у каждого вида — как в цеху
    number = Column(Integer, nullable=True)
    # Статья: «Вода», «Зарплата»… Список ведёт цех, убранная статья
    # остаётся у старых ордеров — поэтому здесь просто строка
    category = Column(String(60), nullable=True)
    amount = Column(Float, default=0.0, nullable=False, server_default='0')
    method = Column(String(10), default=METHOD_CASH, nullable=False,
                    server_default=METHOD_CASH)
    # Кому / за что
    note = Column(Text, nullable=True)

    employee_local_id = Column(Integer, nullable=True)
    shift_local_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False,
                        server_default=text('CURRENT_TIMESTAMP'), index=True)

    # Обратный ордер: uid того, который он отменяет
    reverses_uid = Column(String(40), nullable=True)
    # Ордер, проведённый выдачей зарплаты
    payout_local_id = Column(Integer, nullable=True)
    changed_at = Column(DateTime, nullable=True)


# uid уникален внутри точки: у другой точки может оказаться такой же
UniqueConstraint(CashOrder.shop_id, CashOrder.uid,
                 name='uq_cash_orders_shop_uid')
