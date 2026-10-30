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
    # Подпись QR-ключа, по которому подключился телефон: второй раз тот же
    # код не сработает. Держим в базе — процессов у сервера два
    link_sig = Column(String(32), nullable=True, unique=True)

    # --- Кабинет мастера (решение владельца 27.10.2026) ------------------
    #
    # Кто держит телефон: сотрудник цеха (его номер в базе точки). Мастер
    # выбирает себя один раз и вводит ПИН, который ему поставил приёмщик.
    # Пусто — телефон анонимный, как раньше: шлёт фото, но своих машин,
    # заработка и согласований у него нет
    employee_local_id = Column(Integer, nullable=True)
    # Неверный ПИН подряд и до какого времени вход закрыт: четыре цифры
    # перебираются за минуты, если не останавливать
    pin_fails = Column(Integer, default=0, nullable=False, server_default='0')
    locked_until = Column(DateTime, nullable=True)

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
    license_plate = Column(String(50), nullable=False)

    # work — на посту, waiting — ждёт очереди
    state = Column(String(16), default='waiting', nullable=False)
    started_at = Column(DateTime, nullable=True)

    # Сколько займёт работа: по нему видно, когда освободится пост
    planned_minutes = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=shop_now, nullable=False)

    # Для кабинета мастера: чьи это машины и что с ними делают. Мастера —
    # номера сотрудников через запятую, как в наряде цеха
    masters = Column(String(200), nullable=True)
    car = Column(String(120), nullable=True)
    client_name = Column(String(200), nullable=True)
    wheel_diameter = Column(String(10), nullable=True)
    wash_class = Column(String(16), nullable=True)
    directions = Column(String(20), nullable=True)
    services = Column(Text, nullable=True)
    post = Column(Integer, nullable=True)
    # Работа закончена; клиенту сказали «готово»
    finished_at = Column(DateTime, nullable=True)
    told_at = Column(DateTime, nullable=True)

    shop = relationship('Shop')

    def master_ids(self):
        result = []
        for part in (self.masters or '').split(','):
            part = part.strip()
            if part.isdigit():
                result.append(int(part))
        return result


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
    license_plate = Column(String(50), nullable=True)

    path = Column(String(255), nullable=False)
    comment = Column(Text, nullable=True)

    # Кто снял — как назвался на телефоне
    author = Column(String(80), nullable=True)

    # photo — снимок мастера для клиента; cover — обложка наряда: машина
    # целиком, снятая при приезде (docs/order_photo.md). Обложка клиенту
    # не уходит и в его кабинете не видна: это снимок для цеха
    kind = Column(String(10), default='photo', nullable=False,
                  server_default='photo')

    created_at = Column(DateTime, default=shop_now, nullable=False, index=True)

    # photo или video. Видео живёт две недели (решение владельца
    # 27.10.2026): оно в десятки раз тяжелее снимка, а спорят о нём,
    # пока машина в цеху
    media = Column(String(8), default='photo', nullable=False,
                   server_default='photo')
    content_type = Column(String(60), nullable=True)
    size = Column(Integer, nullable=True)
    # Кто снял — номер сотрудника, если телефон знает своего мастера
    employee_local_id = Column(Integer, nullable=True)
    # Клиент открыл файл в кабинете — мастеру «посмотрел»
    viewed_at = Column(DateTime, nullable=True)

    # Когда и чем сказали клиенту. Пусто — значит сказать было нечем:
    # ни Телеграма, ни кабинета. Это видно в наряде, и приёмщик
    # понимает, что надо звонить
    sent_at = Column(DateTime, nullable=True)
    channel = Column(String(16), nullable=True)
    last_error = Column(String(255), nullable=True)

    shop = relationship('Shop')
    client = relationship('Client')


PHOTO = 'photo'
COVER = 'cover'

MEDIA_PHOTO = 'photo'
MEDIA_VIDEO = 'video'


class ShopService(Base):
    """
    Прайс точки — копия из цеха, чтобы мастер мог предложить работу.

    Цены по радиусам и классам мойки: какую взять, сервер решает по
    наряду. Скидки цех применит сам, когда услуга встанет в наряд, —
    клиенту обещаем цену по прайсу.
    """
    __tablename__ = 'shop_services'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    local_id = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    direction = Column(String(10), default='tire', nullable=False)
    # {"R16": 650, "sedan": 500, "": 300} — JSON строкой
    prices = Column(Text, nullable=True)
    editable = Column(Boolean, default=False, nullable=False)


