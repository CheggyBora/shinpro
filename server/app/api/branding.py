"""
Дашборд → «Оформление»: как организацию видят её клиенты и по каким
адресам открываются её запись и дашборд.

Решение владельца 27.10.2026: у каждой организации свой сайт записи и
свой дашборд. Наш поддомен (koleso.rif-service.ru) появляется сразу,
свой домен владелец подключает здесь: вписывает адрес, делает одну
запись у регистратора, остальное сервер делает сам (deploy/domains.sh).
"""
import socket
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Account, StaffUser, PERM_STAFF
from app.models.account import ROLE_LK, ROLE_ADMIN, KIND_OWN, DOMAIN_WAITING
from app.security import require
from app.services import branding, tenancy

router = APIRouter(prefix='/dashboard', tags=['Дашборд: оформление'])

ROLE_TITLES = {ROLE_LK: 'Запись и кабинет клиента', ROLE_ADMIN: 'Дашборд'}

STATUS_TITLES = {
    'waiting': 'Ждём запись в настройках домена',
    'active': 'Работает',
    'error': 'Не получилось',
}


def _account(db, staff):
    account = db.get(Account, staff.account_id) if staff.account_id else None
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Организация не найдена')
    return account


def _target(account, role):
    """На какой наш адрес направить свой домен (запись CNAME у регистратора)."""
    ours = tenancy.our_names(account)
    if ours.get(role):
        return ours[role]
    # У того, кто держит сервер, своих поддоменов нет — у него lk. и admin.
    for host in settings.HOME_HOSTS:
        if (role == ROLE_ADMIN) == host.startswith('admin.'):
            return host
    return settings.HOME_HOSTS[0] if settings.HOME_HOSTS else ''


_ip_cache = {}


def _ip_of(name):
    """Адрес сервера для записи типа A — на случай, если CNAME нельзя (koleso.ru без www)."""
    if not name:
        return ''
    if name not in _ip_cache:
        try:
            _ip_cache[name] = socket.gethostbyname(name)
        except OSError:
            return ''
    return _ip_cache[name]


def _rows(db, account):
    rows = {row.name: row for row in account.domains}
    home = tenancy.home_account(db)
    is_home = home is not None and home.id == account.id and settings.HOME_HOSTS

    ours = []
    if is_home:
        for host in settings.HOME_HOSTS:
            role = ROLE_ADMIN if host.startswith('admin.') else ROLE_LK
            ours.append({'name': host, 'role': role, 'status': 'active', 'note': None})
    else:
        for role, name in tenancy.our_names(account).items():
            row = rows.get(name)
            ours.append({'name': name, 'role': role,
                         'status': row.status if row else DOMAIN_WAITING,
                         'note': row.note if row else 'Сертификат выпускается'})

    own = []
    for row in account.domains:
        if row.kind != KIND_OWN:
            continue
        target = _target(account, row.role)
        label = row.name.split('.', 1)[0]
        own.append({
            'id': row.id, 'name': row.name, 'role': row.role,
            'status': row.status, 'note': row.note,
            'checked_at': row.checked_at.isoformat() if row.checked_at else None,
            # Что вписать у регистратора
            'record': {'type': 'CNAME', 'host': label, 'value': target},
            'record_a': {'type': 'A', 'host': label, 'value': _ip_of(target)},
        })

    for item in ours + own:
        item['role_title'] = ROLE_TITLES.get(item['role'], item['role'])
        item['status_title'] = STATUS_TITLES.get(item['status'], item['status'])
    return ours, own


def _out(db, account):
    brand = branding.brand_of(db, account)
    ours, own = _rows(db, account)
    return {
        'name': account.brand_name or '',
        'shown_name': brand['name'],
        'color': brand['color'],
        'has_logo': brand['has_logo'],
        'logo_version': brand['logo_version'],
        'ours': ours,
        'own': own,
    }


@router.get('/brand', summary='Оформление и адреса организации')
def get_brand(staff: StaffUser = Depends(require(PERM_STAFF)),
              db: Session = Depends(get_db)):
    return _out(db, _account(db, staff))


class BrandIn(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None


@router.put('/brand', summary='Название и цвет')
def put_brand(payload: BrandIn, staff: StaffUser = Depends(require(PERM_STAFF)),
              db: Session = Depends(get_db)):
    account = _account(db, staff)
    try:
        branding.set_brand(db, account, name=payload.name, color=payload.color)
    except branding.BrandError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _out(db, account)


@router.post('/brand/logo', summary='Загрузить логотип')
async def post_logo(file: UploadFile = File(...),
                    staff: StaffUser = Depends(require(PERM_STAFF)),
                    db: Session = Depends(get_db)):
    from fastapi.concurrency import run_in_threadpool

    data = await file.read(branding.LOGO_MAX_BYTES + 1)
    account = _account(db, staff)
    try:
        await run_in_threadpool(branding.set_logo, db, account, data)
    except branding.BrandError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _out(db, account)


@router.delete('/brand/logo', summary='Убрать логотип')
def delete_logo(staff: StaffUser = Depends(require(PERM_STAFF)),
                db: Session = Depends(get_db)):
    account = _account(db, staff)
    branding.clear_logo(db, account)
    return _out(db, account)


@router.get('/brand/logo', include_in_schema=False)
def get_logo(staff: StaffUser = Depends(require(PERM_STAFF)),
             db: Session = Depends(get_db)):
    """Для предпросмотра в дашборде: страница записи на его адресе закрыта."""
    found = branding.logo_of(db, _account(db, staff))
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Логотипа нет')
    data, kind = found
    return Response(content=data, media_type=kind, headers={'Cache-Control': 'no-cache'})


class DomainIn(BaseModel):
    name: str
    role: str = ROLE_LK


@router.post('/domains', summary='Подключить свой домен')
def post_domain(payload: DomainIn, staff: StaffUser = Depends(require(PERM_STAFF)),
                db: Session = Depends(get_db)):
    account = _account(db, staff)
    try:
        tenancy.add_domain(db, account, payload.name, role=payload.role)
    except tenancy.DomainError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    db.refresh(account)
    return _out(db, account)


@router.delete('/domains/{domain_id}', summary='Отключить свой домен')
def delete_domain(domain_id: int, staff: StaffUser = Depends(require(PERM_STAFF)),
                  db: Session = Depends(get_db)):
    account = _account(db, staff)
    try:
        tenancy.remove_domain(db, account, domain_id)
    except tenancy.DomainError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    db.refresh(account)
    return _out(db, account)
