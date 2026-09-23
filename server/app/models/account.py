"""
Кому принадлежит всё остальное: аккаунт и его точки.

Два уровня, и оба нужны.

**Аккаунт** — это заказчик программы. Своя база клиентов, свои
сотрудники дашборда, свои деньги. Данные разных аккаунтов не
пересекаются нигде и никогда: это не настройка видимости, а условие,
при котором программу вообще можно продать второму шиномонтажу.

**Точка** — конкретный шиномонтаж со своим компьютером в цеху. У
аккаунта их может быть одна или десять. Владелец видит их все и каждую
по отдельности; клиент записывается в ту, которая ему удобна, а
историю видит целиком.

Почему не один уровень. Если считать точку и заказчика одним и тем же,
то при открытии второй точки придётся либо заводить второго «заказчика»
и терять общую историю клиента, либо смешивать выручку двух точек в
одну кучу. Оба варианта неверны.

Ключ обмена выдаётся точке, а не аккаунту: программа в цеху
предъявляет его и этим говорит, кто она. Второй цех с чужим ключом
чужих данных не увидит.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Text,
                        ForeignKey)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now


class Account(Base):
    """Заказчик программы: один шиномонтаж или сеть."""
    __tablename__ = 'accounts'

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(200), nullable=False)

    # Короткое имя для ссылок: shinomontazh-rif -> /z/shinomontazh-rif
    slug = Column(String(64), nullable=False, unique=True, index=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=shop_now, nullable=False)

    # Для продажи другим: до какого числа оплачено пользование. Пусто —
    # ограничений нет. Проверку добавим, когда появится первый платящий:
    # поле заводим сейчас, чтобы потом не менять боевую базу
    paid_until = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)

    shops = relationship('Shop', back_populates='account',
                         cascade='all, delete-orphan')

    @property
    def is_paid(self):
        return self.paid_until is None or self.paid_until >= shop_now()


class Shop(Base):
    """
    Точка: шиномонтаж со своим компьютером в цеху.

    Ключ обмена лежит отпечатком, а не строкой. Украсть базу сервера
    и получить вместе с ней ключи ко всем цехам разом нельзя.
    """
    __tablename__ = 'shops'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False,
                        index=True)

    name = Column(String(200), nullable=False)
    slug = Column(String(64), nullable=False, unique=True, index=True)

    address = Column(String(300), nullable=True)
    phone = Column(String(20), nullable=True)

    # Отпечаток ключа обмена. Сам ключ показывается один раз при
    # создании точки — дальше его знает только программа в цеху
    sync_key_hash = Column(String(255), nullable=True, index=True)
    sync_key_set_at = Column(DateTime, nullable=True)
    last_sync_at = Column(DateTime, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=shop_now, nullable=False)

    account = relationship('Account', back_populates='shops')

    def __repr__(self):
        return f"<Shop #{self.id} {self.name}>"