# Что ответил клиент на предложение мастера
OFFER_PENDING = 'pending'
OFFER_YES = 'yes'
OFFER_CALL = 'call'
OFFER_NO = 'no'


class WorkOffer(Base):
    """
    Мастер предлагает работу: «грыжа — замена шины 650 ₽».

    Клиент получает ссылку со снимком и кнопками «Согласен» / «Позвоните
    мне» / «Не надо». Ответ забирает цех при живом обмене: согласие —
    услуга встаёт в наряд, «позвоните» — приёмщику напоминание.
    """
    __tablename__ = 'work_offers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=True,
                       index=True)
    order_local_id = Column(Integer, nullable=False, index=True)
    license_plate = Column(String(50), nullable=True)
    photo_id = Column(Integer, ForeignKey('order_photos.id'), nullable=True)

    # [{"local_id": 12, "name": "Замена шины R16", "price": 650}]
    items = Column(Text, nullable=False)
    total = Column(Integer, default=0, nullable=False)
    comment = Column(String(500), nullable=True)

    # Ссылка для клиента: /o/<token>. Входа не нужно — ссылка и есть
    # пропуск, её получает только он
    token = Column(String(64), nullable=False, unique=True, index=True)

    employee_local_id = Column(Integer, nullable=True)
    author = Column(String(80), nullable=True)

    state = Column(String(10), default=OFFER_PENDING, nullable=False)
    created_at = Column(DateTime, default=shop_now, nullable=False, index=True)
    sent_at = Column(DateTime, nullable=True)
    channel = Column(String(16), nullable=True)
    last_error = Column(String(255), nullable=True)
    answered_at = Column(DateTime, nullable=True)
    # Цех забрал ответ (или напоминание «клиент молчит»)
    taken_at = Column(DateTime, nullable=True)
    reminded_at = Column(DateTime, nullable=True)

    photo = relationship('OrderPhoto')


# Что нажал мастер на машине
EVENT_START = 'start'
EVENT_DONE = 'done'


class MasterEvent(Base):
    """
    «Начал» или «Готово» с телефона мастера.

    Наряд живёт в цеху, поэтому сервер его не меняет: событие ждёт, пока
    цех заберёт его при живом обмене (раз в 20 секунд) и сам начнёт или
    закончит работу. «Готово» клиенту сервер говорит сразу — человек
    ждёт машину сейчас.
    """
    __tablename__ = 'master_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    order_local_id = Column(Integer, nullable=False)
    kind = Column(String(10), nullable=False)
    employee_local_id = Column(Integer, nullable=True)
    author = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=shop_now, nullable=False)
    # Клиенту сказали «готово» — цеху не надо говорить второй раз
    told = Column(Boolean, default=False, nullable=False)
    taken_at = Column(DateTime, nullable=True, index=True)


class Arrival(Base):
    """
    Машина с телефона: сняли при приезде, номер распознали, ждём цех.

    Наряд по ней создаёт приёмщик в цеху — телефон только подаёт машину.
    Цех забирает ждущие при живом обмене и говорит, чем кончилось: создал
    наряд — снимок становится его обложкой; закрыл окно — машина снята.
    """
    __tablename__ = 'arrivals'

    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False,
                     index=True)
    photo_id = Column(Integer, ForeignKey('order_photos.id'), nullable=True)

    plate = Column(String(50), nullable=False, server_default='')
    # «tire», «wash» или «tire,wash» — как у наряда
    directions = Column(String(20), default='tire', nullable=False,
                        server_default='tire')

    created_at = Column(DateTime, default=shop_now, nullable=False,
                        index=True)
    # Цех разобрался: создал наряд или закрыл окно
    done_at = Column(DateTime, nullable=True)
    order_local_id = Column(Integer, nullable=True)

    photo = relationship('OrderPhoto')


Index('ix_open_orders_shop_plate', OpenOrder.shop_id, OpenOrder.license_plate)
Index('ix_order_photos_shop_order', OrderPhoto.shop_id,
      OrderPhoto.order_local_id)
