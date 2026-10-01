"""
Очередь уведомлений клиенту.

Не отправляем сразу и напрямую по трём причинам. Канал может не
ответить — сообщение не должно пропасть. Напоминание о записи уходит
не сейчас, а накануне — его надо где-то хранить. И одно и то же
напоминание не должно уйти дважды, даже если задача запустится дважды.

Поэтому каждое уведомление — строка: кому, о чём, когда отправить и
отправлено ли. Отправляет её отдельная задача, а всё остальное
просто кладёт строку и забывает.

Чем отправить — решается не здесь и не при создании, а в момент
отправки: к тому времени человек мог подключить телеграм или, наоборот,
удалить кабинет с телефона.
"""
from datetime import datetime

from sqlalchemy import (Column, Integer, String, DateTime, Text, ForeignKey,
                        Index)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now

# О чём напоминаем
KIND_BOOKED = 'booked'            # записали — подтверждение сразу
KIND_REMINDER = 'reminder'        # завтра приезжать
KIND_CANCELLED = 'cancelled'      # запись отменили
KIND_MOVED = 'moved'              # запись перенесли
KIND_STORAGE = 'storage'          # заканчивается срок хранения
KIND_SEASON = 'season'            # пора переобуваться

TITLES = {
    KIND_BOOKED: 'Подтверждение записи',
    KIND_REMINDER: 'Напоминание о записи',
    KIND_CANCELLED: 'Запись отменена',
    KIND_MOVED: 'Запись перенесена',
    KIND_STORAGE: 'Заканчивается хранение',
    KIND_SEASON: 'Пора переобуваться',
}

# На что ссылаются сезонные напоминания. Осень и весна порознь: иначе
# человек, которого позвали осенью, весной остался бы без приглашения
ABOUT_AUTUMN = 'season-autumn'
ABOUT_SPRING = 'season-spring'

# Чем отправили. Каналов два: бот в телеграме и уведомление в браузере.
# Пишем в строку, чтобы по журналу было видно, что у человека работает
BY_TELEGRAM = 'telegram'
BY_PUSH = 'webpush'

# Что с уведомлением
WAITING = 'waiting'
SENT = 'sent'
FAILED = 'failed'
SKIPPED = 'skipped'


class Notice(Base):
    """Одно сообщение клиенту: что, кому и когда."""
    __tablename__ = 'notices'

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False,
                        index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False,
                       index=True)

    kind = Column(String(20), nullable=False, index=True)
    text = Column(Text, nullable=False)

    # На что оно ссылается: запись, комплект. Нужно, чтобы отменить
    # неотправленное напоминание, когда запись отменили
    about = Column(String(20), nullable=True)
    about_id = Column(Integer, nullable=True, index=True)

    send_at = Column(DateTime, default=shop_now, nullable=False, index=True)
    state = Column(String(20), default=WAITING, nullable=False, index=True)

    sent_at = Column(DateTime, nullable=True)
    channel = Column(String(20), nullable=True)
    attempts = Column(Integer, default=0, nullable=False)
    last_error = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)

    client = relationship('Client')


# Задача отправки ищет созревшие: что пора и ещё не ушло
Index('ix_notices_due', Notice.state, Notice.send_at)
