"""
Склад: снимок из цеха и раздел дашборда «Склад» (docs/stock.md).

Цех присылает остатки целиком вместе с обменом живой очереди, когда
они поменялись. Дашборд только показывает: чего мало, что в минусе.
Править склад с телефона нельзя — его ведут в цеху.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Shop, StaffUser, PERM_REVENUE
from app.security import current_staff, require_sync_key
from app.services import shop_settings, stock as stock_service, tenancy

sync_router = APIRouter(prefix='/sync', tags=['Обмен с цехом'])
router = APIRouter(prefix='/dashboard', tags=['Дашборд: склад'])


class StockSnapshotIn(BaseModel):
    # None — цех не сказал: выключатель не трогаем
    enabled: Optional[bool] = None
    items: List[dict] = []


@sync_router.post('/stock', summary='Склад: снимок остатков из цеха')
def snapshot(payload: StockSnapshotIn,
             shop: Shop = Depends(require_sync_key),
             db: Session = Depends(get_db)):
    """
    Полный снимок: позиции обновляются по uid, новые добавляются, чего
    в снимке нет — удаляется. count — сколько позиций теперь лежит.
    """
    try:
        count, rejected = stock_service.replace_snapshot(
            db, shop, payload.model_dump())
    except stock_service.StockError as e:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    answer = {'ok': True, 'count': count}
    if rejected:
        answer['rejected'] = rejected
    return answer


def _shops(db, staff, shop):
    """
    Точки, склад которых показываем. Пусто — все точки аккаунта.

    Чужую точку подставить нельзя: список берётся из аккаунта, к
    которому относится сам сотрудник.
    """
    shops = tenancy.shops_of(db, staff.account_id)
    if shop:
        chosen = [row for row in shops
                  if str(row.id) == str(shop) or row.slug == str(shop)]
        if not chosen:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail='Такой точки нет')
        return chosen
    return shops


@router.get('/stock', summary='Остатки склада')
def list_stock(shop: Optional[str] = Query(
                   None, description='Точка. Пусто — все точки сети'),
               direction: Optional[str] = Query(
                   None, description='Направление: all (по умолчанию), '
                                     'tire или wash'),
               staff: StaffUser = Depends(current_staff),
               db: Session = Depends(get_db)):
    """
    Позиции склада: сначала минус, потом мало, потом по названию.

    Показываем только точки, у которых склад включён: у выключенной
    остатков нет, даже если когда-то приезжал снимок. updated_at — когда
    приехал снимок; по нескольким точкам — самый старый из них: «всё
    свежее» нельзя говорить, пока одна точка молчит.

    Закупочную цену видит только тот, кому открыта выручка.
    """
    chosen = _shops(db, staff, shop)
    enabled = [row for row in chosen if shop_settings.stock_on(db, row)]
    names = {row.id: shop_settings.title(db, row) for row in enabled}

    stamps = [stock_service.snapshot_at(db, row) for row in enabled]
    stamps = [moment for moment in stamps if moment is not None]

    with_purchase = staff.can(PERM_REVENUE)
    wanted = stock_service.parse_direction_filter(direction)
    items = []
    for row in stock_service.items_for(db, list(names), direction=wanted):
        item = stock_service.to_dict(row, with_purchase=with_purchase)
        item['shop_id'] = row.shop_id
        item['shop_name'] = names.get(row.shop_id)
        items.append(item)

    return {
        'enabled': bool(enabled),
        'updated_at': (min(stamps).isoformat(timespec='seconds')
                       if stamps else None),
        'direction': wanted or stock_service.ALL,
        'wash_enabled': any(shop_settings.wash_on(db, row) for row in enabled),
        'items': items,
    }
