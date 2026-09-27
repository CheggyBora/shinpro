"""
Подписка браузера на уведомления.

Веб-пуш устроен не как телеграм: у нас нет адреса человека, есть
адрес его браузера — длинная ссылка на сервер Google или Apple плюс
два ключа, которыми письмо шифруется. Отправляя, мы не знаем, кто
и когда его прочитает; браузер сам разбудит страницу и покажет.

Подписка принадлежит устройству, а не человеку: с телефона и с
компьютера будет две. Поэтому строк на одного клиента может быть
несколько, и слать надо во все — неизвестно, что у него под рукой.

Подписки умирают молча: человек удалил ярлык, почистил браузер,
сменил телефон. Сервер пуша отвечает на такую 404 или 410, и строку
надо удалить, иначе мы будем стучаться в неё годами.
"""
from sqlalchemy import (Column, Integer, String, DateTime, ForeignKey,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils import now as shop_now


class PushSubscription(Base):
    """Один браузер, готовый принять уведомление."""
    __tablename__ = 'push_subscriptions'

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False,
                        index=True)
    client_id = Column(Integer, ForeignKey('clients.id'), nullable=False,
                       index=True)

    # Куда слать. Адрес выдаёт браузер, он же и принадлежит браузеру:
    # подделать его нельзя, но и выбрать мы его не можем
    endpoint = Column(String(500), nullable=False)

    # Ключи, которыми шифруется сообщение. Без них сервер пуша письмо
    # не примет, а браузер не расшифрует
    p256dh = Column(String(200), nullable=False)
    auth = Column(String(100), nullable=False)

    # Чтобы в кабинете было понятно, какое это устройство
    device = Column(String(120), nullable=True)

    created_at = Column(DateTime, default=shop_now, nullable=False)
    last_ok_at = Column(DateTime, nullable=True)
    failures = Column(Integer, default=0, nullable=False)

    client = relationship('Client')

    # Один браузер — одна строка на человека. Но телефон в семье может
    # быть общим, и тогда на нём законно живут подписки двух клиентов:
    # уведомления придут обоим, каждому своё
    __table_args__ = (
        UniqueConstraint('client_id', 'endpoint', name='uq_push_client_point'),
    )
