"""
Живая очередь.

Самая хрупкая часть приложения: она честна ровно настолько, насколько
аккуратно мастера отмечают начало и конец работ. Поэтому сервер отдаёт
не только цифры, но и время, когда цех выходил на связь, — а приложение
показывает «данные устарели» вместо цифр, которым нельзя верить.

Врать клиенту про очередь опаснее, чем не показать её вовсе: человек
приедет к назначенному времени и будет ждать час.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, QueueSnapshot
from app.schemas import QueueOut
from app.security import current_client
from app.services import shop_settings
from app.utils import now as shop_now

router = APIRouter(prefix='/queue', tags=['Очередь'])


@router.get('', response_model=QueueOut, summary='Что сейчас в шиномонтаже')
def current_queue(client: Client = Depends(current_client),
                  db: Session = Depends(get_db)):
    snapshot = db.query(QueueSnapshot).order_by(
        QueueSnapshot.taken_at.desc()).first()

    if snapshot is None:
        return QueueOut(
            shift_is_open=False, cars_in_work=0, cars_waiting=0,
            open_posts=0, taken_at=None, is_stale=True,
            note='Данных пока нет. Позвоните в шиномонтаж, чтобы узнать '
                 'загрузку')

    stale_after = shop_settings.get_int(db, 'queue_stale_minutes')
    age = shop_now() - snapshot.taken_at
    is_stale = age > timedelta(minutes=stale_after)

    if is_stale:
        note = ('Связь с шиномонтажом потеряна, данные устарели. '
                'Лучше позвонить')
    elif not snapshot.shift_is_open:
        note = 'Смена закрыта'
    elif snapshot.free_in_minutes is not None and snapshot.free_in_minutes <= 5:
        note = 'Свободный пост есть, можно подъезжать'
    elif snapshot.free_in_minutes is not None:
        note = f'Ближайший пост освободится примерно через {snapshot.free_in_minutes} мин'
    else:
        note = 'Все посты заняты'

    return QueueOut(
        shift_is_open=snapshot.shift_is_open,
        cars_in_work=snapshot.cars_in_work,
        cars_waiting=snapshot.cars_waiting,
        open_posts=snapshot.open_posts,
        free_in_minutes=None if is_stale else snapshot.free_in_minutes,
        taken_at=snapshot.taken_at,
        is_stale=is_stale,
        note=note)
