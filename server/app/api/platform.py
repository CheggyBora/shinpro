"""
Заказчики, коды подключения и страница скачивания программы.

Три части, у каждой свои права:

    /platform/...   «Заказчики» — только владелец сервера (его номер)
    /dashboard/points   «Точки» организации — её владелец: код, чтобы
                    переподключить компьютер в цеху
    /connect, /setup    без входа — по коду подключения

Как устроен запуск точки — app/services/onboarding.py.
"""
import os
from datetime import datetime
from typing import Optional

from fastapi import (APIRouter, Depends, Form, HTTPException, Query, Request,
                     status)
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Shop, StaffUser, PERM_STAFF
from app.security import current_staff, require
from app.services import billing, onboarding, tenancy
from app.services.onboarding import CodeError, OnboardingError, TooManyTries

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'web')

router = APIRouter(prefix='/platform', tags=['Заказчики'])
points_router = APIRouter(prefix='/dashboard', tags=['Дашборд: точки'])
connect_router = APIRouter(tags=['Подключение точки'])


def platform_owner(staff: StaffUser = Depends(current_staff),
                   db: Session = Depends(get_db)):
    if not onboarding.is_platform_owner(db, staff):
        # Не говорим, что раздел есть: остальным о нём знать незачем
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Не найдено')
    return staff


def _bad(e):
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


def _account(db, account_id):
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Заказчик не найден')
    return account


def _date(value):
    if not value:
        return None
    try:
        day = datetime.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail='Дата выглядит неправильно')
    # «Оплачено до 30.11» — значит весь день 30-го
    return day.replace(hour=23, minute=59, second=59)


# ----------------------------------------------------------------------
# Заказчики
# ----------------------------------------------------------------------

class CustomerIn(BaseModel):
    name: str
    owner_phone: str
    slug: Optional[str] = None
    shop_name: Optional[str] = None
    paid_until: Optional[str] = None


class PointIn(BaseModel):
    name: str


class PayIn(BaseModel):
    amount: float = 0
    months: int = 1
    until: Optional[str] = None
    comment: Optional[str] = None


class BlockIn(BaseModel):
    reason: Optional[str] = None


@router.get('/me', summary='Видит ли вошедший «Заказчиков»')
def me(staff: StaffUser = Depends(platform_owner)):
    return {'platform': True}


@router.get('/accounts', summary='Все организации на сервере')
def accounts(staff: StaffUser = Depends(platform_owner), db: Session = Depends(get_db)):
    rows = db.query(Account).order_by(Account.id).all()
    return {
        'accounts': [onboarding.account_out(db, account) for account in rows],
        'program': onboarding.program_info(),
        'setup_url': onboarding.setup_url(db),
    }


@router.post('/accounts', summary='Новый заказчик и код его первой точки')
def create(payload: CustomerIn, staff: StaffUser = Depends(platform_owner),
           db: Session = Depends(get_db)):
    try:
        account, shop, code = onboarding.create_customer(
            db, payload.name, payload.owner_phone, slug=payload.slug,
            shop_name=payload.shop_name, paid_until=_date(payload.paid_until),
            staff_id=staff.id)
    except OnboardingError as e:
        raise _bad(e)
    return {'account': onboarding.account_out(db, account),
            'code': onboarding.code_out(db, shop, code)}


@router.post('/accounts/{account_id}/shops', summary='Ещё одна точка заказчика')
def add_shop(account_id: int, payload: PointIn,
             staff: StaffUser = Depends(platform_owner), db: Session = Depends(get_db)):
    account = _account(db, account_id)
    try:
        shop, code = onboarding.add_point(db, account, payload.name, staff.id)
    except OnboardingError as e:
        raise _bad(e)
    return {'account': onboarding.account_out(db, account),
            'code': onboarding.code_out(db, shop, code)}


@router.post('/accounts/{account_id}/pay', summary='Записать оплату')
def pay(account_id: int, payload: PayIn,
        staff: StaffUser = Depends(platform_owner), db: Session = Depends(get_db)):
    account = _account(db, account_id)
    if payload.amount < 0 or not 1 <= payload.months <= 36:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail='Проверьте сумму и срок')
    billing.record_payment(db, account, payload.amount, months=payload.months,
                           until=_date(payload.until),
                           comment=(payload.comment or '').strip()[:500] or None)
    db.refresh(account)
    return onboarding.account_out(db, account)


@router.post('/accounts/{account_id}/block', summary='Закрыть доступ')
def block(account_id: int, payload: BlockIn,
          staff: StaffUser = Depends(platform_owner), db: Session = Depends(get_db)):
    account = _account(db, account_id)
    home = tenancy.home_account(db)
    if home is not None and home.id == account.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail='Свою организацию закрыть нельзя — вы потеряете вход')
    billing.block(db, account, payload.reason)
    return onboarding.account_out(db, account)


@router.post('/accounts/{account_id}/unblock', summary='Открыть доступ')
def unblock(account_id: int, staff: StaffUser = Depends(platform_owner),
            db: Session = Depends(get_db)):
    account = _account(db, account_id)
    billing.unblock(db, account)
    return onboarding.account_out(db, account)


