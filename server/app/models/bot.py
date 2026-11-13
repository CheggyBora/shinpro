"""
Бот организации на сервере (решение владельца 13.11.2026).

Бот один на организацию, им управляет сервер: токен вписывают в
дашборде, телеграм присылает все сообщения сюда. Так переписка
(партнёры, сотрудники, клиенты) живёт и при выключенном компьютере в
цеху, и её видно с телефона.

Здесь — кто писал боту. Программа в цеху раньше узнавала это сама через
getUpdates; с ботом на сервере так нельзя (телеграм отдаёт сообщения
либо вебхуку, либо getUpdates), и список людей цех получает при обмене.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.database import Base
from app.utils import now as shop_now


class TelegramChat(Base):
    __tablename__ = 'telegram_chats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False, index=True)
    chat_id = Column(String(32), nullable=False)
    username = Column(String(64), nullable=True)
    name = Column(String(200), nullable=True)
    started_at = Column(DateTime, default=shop_now, nullable=False)
    # Ждём от этого человека ответ на кнопку: «price:<uid работы>» —
    # следующее число будет ценой партнёра
    pending = Column(String(60), nullable=True)
    last_at = Column(DateTime, default=shop_now, nullable=False)

    __table_args__ = (UniqueConstraint('account_id', 'chat_id', name='uq_telegram_chats_account_chat'),)
