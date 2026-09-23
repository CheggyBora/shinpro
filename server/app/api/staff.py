"""
Вход в дашборд и управление доступом.

Для человека это выглядит так же, как вход клиента:

    ввёл телефон  →  первый раз: код  →  придумал ПИН
                  →  дальше всегда: ПИН

Разница в том, кого пускают. Клиентом становится любой, кто подтвердил
свой номер. Сотрудника заводит владелец: человек с улицы, знающий чужой
номер, увидит здесь ровно то же, что и при неверном коде.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (StaffUser, ALL_PERMISSIONS, PERMISSION_TITLES,
                        ROLE_TITLES, ROLE_PERMISSIONS, PERM_STAFF)
from app.security import create_staff_token, current_staff, require
from app.services.auth_service import AuthError, NeedEmail
from app.services.staff_service import StaffService, StaffError
from app.utils import format_phone

router = APIRouter(prefix='/staff', tags=['Дашборд: вход и доступ'])


# ----------------------------------------------------------------------
# Что приходит и уходит
# ----------------------------------------------------------------------

class PhoneIn(BaseModel):
    phone: str


class CodeRequestIn(BaseModel):
    phone: str
    email: Optional[str] = None


class VerifyIn(BaseModel):
    phone: str
    code: str


class PinLoginIn(BaseModel):
    phone: str
    pin: str


class PinIn(BaseModel):
    pin: str


class StartOut(BaseModel):
    step: str
    channel: str


class StaffOut(BaseModel):
    id: int
    phone: str
    name: Optional[str] = None
    role: str
    role_title: str
    permissions: List[str] = []
    is_active: bool = True
    pin_is_set: bool = False


class TokenOut(BaseModel):
    token: str
    staff: StaffOut


class StaffIn(BaseModel):
    phone: str
    name: Optional[str] = None
    role: str = 'admin'
    # None — права как у роли. Список — свой набор
    permissions: Optional[List[str]] = None


class StaffPatchIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None


def _out(staff):
    return StaffOut(
        id=staff.id,
        phone=format_phone(staff.phone),
        name=staff.name,
        role=staff.role,
        role_title=staff.role_title,
        permissions=staff.allowed(),
        is_active=staff.is_active,
        pin_is_set=bool(staff.pin_hash))


# ----------------------------------------------------------------------
# Вход
# ----------------------------------------------------------------------

@router.post('/start', response_model=StartOut,
             summary='Что спросить у сотрудника, который ввёл телефон')
def start(payload: PhoneIn, db: Session = Depends(get_db)):
    """
    Первый шаг входа.

    Про незаведённый номер отвечаем так же, как про «первый заход»:
    иначе по форме входа можно перебрать номера и узнать, кто работает
    в шиномонтаже.
    """
    service = StaffService(db)
    try:
        step, _ = service.start(payload.phone)
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return StartOut(step=step, channel=service.channel())


@router.post('/code', summary='Выслать код сотруднику')
def request_code(payload: CodeRequestIn, db: Session = Depends(get_db)):
    try:
        seconds, channel = StaffService(db).request_code(
            payload.phone, payload.email)
    except NeedEmail as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={'email_required': True, 'detail': str(e)})
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {'expires_in_seconds': seconds, 'channel': channel}


@router.post('/verify', response_model=TokenOut, summary='Проверить код и войти')
def verify(payload: VerifyIn, db: Session = Depends(get_db)):
    try:
        staff = StaffService(db).verify_code(payload.phone, payload.code)
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return TokenOut(token=create_staff_token(staff), staff=_out(staff))


@router.post('/login', response_model=TokenOut,
             summary='Обычный вход: телефон и ПИН')
def login(payload: PinLoginIn, db: Session = Depends(get_db)):
    try:
        staff = StaffService(db).login_by_pin(payload.phone, payload.pin)
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(e))

    return TokenOut(token=create_staff_token(staff), staff=_out(staff))


@router.post('/pin', response_model=TokenOut, summary='Задать или сменить ПИН')
def set_pin(payload: PinIn, staff: StaffUser = Depends(current_staff),
            db: Session = Depends(get_db)):
    try:
        StaffService(db).set_pin(staff, payload.pin)
    except AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return TokenOut(token=create_staff_token(staff), staff=_out(staff))


@router.get('/me', response_model=StaffOut, summary='Кто я и что мне доступно')
def me(staff: StaffUser = Depends(current_staff)):
    return _out(staff)


# ----------------------------------------------------------------------
# Люди и права
# ----------------------------------------------------------------------

@router.get('/roles', summary='Роли и права — для экрана настройки доступа')
def roles(staff: StaffUser = Depends(require(PERM_STAFF))):
    return {
        'roles': [{'key': key, 'title': title,
                   'permissions': ROLE_PERMISSIONS.get(key, [])}
                  for key, title in ROLE_TITLES.items()],
        'permissions': [{'key': key, 'title': PERMISSION_TITLES[key]}
                        for key in ALL_PERMISSIONS],
    }


@router.get('/people', response_model=List[StaffOut], summary='Кто имеет доступ')
def people(staff: StaffUser = Depends(require(PERM_STAFF)),
           db: Session = Depends(get_db)):
    return [_out(row) for row in StaffService(db).people()]


@router.post('/people', response_model=StaffOut, summary='Завести сотрудника')
def add_person(payload: StaffIn,
               staff: StaffUser = Depends(require(PERM_STAFF)),
               db: Session = Depends(get_db)):
    try:
        row = StaffService(db).add(
            staff, payload.phone, payload.name, payload.role,
            payload.permissions)
    except StaffError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return _out(row)


@router.patch('/people/{staff_id}', response_model=StaffOut,
              summary='Изменить роль, права или закрыть доступ')
def update_person(staff_id: int, payload: StaffPatchIn,
                  staff: StaffUser = Depends(require(PERM_STAFF)),
                  db: Session = Depends(get_db)):
    try:
        row = StaffService(db).update(
            staff, staff_id, name=payload.name, role=payload.role,
            permissions=payload.permissions,
            is_active=payload.is_active)
    except StaffError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))

    return _out(row)


@router.get('/log', summary='Кто заходил и что менял')
def log(limit: int = 100, staff: StaffUser = Depends(require(PERM_STAFF)),
        db: Session = Depends(get_db)):
    return [{'happened_at': row.happened_at, 'action': row.action,
             'detail': row.detail, 'phone': format_phone(row.phone or '')}
            for row in StaffService(db).actions(limit)]
