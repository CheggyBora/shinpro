"""
Бот: что приходит от телеграма и что отдаётся кабинету.

Адрес вебхука содержит секрет аккаунта — по нему сервер и понимает,
чей это бот. Без секрета любой, кто узнал адрес сервера, слал бы боту
что угодно от имени телеграма.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Client
from app.security import current_client
from app.services import telegram

router = APIRouter(tags=['Напоминания в Telegram'])


@router.post('/telegram/{secret}', include_in_schema=False)
async def webhook(secret: str, request: Request,
                  db: Session = Depends(get_db)):
    """
    Сообщение человека боту.

    Телеграм ждёт быстрый ответ и повторяет запрос, если его не
    получил. Поэтому отвечаем «принято» в любом случае: разбираться с
    непонятным сообщением — наша забота, а не его.
    """
    account = db.query(Account).filter(
        Account.telegram_secret == secret).first()

    if account is None or not account.is_active:
        # Не говорим, что секрет не тот: незачем подсказывать тому,
        # кто их перебирает
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Не найдено')

    try:
        update = await request.json()
    except Exception:
        return {'ok': True}

    try:
        telegram.handle_update(db, account, update)
    except telegram.TelegramError:
        # Телеграм не ответил на нашу отправку — повторять его же
        # запрос бессмысленно, он ничего не исправит
        pass

    return {'ok': True}


@router.get('/me/telegram', summary='Подключены ли напоминания')
def status_of(client: Client = Depends(current_client),
              db: Session = Depends(get_db)):
    """
    Состояние напоминаний и ссылка на бота.

    Ссылка выдаётся с одноразовым кодом: человек нажимает её, бот
    получает код и понимает, кто пришёл.
    """
    account = db.query(Account).filter(
        Account.id == client.account_id).first()

    ready = bool(account and account.telegram_bot_username
                 and account.telegram_bot_token)

    if not ready:
        return {'available': False, 'connected': False, 'url': None}

    if client.telegram_chat_id:
        return {'available': True, 'connected': True, 'url': None,
                'since': client.telegram_linked_at}

    code = telegram.link_code(db, client)
    return {'available': True, 'connected': False,
            'url': telegram.link_url(account, code)}


@router.delete('/me/telegram', summary='Отключить напоминания')
def disconnect(client: Client = Depends(current_client),
               db: Session = Depends(get_db)):
    telegram.unlink(db, client)
    return {'connected': False}
