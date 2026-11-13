"""
Работы у партнёров: дашборд (главный) и кабинет на телефоне (кто
согласует), решения владельца 13.11.2026. Логика — app/services/partners.

Одни и те же действия с двух сторон: переписка, заявка партнёру, цена
партнёра, цена клиенту на согласование, «готово», отказ. Оплатить
партнёру — из дашборда (касса цеха проведёт РКО при обмене).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.photos import WEB_DIR, _device
from app.database import get_db
from app.models import PartnerMessage, StaffUser, PERM_CALENDAR
from app.security import require
from app.services import master, partners, tenancy
from app.services.partners import PartnerError

router = APIRouter(prefix='/dashboard/partners', tags=['Дашборд: работы у партнёров'])
cabinet_router = APIRouter(prefix='/m/partners', tags=['Кабинет: работы у партнёров'])
quote_router = APIRouter(tags=['Цена работы клиенту'])


class PriceIn(BaseModel):
    price: Optional[str] = None


class StatusIn(BaseModel):
    # finish / refuse / client_yes / client_no
    action: str


class MessageIn(BaseModel):
    text: str = ''


class PayIn(BaseModel):
    uids: List[str]
    method: str
    note: Optional[str] = None


class AnswerIn(BaseModel):
    answer: str


def _bad(e):
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


def _base_url(request: Request):
    host = request.headers.get('x-forwarded-host') or request.headers.get('host') or ''
    return f'https://{host.split(",")[0].strip()}'


# --- общие действия -------------------------------------------------------

def _act(db, task, who, action):
    if action == 'finish':
        return partners.finish(db, task, who)
    if action == 'refuse':
        return partners.refuse(db, task, who)
    if action in ('client_yes', 'client_no'):
        return partners.client_answer(db, task, action == 'client_yes', who)
    raise PartnerError('Неизвестное действие')


async def _message(db, task, who, request):
    """Текст — JSON; фото — форма (photo + text)."""
    kind = request.headers.get('content-type') or ''
    if kind.startswith('multipart/'):
        form = await request.form()
        upload = form.get('photo')
        text = str(form.get('text') or '')
        photo = None
        if upload is not None and hasattr(upload, 'read'):
            data = await upload.read()
            if data:
                photo = partners.save_photo(task, data, getattr(upload, 'content_type', None))
        return partners.staff_message(db, task, who, text, photo)
    body = await request.json()
    return partners.staff_message(db, task, who, (body or {}).get('text') or '')


def _photo(db, task, message_id):
    row = db.query(PartnerMessage).filter(PartnerMessage.id == message_id,
                                          PartnerMessage.shop_id == task.shop_id,
                                          PartnerMessage.task_uid == task.uid).first()
    path = partners.photo_path(row) if row is not None else None
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Фото нет')
    return FileResponse(path)


# --- дашборд -----------------------------------------------------------

def _ids(db, staff, shop):
    shops = tenancy.shops_of(db, staff.account_id)
    if shop:
        chosen = [row.id for row in shops if str(row.id) == str(shop) or row.slug == str(shop)]
        if not chosen:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Такой точки нет')
        return chosen
    return [row.id for row in shops]


def _task(db, staff, uid):
    task = partners.job(db, _ids(db, staff, None), uid)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Работа не найдена')
    return task


def _who(staff):
    return staff.name or 'Владелец'


@router.get('', summary='Работы у партнёров и оплата партнёрам')
def list_jobs(shop: Optional[str] = Query(None), staff: StaffUser = Depends(require(PERM_CALENDAR)),
              db: Session = Depends(get_db)):
    ids = _ids(db, staff, shop)
    return {'summary': partners.summary(db, ids),
            'jobs': [partners.job_dict(db, t) for t in partners.jobs(db, ids)]}


@router.get('/{uid}', summary='Работа и переписка')
def get_job(uid: str, staff: StaffUser = Depends(require(PERM_CALENDAR)), db: Session = Depends(get_db)):
    task = _task(db, staff, uid)
    result = partners.job_dict(db, task, messages=True)
    result['invite'] = partners.invite_link(db, task)
    return result


@router.post('/{uid}/price', summary='Цена партнёра руками')
def post_price(uid: str, payload: PriceIn, staff: StaffUser = Depends(require(PERM_CALENDAR)),
               db: Session = Depends(get_db)):
    task = _task(db, staff, uid)
    try:
        partners.set_partner_price(db, task, payload.price, _who(staff))
    except PartnerError as e:
        raise _bad(e)
    return get_job(uid, staff, db)


@router.post('/{uid}/status', summary='Готово, отказ, ответ клиента')
def post_status(uid: str, payload: StatusIn, staff: StaffUser = Depends(require(PERM_CALENDAR)),
                db: Session = Depends(get_db)):
    task = _task(db, staff, uid)
    try:
        _act(db, task, _who(staff), payload.action)
    except PartnerError as e:
        raise _bad(e)
    return get_job(uid, staff, db)


@router.post('/{uid}/send', summary='Отправить заявку партнёру')
def post_send(uid: str, staff: StaffUser = Depends(require(PERM_CALENDAR)), db: Session = Depends(get_db)):
    task = _task(db, staff, uid)
    try:
        partners.send_job(db, task, _who(staff))
    except PartnerError as e:
        raise _bad(e)
    return get_job(uid, staff, db)


@router.post('/{uid}/quote', summary='Цену — клиенту на согласование')
def post_quote(uid: str, request: Request, staff: StaffUser = Depends(require(PERM_CALENDAR)),
               db: Session = Depends(get_db)):
    task = _task(db, staff, uid)
    try:
        quote = partners.make_quote(db, task, _who(staff))
    except PartnerError as e:
        raise _bad(e)
    result = get_job(uid, staff, db)
    result['quote_sent'] = partners.send_quote(db, task, quote, _base_url(request))
    return result


@router.post('/{uid}/message', summary='Написать в переписку (текст или фото)')
async def post_message(uid: str, request: Request, staff: StaffUser = Depends(require(PERM_CALENDAR)),
                       db: Session = Depends(get_db)):
    task = _task(db, staff, uid)
    try:
        await _message(db, task, _who(staff), request)
    except PartnerError as e:
        raise _bad(e)
    return get_job(uid, staff, db)


@router.get('/{uid}/photo/{message_id}', summary='Фото из переписки')
def get_photo(uid: str, message_id: int, staff: StaffUser = Depends(require(PERM_CALENDAR)),
              db: Session = Depends(get_db)):
    return _photo(db, _task(db, staff, uid), message_id)


@router.post('/pay', summary='Оплатили партнёру')
def post_pay(payload: PayIn, staff: StaffUser = Depends(require(PERM_CALENDAR)),
             db: Session = Depends(get_db)):
    tasks = [_task(db, staff, uid) for uid in payload.uids]
    if not tasks:
        raise _bad('Отметьте, что оплачиваем')
    try:
        partners.pay(db, tasks, payload.method, payload.note, _who(staff))
    except PartnerError as e:
        raise _bad(e)
    return list_jobs(None, staff, db)


# --- кабинет на телефоне ---------------------------------------------

def _person(request, db):
    device = _device(request, db)
    person = master.employee_of(db, device)
    if person is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail='Войдите под своим именем')
    if not person.can_partners:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Согласовывать с партнёрами вам не разрешено')
    return person


def _cab_task(db, person, uid):
    task = partners.job(db, [person.shop_id], uid)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Работа не найдена')
    return task


def _cab_job(db, task):
    result = partners.job_dict(db, task, messages=True)
    result['invite'] = partners.invite_link(db, task)
    return result


@cabinet_router.get('', summary='Мои работы у партнёров')
def cab_list(request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    return {'jobs': [partners.job_dict(db, t) for t in partners.jobs(db, [person.shop_id], open_only=True)]}


@cabinet_router.get('/{uid}', summary='Работа и переписка')
def cab_job(uid: str, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    return _cab_job(db, _cab_task(db, person, uid))


@cabinet_router.post('/{uid}/price', summary='Цена партнёра')
def cab_price(uid: str, payload: PriceIn, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    task = _cab_task(db, person, uid)
    try:
        partners.set_partner_price(db, task, payload.price, person.title)
    except PartnerError as e:
        raise _bad(e)
    return _cab_job(db, task)


@cabinet_router.post('/{uid}/status', summary='Готово, отказ, ответ клиента')
def cab_status(uid: str, payload: StatusIn, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    task = _cab_task(db, person, uid)
    try:
        _act(db, task, person.title, payload.action)
    except PartnerError as e:
        raise _bad(e)
    return _cab_job(db, task)


@cabinet_router.post('/{uid}/send', summary='Отправить заявку партнёру')
def cab_send(uid: str, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    task = _cab_task(db, person, uid)
    try:
        partners.send_job(db, task, person.title)
    except PartnerError as e:
        raise _bad(e)
    return _cab_job(db, task)


@cabinet_router.post('/{uid}/quote', summary='Цену — клиенту на согласование')
def cab_quote(uid: str, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    task = _cab_task(db, person, uid)
    try:
        quote = partners.make_quote(db, task, person.title)
    except PartnerError as e:
        raise _bad(e)
    result = _cab_job(db, task)
    result['quote_sent'] = partners.send_quote(db, task, quote, _base_url(request))
    return result


@cabinet_router.post('/{uid}/message', summary='Написать в переписку')
async def cab_message(uid: str, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    task = _cab_task(db, person, uid)
    try:
        await _message(db, task, person.title, request)
    except PartnerError as e:
        raise _bad(e)
    return _cab_job(db, task)


@cabinet_router.get('/{uid}/photo/{message_id}', summary='Фото из переписки')
def cab_photo(uid: str, message_id: int, request: Request, db: Session = Depends(get_db)):
    person = _person(request, db)
    return _photo(db, _cab_task(db, person, uid), message_id)


# --- страница клиента: цена работы ------------------------------------

@quote_router.get('/pq/{token}', response_class=HTMLResponse, include_in_schema=False)
def quote_page(token: str):
    import os
    with open(os.path.join(WEB_DIR, 'quote.html'), encoding='utf-8') as page:
        return page.read()


@quote_router.get('/public/quote/{token}', include_in_schema=False)
def quote_data(token: str, db: Session = Depends(get_db)):
    from app.models import Shop, Task
    quote = partners.quote_of(db, token)
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Ссылка устарела')
    task = db.query(Task).filter(Task.shop_id == quote.shop_id, Task.uid == quote.task_uid).first()
    shop = db.get(Shop, quote.shop_id)
    return {'title': task.title if task else '', 'note': task.note if task else '',
            'price': quote.price, 'state': quote.state, 'shop': shop.name if shop else ''}


@quote_router.post('/public/quote/{token}', include_in_schema=False)
def quote_answer(token: str, payload: AnswerIn, db: Session = Depends(get_db)):
    quote = partners.quote_of(db, token)
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Ссылка устарела')
    try:
        partners.answer_quote(db, quote, payload.answer)
    except PartnerError as e:
        raise _bad(e)
    return quote_data(token, db)