def _shop(db, shop_id, account_id=None):
    shop = db.get(Shop, shop_id)
    if shop is None or (account_id is not None and shop.account_id != account_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Точка не найдена')
    return shop


@router.post('/shops/{shop_id}/code', summary='Код подключения точки')
def shop_code(shop_id: int, staff: StaffUser = Depends(platform_owner),
              db: Session = Depends(get_db)):
    shop = _shop(db, shop_id)
    try:
        row = onboarding.issue_code(db, shop, staff.id)
    except OnboardingError as e:
        raise _bad(e)
    return onboarding.code_out(db, shop, row)


@router.delete('/shops/{shop_id}/code', summary='Отменить код')
def drop_shop_code(shop_id: int, staff: StaffUser = Depends(platform_owner),
                   db: Session = Depends(get_db)):
    onboarding.cancel_code(db, _shop(db, shop_id))
    return {'ok': True}


# --- Программа для скачивания ------------------------------------------

@router.get('/program', summary='Какая версия программы отдаётся')
def program(staff: StaffUser = Depends(platform_owner)):
    return onboarding.program_info()


@router.post('/program/start', summary='Начать загрузку новой версии')
def program_start(staff: StaffUser = Depends(platform_owner)):
    return {'upload': onboarding.start_upload(),
            'part_bytes': onboarding.PART_MAX_BYTES}


@router.post('/program/part', summary='Кусок файла программы')
async def program_part(request: Request, upload: str = Query(...),
                       offset: int = Query(..., ge=0),
                       staff: StaffUser = Depends(platform_owner)):
    data = await request.body()
    try:
        return {'size': onboarding.add_part(upload, offset, data)}
    except OnboardingError as e:
        raise _bad(e)


@router.post('/program/finish', summary='Файл загружен целиком')
def program_finish(upload: str = Query(...), size: int = Query(..., ge=1),
                   staff: StaffUser = Depends(platform_owner)):
    try:
        return onboarding.finish_upload(upload, size)
    except OnboardingError as e:
        raise _bad(e)


# ----------------------------------------------------------------------
# «Точки» в дашборде организации
# ----------------------------------------------------------------------

@points_router.get('/points', summary='Точки организации и их связь')
def points(staff: StaffUser = Depends(require(PERM_STAFF)), db: Session = Depends(get_db)):
    account = db.get(Account, staff.account_id)
    shops = sorted(account.shops, key=lambda s: s.id) if account else []
    return {'points': [onboarding.point_out(db, shop) for shop in shops if shop.is_active],
            'setup_url': onboarding.setup_url(db)}


@points_router.post('/points/{shop_id}/code', summary='Код, чтобы подключить компьютер')
def point_code(shop_id: int, staff: StaffUser = Depends(require(PERM_STAFF)),
               db: Session = Depends(get_db)):
    shop = _shop(db, shop_id, staff.account_id)
    try:
        row = onboarding.issue_code(db, shop, staff.id)
    except OnboardingError as e:
        raise _bad(e)
    return onboarding.code_out(db, shop, row)


@points_router.delete('/points/{shop_id}/code', summary='Отменить код')
def drop_point_code(shop_id: int, staff: StaffUser = Depends(require(PERM_STAFF)),
                    db: Session = Depends(get_db)):
    onboarding.cancel_code(db, _shop(db, shop_id, staff.account_id))
    return {'ok': True}


# ----------------------------------------------------------------------
# По коду: страница скачивания и программа цеха
# ----------------------------------------------------------------------

class CodeIn(BaseModel):
    code: str


def _address(request):
    return request.client.host if request.client else '?'


def _code_error(e):
    if isinstance(e, TooManyTries):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@connect_router.post('/connect/check', summary='Подходит ли код — не тратит его')
def connect_check(payload: CodeIn, request: Request, db: Session = Depends(get_db)):
    try:
        row = onboarding.find(db, payload.code, _address(request))
    except CodeError as e:
        raise _code_error(e)
    answer = onboarding.describe(db, row.shop)
    answer['expires_at'] = row.expires_at.isoformat()
    answer['program'] = onboarding.program_info().get('exists', False)
    return answer


@connect_router.post('/connect', summary='Подключить программу цеха по коду')
def connect(payload: CodeIn, request: Request, db: Session = Depends(get_db)):
    """
    Программа цеха вводит код и получает ключ обмена. Код погашен:
    второй компьютер с тем же кодом не подключится.
    """
    try:
        shop, key = onboarding.redeem(db, payload.code, _address(request))
    except CodeError as e:
        raise _code_error(e)
    answer = onboarding.describe(db, shop)
    answer['key'] = key
    return answer


def setup_page():
    with open(os.path.join(WEB_DIR, 'setup.html'), encoding='utf-8') as page:
        return HTMLResponse(page.read(), headers={'Cache-Control': 'no-cache'})


@connect_router.get('/setup', response_class=HTMLResponse, include_in_schema=False)
def setup():
    return setup_page()


def _setup_error(text):
    from html import escape
    return HTMLResponse(
        status_code=400,
        content='<!doctype html><meta charset="utf-8"><meta name="viewport" '
                'content="width=device-width,initial-scale=1"><title>Код не подошёл</title>'
                '<body style="font-family:system-ui,sans-serif;max-width:480px;margin:40px auto;'
                f'padding:0 16px"><h1>Не получилось</h1><p>{escape(text)}</p>'
                '<p><a href="javascript:history.back()">Назад</a></p></body>')


@connect_router.post('/setup/download', include_in_schema=False)
def setup_download(request: Request, code: str = Form(''), db: Session = Depends(get_db)):
    """Обычная форма, а не fetch: 40 МБ браузер скачивает сам, с полосой."""
    try:
        onboarding.find(db, code, _address(request))
    except CodeError as e:
        return _setup_error(str(e))
    path = onboarding.program_path()
    if not os.path.isfile(path):
        return _setup_error('Программа ещё не загружена на сервер. '
                            'Напишите тому, кто прислал код.')
    return FileResponse(path, media_type='application/vnd.microsoft.portable-executable',
                        filename=onboarding.PROGRAM_FILE,
                        headers={'Cache-Control': 'no-store'})
