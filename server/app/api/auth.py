"""
Вход в кабинет: телефон и ПИН-код.

Для человека это выглядит так:

    ввёл телефон  →  первый раз: код  →  придумал ПИН
                  →  дальше всегда: ПИН

Одинаково и в приложении, и на странице записи в браузере: кабинет
у клиента один, и заводить его дважды он не должен.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client
from app.schemas import (StartIn, StartOut, CodeRequestIn, CodeSentOut,
                         VerifyIn, PinLoginIn, PinIn, TokenOut, DeviceIn,
                         ProfileOut, ProfileIn, CarOut)
from app.security import create_token, current_client
from app.services.auth_service import (AuthService, AuthError, NeedEmail,
                                       STEP_SET_PIN)
from app.utils import format_phone

router = APIRouter(prefix='/auth', tags=['Вход'])


def _token_answer(client):
    return TokenOut(token=create_token(client.id), client_id=client.id,
                    name=client.name, phone=format_phone(client.phone),
                    pin_is_set=bool(client.pin_hash))


def _profile(client):
    return ProfileOut(
        id=client.id,
        name=client.name,
        email=client.email,
        phone=format_phone(client.phone),
        pin_is_set=bool(client.pin_hash),
        cars=[CarOut.model_validate(car) for car in client.cars])


@router.post('/start', response_model=StartOut,
             summary='Что спросить у человека, который ввёл телефон')
def start(payload: StartIn, db: Session = Depends(get_db)):
    """
    Первый шаг входа.

    По ответу приложение решает: показать поле ПИНа или отправить
    человека подтверждать номер. Спрашивать его самого «вы у нас
    впервые?» незачем — программа это знает.
    """
    service = AuthService(db)
    try:
        step, known, blocked = service.start(payload.phone)
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return StartOut(step=step, is_known=known, pin_is_blocked=blocked,
                    channel=service.channel())


@router.post('/code', response_model=CodeSentOut,
             summary='Выслать код подтверждения')
def request_code(payload: CodeRequestIn, db: Session = Depends(get_db)):
    try:
        seconds, channel = AuthService(db).request_code(
            payload.phone, payload.email)
    except NeedEmail as e:
        # Не ошибка, а вопрос: страница должна показать поле почты
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={'email_required': True, 'detail': str(e)})
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return CodeSentOut(expires_in_seconds=seconds, channel=channel)


@router.post('/verify', response_model=TokenOut,
             summary='Проверить код и войти')
def verify(payload: VerifyIn, db: Session = Depends(get_db)):
    """
    Проверить код.

    Токен выдаём сразу: человек уже доказал, что номер его. ПИН он
    задаст следующим шагом — по полю pin_is_set видно, что пора.
    """
    service = AuthService(db)
    try:
        client = service.verify_code(payload.phone, payload.code)
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    if payload.device_id:
        service.register_push_token(client, payload.device_id, None)

    return _token_answer(client)


@router.post('/login', response_model=TokenOut,
             summary='Обычный вход: телефон и ПИН')
def login(payload: PinLoginIn, db: Session = Depends(get_db)):
    try:
        client = AuthService(db).login_by_pin(payload.phone, payload.pin)
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(e))

    return _token_answer(client)


@router.post('/pin', response_model=ProfileOut, summary='Задать или сменить ПИН')
def set_pin(payload: PinIn,
            client: Client = Depends(current_client),
            db: Session = Depends(get_db)):
    try:
        AuthService(db).set_pin(client, payload.pin)
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return _profile(client)


@router.delete('/pin', response_model=ProfileOut, summary='Убрать ПИН')
def forget_pin(client: Client = Depends(current_client),
               db: Session = Depends(get_db)):
    AuthService(db).forget_pin(client)
    return _profile(client)


@router.post('/device', summary='Запомнить устройство для уведомлений')
def register_device(payload: DeviceIn,
                    client: Client = Depends(current_client),
                    db: Session = Depends(get_db)):
    AuthService(db).register_push_token(
        client, payload.device_id, payload.push_token,
        payload.platform, payload.app_version)
    return {'ok': True}


@router.get('/me', response_model=ProfileOut, summary='Профиль и машины')
def profile(client: Client = Depends(current_client)):
    return _profile(client)


@router.patch('/me', response_model=ProfileOut, summary='Изменить имя')
def update_profile(payload: ProfileIn,
                   client: Client = Depends(current_client),
                   db: Session = Depends(get_db)):
    if payload.name is not None:
        client.name = payload.name.strip() or None
        db.commit()
        db.refresh(client)

    return _profile(client)
