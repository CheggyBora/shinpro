"""
Фото из цеха и телефоны мастеров, которые их шлют.

Фотография рождается на телефоне мастера: он видит грыжу на боковине
и показывает её клиенту. Раньше путь был такой — скинуть на компьютер,
найти наряд, переслать. На потоке это не делается никогда, и клиент
узнаёт о дефекте словами, которым верит не всегда.

Поэтому телефон отправляет прямо сюда, а компьютер в цеху только
показывает, что ушло.
"""
from sqlalchemy import (Column, Integer, String, Text, DateTime, ForeignKey,
                        Boolean, Index)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now


class MasterDevice(Base):
    """
    Телефон мастера, которому разрешено слать фото в эту точку.

    Заводится один раз: приёмщик показывает QR, мастер наводит камеру.
    Дальше телефон помнит себя сам, и сканировать больше не надо —
    иначе на потоке этим не пользовались бы.

    Телефон, а не человек: мастера меняются, смены меняются, а разбор
    «кто снял» в цеху ведётся по имени на экране, а не по учётной
    записи. Заводить каждому мастеру логин с паролем ради трёх фото
    в день — это способ сделать так, чтобы фото не слали вовсе.
    """
    __tablename__ = 'master_devices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)

    # Чем телефон представляется при каждом заходе. Храним как есть:
    # это не пароль от денег, а пропуск в один цех на отправку фото,
    # и отозвать его можно одной кнопкой
    token = Column(String(64), nullable=False, unique=True, index=True)

    # Как мастер назвал себя при первом заходе. Нужно только для того,
    # чтобы в наряде было видно, кто прислал
    name = Column(String(80), nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    shop = relationship('Shop')


class OpenOrder(Base):
    """
    Машина, которая сейчас в цеху. Слепок, а не история.

    Мастеру надо ткнуть в свою машину, а не набирать госномер пальцем
    в перчатке. Для этого телефон должен знать, что сейчас в боксе, —
    а знает это цех, и присылает списком при каждом обмене.

    Строки заменяются целиком: это снимок на момент обмена, и машина,
    которая уехала, не должна висеть в списке до вечера.
    """
    __tablename__ = 'open_orders'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)

    local_id = Column(Integer, nullable=False)
    license_plate = Column(String(20), nullable=False)

    # work — на посту, waiting — ждёт очереди
    state = Column(String(16), default='waiting', nullable=False)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=shop_now, nullable=False)

    shop = relationship('Shop')


class OrderPhoto(Base):
    """
    Фотография по наряду: дефект, согласование, «вот как было».

    Клиенту уходит сразу, как только мастер нажал «отправить». Второго
    шага нет намеренно: любой шаг «потом переслать» на потоке означает
    «никогда».

    Файл лежит на диске, в базе только путь. Складывать картинки в
    базу — значит получить базу, которую нельзя ни скопировать, ни
    восстановить за разумное время.
    """
    __tablename__ = 'order_photos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True,
                       index=True)

    # Номер наряда в базе цеха. По нему приёмщик видит фото в наряде,
    # а клиент — в своей истории
    order_local_id = Column(Integer, nullable=True, index=True)
    license_plate = Column(String(20), nullable=True)

    path = Column(String(255), nullable=False)
    comment = Column(Text, nullable=True)

    # Кто снял — как назвался на телефоне
    author = Column(String(80), nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False, index=True)

    # Когда и чем сказали клиенту. Пусто — значит сказать было нечем:
    # ни Телеграма, ни кабинета. Это видно в наряде, и приёмщик
    # понимает, что надо звонить
    sent_at = Column(DateTime, nullable=True)
    channel = Column(String(16), nullable=True)
    last_error = Column(String(255), nullable=True)

    shop = relationship('Shop')
    client = relationship('Client')


Index('ix_open_orders_shop_plate', OpenOrder.shop_id, OpenOrder.license_plate)
Index('ix_order_photos_shop_order', OrderPhoto.shop_id,
      OrderPhoto.order_local_id)
