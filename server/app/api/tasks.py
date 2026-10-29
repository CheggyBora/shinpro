"""
Календарь задач: обмен с цехом и раздел дашборда (docs/calendar.md).

Задачу ставят и в цеху, и из дома — с телефона владельца. Обе стороны
правят одну и ту же строку, и побеждает более поздняя правка. Задача
из дашборда доезжает до цеха ближайшим обменом, раз в двадцать секунд.
"""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Shop, StaffUser
from app.security import current_staff, require_sync_key
from app.models.task import KIND_NOTE
from app.services import notify, shop_settings, tasks as task_service, tenancy
from app.utils import now as shop_now

# Фильтр по направлению в адресе: tire, wash или all. Календарь у
# шиномонтажа и мойки один, пусто — оба направления сразу
DIRECTION_HELP = 'Направление: all (по умолчанию — оба), tire или wash'

sync_router = APIRouter(prefix='/sync', tags=['Обмен с цехом'])
router = APIRouter(prefix='/dashboard', tags=['Дашборд: календарь'])

# Сколько дней можно спросить за раз. Календарь показывает неделю;
# больше двух месяцев сразу никому не нужно, а базу такой запрос грузит
MAX_RANGE_DAYS = 62


# ----------------------------------------------------------------------
# Обмен с цехом
# ----------------------------------------------------------------------

class TasksExchangeIn(BaseModel):
    # «now» из прошлого ответа. Пусто — первый обмен
    since: Optional[str] = None
    tasks: List[dict] = []
    counterparties: List[dict] = []


@sync_router.post('/tasks', summary='Календарь задач: обмен с цехом')
def exchange(payload: TasksExchangeIn,
             shop: Shop = Depends(require_sync_key),
             db: Session = Depends(get_db)):
    """
    Цех отдаёт изменённое у себя и забирает изменённое здесь.

    Ответ — строки с updated_at позже since, в том числе только что
    принятые: цех перезапишет их тем же самым, и это безопасно. «now»
    из ответа цех присылает следующим since.
    """
    return task_service.exchange(db, shop, payload.model_dump())


# ----------------------------------------------------------------------
# Дашборд
# ----------------------------------------------------------------------

def _shop_ids(db, staff, shop):
    """
    Точки, задачи которых показываем. Пусто — все точки аккаунта.

    Чужую точку подставить нельзя: список берётся из аккаунта, к
    которому относится сам сотрудник.
    """
    shops = tenancy.shops_of(db, staff.account_id)
    if shop:
        chosen = [row.id for row in shops
                  if str(row.id) == str(shop) or row.slug == str(shop)]
        if not chosen:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail='Такой точки нет')
        return chosen
    return [row.id for row in shops]


def _one_shop(db, staff, shop):
    """
    Точка, в которую ставим задачу. Одна и обязательно.

    Задача «привезти комплект» без точки — это задача никому: не
    угадываем, а просим выбрать.
    """
    shops = tenancy.shops_of(db, staff.account_id)
    if not shop:
        if len(shops) == 1:
            return shops[0]
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail='Выберите точку: задачи у каждой свои')

    for row in shops:
        if str(row.id) == str(shop) or row.slug == str(shop):
            return row
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Такой точки нет')


def _view(row, names):
    item = task_service.to_dict(row)
    item['shop_id'] = row.shop_id
    item['counterparty_name'] = names.get((row.shop_id, row.counterparty_uid))
    return item


def _names(db, shop_ids):
    return {(row.shop_id, row.uid): row.name
            for row in task_service.counterparties(db, shop_ids)}


@router.get('/tasks', summary='Задачи на дни календаря')
def list_tasks(day_from: Optional[date] = Query(None, alias='from'),
               day_to: Optional[date] = Query(None, alias='to'),
               shop: Optional[str] = Query(
                   None, description='Точка. Пусто — все точки сети'),
               direction: Optional[str] = Query(None,
                                                description=DIRECTION_HELP),
               staff: StaffUser = Depends(current_staff),
               db: Session = Depends(get_db)):
    """
    Задачи с from по to — обоих направлений или одного (direction).
    Если в эти дни попадает сегодня — ещё и неотмеченные прошлых дней
    отдельным списком: они висят красными, пока их не отметят.

    wash_enabled — работает ли мойкой хоть одна из показанных точек:
    только тогда дашборд показывает фильтр «Направление» и метки
    «ШИНОМОНТАЖ» / «МОЙКА» у задач.
    """
    direction = task_service.parse_direction_filter(direction)
    today = shop_now().date()
    day_from = day_from or today
    day_to = day_to or (day_from + timedelta(days=6))
    if day_from > day_to:
        day_from, day_to = day_to, day_from
    if (day_to - day_from).days > MAX_RANGE_DAYS:
        day_to = day_from + timedelta(days=MAX_RANGE_DAYS)

    ids = _shop_ids(db, staff, shop)
    overdue, rows = task_service.for_range(db, ids, day_from, day_to,
                                           today=today, direction=direction)
    names = _names(db, ids)
    return {
        'from': day_from.isoformat(),
        'to': day_to.isoformat(),
        'today': today.isoformat(),
        'direction': direction or task_service.ALL,
        'wash_enabled': any(shop_settings.wash_on(db, shop_id)
                            for shop_id in ids),
        'overdue': [_view(row, names) for row in overdue],
        'tasks': [_view(row, names) for row in rows],
        # Часы на сетке «Неделя» и «День» — часы работы точки
        'hours': _hours(db, ids),
    }


