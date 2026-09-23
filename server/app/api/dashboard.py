"""
Данные дашборда: выручка, услуги, мастера, наряды, смены.

Кто что видит, решают права, а не экран. Мастер, открывший чужой
наряд по номеру, получит отказ, а не чужие деньги: прятать кнопку
в интерфейсе — не защита.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (StaffUser, PERM_REVENUE, PERM_ORDERS, PERM_SALARY_ALL,
                        PERM_SALARY_OWN, QueueSnapshot)
from app.security import current_staff, require
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix='/dashboard', tags=['Дашборд: цифры'])


def _period(day_from: Optional[date], day_to: Optional[date]):
    """
    Период. По умолчанию — последние 30 дней, как в программе цеха.

    Перевёрнутые даты не ругаем, а меняем местами: человек ошибся в
    двух полях, а не совершил преступление.
    """
    today = date.today()
    day_to = day_to or today
    day_from = day_from or (day_to - timedelta(days=29))

    if day_from > day_to:
        day_from, day_to = day_to, day_from

    return day_from, day_to


def _own_master_id(staff: StaffUser):
    """
    Номер сотрудника для того, кто видит только своё.

    Без номера мастеру показывать нечего: связать его с нарядами не по
    чему. Об этом честно говорим, а не отдаём пустой экран.
    """
    if staff.can(PERM_SALARY_ALL) or staff.can(PERM_ORDERS):
        return None

    if not staff.employee_shop_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail='К вашей учётной записи не привязан номер сотрудника. '
                   'Попросите владельца указать его')

    return staff.employee_shop_id


@router.get('/summary', summary='Сводка за период')
def summary(day_from: Optional[date] = Query(None, alias='from'),
            day_to: Optional[date] = Query(None, alias='to'),
            staff: StaffUser = Depends(require(PERM_REVENUE)),
            db: Session = Depends(get_db)):
    day_from, day_to = _period(day_from, day_to)
    return DashboardService(db).summary(day_from, day_to)


@router.get('/services', summary='Выручка по услугам')
def services(day_from: Optional[date] = Query(None, alias='from'),
             day_to: Optional[date] = Query(None, alias='to'),
             staff: StaffUser = Depends(require(PERM_REVENUE)),
             db: Session = Depends(get_db)):
    day_from, day_to = _period(day_from, day_to)
    return DashboardService(db).services(day_from, day_to)


@router.get('/masters', summary='Мастера и начисления')
def masters(day_from: Optional[date] = Query(None, alias='from'),
            day_to: Optional[date] = Query(None, alias='to'),
            staff: StaffUser = Depends(require(PERM_SALARY_ALL)),
            db: Session = Depends(get_db)):
    day_from, day_to = _period(day_from, day_to)
    return DashboardService(db).masters(day_from, day_to)


@router.get('/orders', summary='Наряды за период')
def orders(day_from: Optional[date] = Query(None, alias='from'),
           day_to: Optional[date] = Query(None, alias='to'),
           employee_shop_id: Optional[int] = None,
           payment_method: Optional[str] = None,
           limit: int = Query(500, le=2000),
           staff: StaffUser = Depends(current_staff),
           db: Session = Depends(get_db)):
    """
    Наряды. Мастеру — только его собственные.

    Он может спросить и чужого мастера — ответим его же нарядами:
    подменить номер в запросе проще всего, и проверять надо здесь.
    """
    if not staff.can(PERM_ORDERS) and not staff.can(PERM_SALARY_OWN):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к этому разделу')

    own = _own_master_id(staff)
    if own is not None:
        employee_shop_id = own

    day_from, day_to = _period(day_from, day_to)
    return DashboardService(db).orders(day_from, day_to, employee_shop_id,
                                       payment_method, limit)


@router.get('/orders/{shop_id}', summary='Наряд целиком')
def order_card(shop_id: int, staff: StaffUser = Depends(current_staff),
               db: Session = Depends(get_db)):
    if not staff.can(PERM_ORDERS) and not staff.can(PERM_SALARY_OWN):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к этому разделу')

    card = DashboardService(db).order_card(shop_id, _own_master_id(staff))
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Наряд не найден')

    return card


@router.get('/shifts', summary='Смены за период')
def shifts(day_from: Optional[date] = Query(None, alias='from'),
           day_to: Optional[date] = Query(None, alias='to'),
           staff: StaffUser = Depends(current_staff),
           db: Session = Depends(get_db)):
    if not staff.can(PERM_SALARY_ALL) and not staff.can(PERM_SALARY_OWN):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к этому разделу')

    day_from, day_to = _period(day_from, day_to)
    return DashboardService(db).shifts(day_from, day_to)


@router.get('/shifts/current', summary='Текущая смена')
def current_shift(staff: StaffUser = Depends(current_staff),
                  db: Session = Depends(get_db)):
    """
    Открытая сейчас смена и загрузка цеха.

    Слепок очереди приходит из цеха раз в десять минут. Отдаём вместе с
    его временем: если цех давно не выходил на связь, дашборд покажет
    «данные от 10:42», а не соврёт свежими цифрами.
    """
    service = DashboardService(db)
    shift = service.current_shift()

    last = db.query(QueueSnapshot).order_by(
        QueueSnapshot.taken_at.desc()).first()

    return {
        'shift': {
            'shop_id': shift.shop_id,
            'started_at': shift.started_at,
            'open_posts': shift.open_posts,
        } if shift else None,
        'queue': {
            'taken_at': last.taken_at,
            'cars_in_work': last.cars_in_work,
            'cars_waiting': last.cars_waiting,
            'open_posts': last.open_posts,
            'free_in_minutes': last.free_in_minutes,
            'shift_is_open': last.shift_is_open,
        } if last else None,
    }


@router.get('/shifts/{shift_shop_id}/salary', summary='Начисления за смену')
def shift_salary(shift_shop_id: int,
                 staff: StaffUser = Depends(current_staff),
                 db: Session = Depends(get_db)):
    """
    Кнопка «Начисления за смену».

    Владелец и управляющий с правом на зарплаты видят всех, мастер —
    только себя. Тот же расчёт, что и в программе цеха.
    """
    if staff.can(PERM_SALARY_ALL):
        only = None
    elif staff.can(PERM_SALARY_OWN):
        only = _own_master_id(staff)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail='Нет доступа к зарплатам')

    return DashboardService(db).shift_salary(shift_shop_id, only)
