"""
Раздел дашборда «Касса» (docs/cash.md).

Сколько сейчас в кассе, ордера за период с итогами по статьям и
пересчёты кассы по сменам. Ордера приезжают из цеха с обменом
(POST /sync/push, поле cash_orders); править их отсюда нельзя.

Смотрит тот, кому открыта выручка: касса — те же деньги.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dashboard import _period
from app.database import get_db
from app.models import StaffUser, PERM_CASH
from app.security import require
from app.services import cash as cash_service, shop_settings, tenancy
from app.services.dashboard_service import day_bounds

router = APIRouter(prefix='/dashboard', tags=['Дашборд: касса'])


def _shops(db, staff, shop):
    """Выбранная точка или все точки аккаунта. Чужую не подставить."""
    shops = tenancy.shops_of(db, staff.account_id)
    if shop:
        chosen = [row for row in shops
                  if str(row.id) == str(shop) or row.slug == str(shop)]
        if not chosen:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail='Такой точки нет')
        return chosen
    return shops


@router.get('/cash', summary='Касса: остаток, ордера, пересчёты')
def cash(day_from: Optional[date] = Query(None, alias='from'),
         day_to: Optional[date] = Query(None, alias='to'),
         shop: Optional[str] = Query(
             None, description='Точка. Пусто — все точки сети'),
         staff: StaffUser = Depends(require(PERM_CASH)),
         db: Session = Depends(get_db)):
    """
    now — остаток каждой точки: у открытой смены «должно быть», у
    закрытой — сколько пересчитали при закрытии; null — касса не
    велась (старая программа цеха).

    orders — ордера за период, новые сверху; отменённый и его отмена
    видны оба. totals — итоги по статьям наличными отдельно для
    расхода и прихода, отмены вычтены; безнал расхода — одной суммой.

    shifts — смены периода, где кассу считали.
    """
    day_from, day_to = _period(day_from, day_to)
    start, end = day_bounds(day_from, day_to)

    chosen = _shops(db, staff, shop)
    ids = [row.id for row in chosen]
    titles = {row.id: shop_settings.title(db, row) for row in chosen}

    # Дни — это смены (решение владельца 27.10.2026): ордер ночью после
    # полуночи — в той смене, которая шла, а не в завтрашнем дне
    from app.services.workday import Period
    orders = cash_service.orders_for(db, ids, start, end, titles,
                                     period=Period(db, day_from, day_to, ids))
    return {
        'from': day_from,
        'to': day_to,
        'now': cash_service.now_in_cash(db, chosen, titles),
        'orders': orders,
        'totals': cash_service.totals_for(orders),
        'shifts': cash_service.shifts_for(db, ids, start, end, titles),
    }
