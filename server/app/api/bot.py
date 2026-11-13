"""
Дашборд → «Оформление» → «Бот в Telegram» (решение владельца 13.11.2026).

Бот один на организацию, им управляет сервер. Владелец вписывает токен
здесь — или одной кнопкой переносит бота, который уже работает в
программе на точке (его токен цех и так присылает при обмене). Сервер
говорит телеграму слать сообщения сюда; программа в цеху получает токен
и список людей при обмене и сама телеграм больше не опрашивает.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Shop, StaffUser, PERM_STAFF
from app.security import require
from app.services import shop_settings, telegram

router = APIRouter(prefix='/dashboard', tags=['Дашборд: бот'])


class BotIn(BaseModel):
    token: Optional[str] = None
    # Взять токен бота, который вписан в программе на точке
    from_shop: bool = False


def _account(db, staff):
    account = db.get(Account, staff.account_id) if staff.account_id else None
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Организация не найдена')
    return account


def shop_token(db, account):
    """Токен бота из программы на точке — первый, что нашёлся у точек организации."""
    for shop in db.query(Shop).filter(Shop.account_id == account.id).order_by(Shop.id).all():
        token = (shop_settings.get(db, 'telegram_token', shop=shop) or '').strip()
        if token:
            return token
    return ''


def _out(db, account):
    from_shop = shop_token(db, account)
    return {
        'connected': bool(account.telegram_bot_token),
        'username': account.telegram_bot_username or '',
        'people': len(telegram.people(db, account)) if account.telegram_bot_token else 0,
        # Есть бот в программе на точке и он ещё не на сервере — предложим перенести
        'shop_bot': bool(from_shop) and from_shop != (account.telegram_bot_token or ''),
    }


def _base_url(request: Request):
    """Адрес сервера для телеграма — тот, по которому открыт дашборд, всегда https."""
    host = request.headers.get('x-forwarded-host') or request.headers.get('host') or ''
    return f'https://{host.split(",")[0].strip()}'


@router.get('/bot', summary='Бот в Telegram: подключён ли')
def get_bot(staff: StaffUser = Depends(require(PERM_STAFF)), db: Session = Depends(get_db)):
    return _out(db, _account(db, staff))


@router.post('/bot', summary='Подключить бота к серверу')
def post_bot(payload: BotIn, request: Request,
             staff: StaffUser = Depends(require(PERM_STAFF)), db: Session = Depends(get_db)):
    account = _account(db, staff)
    token = shop_token(db, account) if payload.from_shop else (payload.token or '').strip()
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Вставьте токен бота от @BotFather' if not payload.from_shop
                            else 'В программе на точке бот не вписан')
    try:
        telegram.connect_bot(db, account, token)
        telegram.set_webhook(account, _base_url(request))
    except telegram.TelegramError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f'Телеграм не принял бота: {e}')
    return _out(db, account)


@router.delete('/bot', summary='Отключить бота от сервера')
def delete_bot(staff: StaffUser = Depends(require(PERM_STAFF)), db: Session = Depends(get_db)):
    account = _account(db, staff)
    telegram.disconnect_bot(db, account)
    return _out(db, account)
