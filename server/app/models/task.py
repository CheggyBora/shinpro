"""
Календарь задач и контрагенты (docs/calendar.md).

Задача одна и та же в цеху и на сервере: её узнают по uid, а не по
номеру строки. Номер строки у цеха свой, у сервера свой, а задачу
ставят с обеих сторон — из программы цеха и из дашборда, — и по
номеру они бы разошлись после первого же обмена.

Удалённую задачу не стираем, а помечаем: строка должна дожить до
обмена, иначе вторая сторона так и не узнает, что её удалили, и
задача воскреснет при следующей присылке.
"""
from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Date,
                        Float, Text, ForeignKey, Index, UniqueConstraint)

from app.database import Base
from app.utils import now as shop_now

# Разделы задач — в этом порядке их показывают везде
WORK = 'work'
STORAGE = 'storage'
TIRES = 'tires'
PAINT = 'paint'
CATEGORIES = (WORK, STORAGE, TIRES, PAINT)

CATEGORY_TITLES = {
    WORK: 'Рабочая',
    STORAGE: 'Хранение',
    TIRES: 'Шины',
    PAINT: 'Покраска',
}

# Откуда задача взялась
SOURCE_SHOP = 'shop'
SOURCE_DASHBOARD = 'dashboard'
SOURCE_AUTO = 'auto'
SOURCE_CABINET = 'cabinet'
SOURCES = (SOURCE_SHOP, SOURCE_DASHBOARD, SOURCE_AUTO, SOURCE_CABINET)


class Task(Base):
    __tablename__ = 'tasks'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)

    # uuid4 строкой. Задачам из кабинета — свой, предсказуемый
    # («cab-appt-12»): повторный запрос не должен ставить вторую
    uid = Column(String(40), nullable=False)

    category = Column(String(10), default=WORK, nullable=False)
    due_date = Column(Date, nullable=False)
    # «HH:MM» или пусто: у «заказать грузики» времени нет
    due_time = Column(String(5), nullable=True)

    title = Column(String(200), nullable=False)
    note = Column(Text, nullable=True)

    license_plate = Column(String(20), nullable=True)
    # Для показа там, где клиента в базе нет
    client_name = Column(String(200), nullable=True)
    client_phone = Column(String(20), nullable=True)

    counterparty_uid = Column(String(40), nullable=True)
    # Номер комплекта хранения в цеху. Через запятую, если их несколько
    storage_ref = Column(String(100), nullable=True)
    amount = Column(Float, nullable=True)

    done_at = Column(DateTime, nullable=True)
    done_by = Column(String(100), nullable=True)
    deleted = Column(Boolean, default=False, nullable=False,
                     server_default='0')

    source = Column(String(20), default=SOURCE_SHOP, nullable=False)
    created_by = Column(String(100), nullable=True)

    # Время правки ставится руками, а не onupdate: при обмене это время
    # правки в цеху, а не время, когда строка доехала. По нему решается,
    # чья правка новее, и подменять его нельзя
    created_at = Column(DateTime, default=shop_now, nullable=False)
    updated_at = Column(DateTime, default=shop_now, nullable=False)


class Counterparty(Base):
    """Поставщик, склад, покрасочная — с кем цех работает по задачам."""
    __tablename__ = 'counterparties'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    uid = Column(String(40), nullable=False)

    name = Column(String(200), nullable=False)
    kind = Column(String(200), nullable=True)       # чем занимается
    contact = Column(String(200), nullable=True)
    phone = Column(String(40), nullable=True)
    email = Column(String(200), nullable=True)
    address = Column(String(300), nullable=True)
    inn = Column(String(20), nullable=True)
    note = Column(Text, nullable=True)
    deleted = Column(Boolean, default=False, nullable=False,
                     server_default='0')

    updated_at = Column(DateTime, default=shop_now, nullable=False)


# uid уникален внутри точки: задача другой точки с тем же uid — другая
# задача, и затирать её чужим обменом нельзя
UniqueConstraint(Task.shop_id, Task.uid, name='uq_tasks_shop_uid')
UniqueConstraint(Counterparty.shop_id, Counterparty.uid,
                 name='uq_counterparties_shop_uid')

# Обмен спрашивает «что поменялось после», календарь — «что на эти дни»
Index('ix_tasks_shop_updated', Task.shop_id, Task.updated_at)
Index('ix_tasks_shop_due', Task.shop_id, Task.due_date)
Index('ix_counterparties_shop_updated', Counterparty.shop_id,
      Counterparty.updated_at)