def _hours(db, shop_ids):
    """С какого по какой час рисовать сетку: самые ранние и поздние часы точек."""
    def hour(text, fallback):
        try:
            return int(str(text).split(':')[0])
        except (TypeError, ValueError):
            return fallback
    opens = [hour(shop_settings.get(db, 'booking_opens_at', shop=i), 9) for i in shop_ids]
    closes = [hour(shop_settings.get(db, 'booking_closes_at', shop=i), 21) for i in shop_ids]
    start, end = (min(opens) if opens else 9), (max(closes) if closes else 21)
    if end <= start:
        start, end = 9, 21
    return {'from': start, 'to': end}


@router.post('/tasks', summary='Поставить задачу')
def create_task(payload: dict,
                shop: Optional[str] = Query(None),
                staff: StaffUser = Depends(current_staff),
                db: Session = Depends(get_db)):
    # Точку можно прислать и в теле: форма знает, куда ставит
    chosen = _one_shop(db, staff, payload.get('shop') or shop)
    try:
        row = task_service.create(db, chosen, payload, author=staff.title)
    except task_service.TaskError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    names = _names(db, [chosen.id])
    _announce(row, names)
    return _view(row, names)


def _announce(row, names):
    """Новая задача — в Telegram, не задерживая ответ. Комментарий — никуда."""
    if row.kind == KIND_NOTE:
        return
    text = task_service.telegram_text(row, names.get((row.shop_id, row.counterparty_uid)))
    notify.send_in_background(text, shop=row.shop_id, kind=notify.KIND_TASK)
    # Контрагент с ником — ему лично (решение владельца 29.10.2026)
    party = task_service.counterparty_of(row)
    if party is not None and party.telegram and not party.deleted:
        notify.send_personal_in_background(text, row.shop_id, party.telegram,
                                           kind=notify.KIND_TASK)


@router.patch('/tasks/{uid}', summary='Поправить, перенести, отметить')
def patch_task(uid: str, payload: dict,
               shop: Optional[str] = Query(None),
               staff: StaffUser = Depends(current_staff),
               db: Session = Depends(get_db)):
    """
    Любое поле задачи; done — отметка «сделано» (true) или снятие её
    (false); deleted — удалить. Время правки двигается, и цех заберёт
    задачу при ближайшем обмене.
    """
    ids = _shop_ids(db, staff, shop)
    row = task_service.find(db, ids, uid)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail='Задача не найдена')
    was_note = row.kind == KIND_NOTE
    try:
        row = task_service.patch(db, row, payload, author=staff.title)
    except task_service.TaskError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    names = _names(db, [row.shop_id])
    # Комментарий сделали задачей — теперь это дело, о нём надо сказать
    if was_note and row.kind != KIND_NOTE and not row.deleted:
        _announce(row, names)
    return _view(row, names)


@router.get('/counterparties', summary='Контрагенты — для выбора в задаче')
def list_counterparties(shop: Optional[str] = Query(None),
                        direction: Optional[str] = Query(
                            None, description=DIRECTION_HELP),
                        staff: StaffUser = Depends(current_staff),
                        db: Session = Depends(get_db)):
    # У мойки свои поставщики: в задаче мойки выбирать склад шин незачем.
    # Форма просит список направления задачи; пусто или all — все
    ids = _shop_ids(db, staff, shop)
    direction = task_service.parse_direction_filter(direction)
    result = []
    for row in task_service.counterparties(db, ids, direction=direction):
        item = task_service.counterparty_dict(row)
        item['shop_id'] = row.shop_id
        result.append(item)
    return result
