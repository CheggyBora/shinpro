"""
Рабочий день — это смена (решение владельца 27.10.2026).

Смена открыта — идёт подсчёт, и всё, что пробили до её закрытия, — её,
даже если это было в два часа ночи. Поэтому в «Отчётах» и зарплате день
значит «смены, открытые в этот день»: наряд — в смене, где его оплатили
(при оплате наряд привязывается к открытой смене, SalaryService).

Наряды без смены (старые записи) считаются по дню оплаты, как раньше.
"""
from datetime import datetime

from sqlalchemy import and_, or_

from utils import as_naive, get_moscow_time


def _day(value):
    return value.date() if isinstance(value, datetime) else value


def shift_ids(db, date_from, date_to):
    """Смены, открытые в эти дни. Сравниваем в Python: время смены хранится с поясом."""
    from models import Shift

    first, last = _day(date_from), _day(date_to)
    result = []
    for shift_id, started in db.query(Shift.id, Shift.start_time).all():
        started = as_naive(started)
        if started is not None and first <= started.date() <= last:
            result.append(shift_id)
    return result


def orders_filter(db, date_from, date_to):
    """Условие на WorkOrder: оплачен в сменах этих дней (без смены — в эти дни)."""
    from models import WorkOrder

    start = datetime.combine(_day(date_from), datetime.min.time())
    end = datetime.combine(_day(date_to), datetime.max.time())
    return or_(WorkOrder.shift_id.in_(shift_ids(db, date_from, date_to)),
               and_(WorkOrder.shift_id.is_(None),
                    WorkOrder.paid_at >= start, WorkOrder.paid_at <= end))


def work_day(db):
    """Какой сейчас рабочий день: открытая смена — день её открытия."""
    from models import Shift

    shift = db.query(Shift).filter(Shift.status == 'open').order_by(Shift.id.desc()).first()
    started = as_naive(shift.start_time) if shift is not None else None
    return started.date() if started is not None else get_moscow_time().date()


def moment_day(db, at, shifts=None):
    """
    Рабочий день момента: шла смена — день её открытия, не шла —
    календарный. Для того, у чего своей смены нет: выдача зарплаты.
    shifts — заранее загруженные [(начало, конец)], чтобы не ходить в базу
    на каждую строку.
    """
    at = as_naive(at)
    if at is None:
        return None
    if shifts is None:
        shifts = shift_windows(db)
    for started, ended in shifts:
        if started <= at <= ended:
            return started.date()
    return at.date()


def shift_windows(db):
    from models import Shift

    now = as_naive(get_moscow_time())
    result = []
    for started, ended in db.query(Shift.start_time, Shift.end_time).all():
        started = as_naive(started)
        if started is not None:
            result.append((started, as_naive(ended) or now))
    return result
