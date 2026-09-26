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

from sqlalchemy import (Column, Integer, String, Boolean, DateTime, Float,
                        Text, ForeignKey)
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

    # --- Оплата пользования ---------------------------------------------
    #
    # До какого числа оплачено. Пусто — ограничений нет: так живёт свой
    # шиномонтаж, которому никто не выставляет счёт.
    paid_until = Column(DateTime, nullable=True)

    # Название тарифа — строкой, а не ссылкой на справочник: пока тариф
    # один, а заводить таблицу из одной строки незачем
    plan = Column(String(64), nullable=True)

    # Закрыт вручную: не за неоплату, а по решению — просьба заказчика,
    # спор, что угодно. Отдельно от срока оплаты, чтобы одно не
    # маскировало другое
    blocked_at = Column(DateTime, nullable=True)
    block_reason = Column(String(255), nullable=True)

    note = Column(Text, nullable=True)

    # --- Бот для напоминаний клиентам ------------------------------------
    #
    # Свой у каждого заказчика: клиент «Колеса» не должен получать
    # сообщения от бота «РИФа», даже если они стоят на одном сервере.
    telegram_bot_token = Column(String(255), nullable=True)
    telegram_bot_username = Column(String(64), nullable=True)

    # Телеграм присылает обновления на адрес с этой строкой внутри.
    # Без неё любой, кто узнал адрес сервера, мог бы слать боту всё что
    # угодно от имени телеграма
    telegram_secret = Column(String(64), nullable=True, index=True)

    shops = relationship('Shop', back_populates='account',
                         cascade='all, delete-orphan')
    payments = relationship('AccountPayment', back_populates='account',
                            cascade='all, delete-orphan',
                            order_by='AccountPayment.paid_at.desc()')

    @property
    def is_paid(self):
        return self.paid_until is None or self.paid_until >= shop_now()


class AccountPayment(Base):
    """
    Платёж за пользование программой.

    Каждый платёж — строка: когда пришёл, сколько, за какой period и
    откуда про него узнали. Срок в аккаунте (paid_until) складывается
    из этих строк, а не правится руками: иначе через полгода никто не
    объяснит, почему там стоит именно эта дата.

    Способ хранится строкой: сегодня это «отметили вручную», завтра —
    название платёжной системы. external_id — её номер платежа, по
    нему повторное уведомление не создаст вторую строку.
    """
    __tablename__ = 'account_payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False,
                        index=True)

    amount = Column(Float, default=0.0, nullable=False)
    paid_at = Column(DateTime, default=shop_now, nullable=False, index=True)

    # За какой отрезок заплатили. Нужен для ответа на вопрос «за что
    # эти деньги», а не только «сколько всего пришло»
    period_from = Column(DateTime, nullable=True)
    period_to = Column(DateTime, nullable=True)

    method = Column(String(32), default='manual', nullable=False)
    external_id = Column(String(128), nullable=True, unique=True, index=True)

    comment = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=shop_now, nullable=False)

    account = relationship('Account', back_populates='payments')


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
