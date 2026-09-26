"""
Клиент, его машины, устройства и коды входа.

Клиент на сервере — это тот же человек, что в базе цеха, но со своим
номером строки. Связь держим через local_id: цех остаётся главным,
сервер только знает, кому что показывать.

Про два поля сразу, чтобы не путаться:

* **почта** — по ней человек входит, на неё приходит код подтверждения;
* **телефон** — по нему он находится в базе цеха.

Одного не хватает. Цех записывает клиентов по телефону и про почту
ничего не знает, поэтому вход только по почте оставил бы человека
с пустым кабинетом: ни машин, ни хранения, ни истории.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, Boolean, DateTime,
                        ForeignKey, Index)
from sqlalchemy.orm import relationship

from sqlalchemy import UniqueConstraint

from app.database import Base
from app.utils import now as shop_now


class Client(Base):
    __tablename__ = 'clients'

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Номер строки этого же клиента в базе цеха. Пусто — значит клиент
    # завёлся в приложении и цех о нём ещё не знает.
    local_id = Column(Integer, nullable=True, index=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True,
                        index=True)

    # Телефон — то, чем человек входит, и по нему же он находится
    # в базе цеха. Одно поле на обе роли: заводить второе означало бы
    # рано или поздно их разъехать
    # Телефон уникален внутри аккаунта, а не вообще: один и тот же
    # человек может обслуживаться в двух не связанных шиномонтажах
    phone = Column(String(20), nullable=False, index=True)
    phone_verified_at = Column(DateTime, nullable=True)

    # Почта — запасной канал для кода подтверждения, если шиномонтаж
    # не хочет платить за SMS. Для входа не нужна
    email = Column(String(255), nullable=True, index=True)

    name = Column(String(200), nullable=True)

    # --- Напоминания в Telegram ------------------------------------------
    #
    # chat_id — куда писать. Пусто — человек не подключал бота, и
    # напоминания ему не идут: писать без спроса нельзя
    telegram_chat_id = Column(String(32), nullable=True, index=True)
    telegram_linked_at = Column(DateTime, nullable=True)

    # Одноразовый код привязки: кабинет отдаёт ссылку на бота с ним,
    # бот присылает его обратно, и по нему находится этот человек
    telegram_code = Column(String(32), nullable=True, index=True)
    telegram_code_until = Column(DateTime, nullable=True)

    # ПИН-код. Хранится отпечатком: украдут базу — войти по ней нельзя
    pin_hash = Column(String(128), nullable=True)
    pin_updated_at = Column(DateTime, nullable=True)

    # Сколько раз подряд ошиблись ПИНом. Четыре цифры перебираются
    # за минуту, если не считать попытки
    pin_failures = Column(Integer, default=0, nullable=False)
    pin_blocked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)

    # Заблокированный клиент не может записываться: нужно, если кто-то
    # записывается и не приезжает раз за разом
    is_blocked = Column(Boolean, default=False, nullable=False)

    cars = relationship('Car', back_populates='client',
                        cascade='all, delete-orphan')
    devices = relationship('Device', back_populates='client',
                           cascade='all, delete-orphan')


class Car(Base):
    __tablename__ = 'cars'

    id = Column(Integer, primary_key=True, autoincrement=True)
    local_id = Column(Integer, nullable=True, index=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True,
                        index=True)

    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True, index=True)

    # Госномер в том же нормализованном виде, что и в цеху
    license_plate = Column(String(20), nullable=False, index=True)
    vehicle_type = Column(String(20), nullable=True)
    wheel_diameter = Column(String(10), nullable=True)
    wheels_assembled = Column(Boolean, nullable=True)

    client = relationship('Client', back_populates='cars')


UniqueConstraint(Client.account_id, Client.phone,
                 name='uq_clients_account_phone')
UniqueConstraint(Client.account_id, Client.local_id,
                 name='uq_clients_account_local')


class Device(Base):
    """
    Телефон, с которого клиент заходил.

    Нужен для двух вещей: слать push и пускать по ПИН-коду. ПИН из
    четырёх цифр сам по себе слаб, поэтому вход по нему разрешён только
    с устройства, которое хотя бы раз подтвердило почту кодом. Украли
    почту — с чужого телефона по ПИНу всё равно не зайти.

    Устройств у клиента может быть несколько — телефон и планшет,
    старый и новый. Уведомление уходит на все, а мёртвые токены
    отваливаются сами: Apple и Google скажут, что адресата нет.
    """
    __tablename__ = 'devices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False, index=True)

    # Постоянный номер устройства, который приложение придумывает себе
    # при первой установке. По нему узнаём знакомый телефон
    device_id = Column(String(64), nullable=False, unique=True, index=True)

    # Устройство подтвердило почту кодом — значит, ему можно доверять ПИН
    is_trusted = Column(Boolean, default=False, nullable=False)

    # Сколько раз подряд ошиблись ПИНом на этом устройстве
    pin_failures = Column(Integer, default=0, nullable=False)
    pin_blocked_at = Column(DateTime, nullable=True)

    push_token = Column(String(255), nullable=True, index=True)
    platform = Column(String(10), nullable=True)     # ios / android
    app_version = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    last_seen_at = Column(DateTime, default=shop_now, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    client = relationship('Client', back_populates='devices')


class LoginCode(Base):
    """
    Код подтверждения, который уходит на почту.

    Сам код не храним — только его отпечаток. Если базу когда-нибудь
    украдут, войти по ней не получится. Ошибки считаем: подобрать
    четыре цифры перебором иначе было бы делом минуты.
    """
    __tablename__ = 'login_codes'

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True,
                        index=True)

    # Кому ушёл код: телефон в нормализованном виде или почтовый ящик
    login = Column(String(255), nullable=False, index=True)
    channel = Column(String(10), default='sms', nullable=False)
    code_hash = Column(String(128), nullable=False)

    # Зачем запрашивали код: первый вход или забытый ПИН
    purpose = Column(String(20), default='signup', nullable=False)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)

    attempts = Column(Integer, default=0, nullable=False)
    used_at = Column(DateTime, nullable=True)


Index('ix_login_codes_login_created', LoginCode.login, LoginCode.created_at)
