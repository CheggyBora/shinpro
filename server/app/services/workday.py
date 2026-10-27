"""
Рабочий день — это смена (решение владельца 27.10.2026).

Шиномонтаж считает деньги сменами: смена открыта — идёт подсчёт, и всё,
что пробили до её закрытия, — её, даже если это было в два часа ночи.
Поэтому везде, где человек выбирает дни (дашборд, касса, кабинет
мастера), день значит «смены, открытые в этот день»:

    наряд    — в смене, где его оплатили (Visit.shift_local_id);
    возврат  — в смене, во время которой его провели;
    ордер    — в смене, где его пробили (CashOrder.shift_local_id).

Записи без смены (старые, до того как цех стал их присылать) считаются
по календарному дню, как раньше: иначе они пропали бы из отчётов вовсе.
"""
from datetime import datetime, time, timedelta

from sqlalchemy import and_, or_

from app.models import ShopShift
from app.utils import now as shop_now

# Смена не бывает длиннее: забытую программа закрывает сама на
# следующее утро. С запасом — чтобы найти смену, в которой был возврат
LONGEST_SHIFT = timedelta(days=3)


def calendar_bounds(day_from, day_to):
    return datetime.combine(day_from, time.min), datetime.combine(day_to, time.max)


def work_day(db, shop_ids=None):
    """
    Какой сейчас рабочий день: открытая смена — день её открытия (в час
    ночи это ещё вчерашний день), нет открытой — сегодня.
    """
    query = db.query(ShopShift).filter(ShopShift.ended_at.is_(None),
                                       ShopShift.status == 'open')
    if shop_ids is not None:
        query = query.filter(ShopShift.shop_id.in_(list(shop_ids)))
    row = query.order_by(ShopShift.started_at.desc()).first()
    if row is not None and row.started_at is not None:
        return row.started_at.date()
    return shop_now().date()


class Period:
    """Дни, выбранные человеком, — как набор смен."""

    def __init__(self, db, day_from, day_to, shop_ids=None):
        self.db = db
        self.day_from, self.day_to = day_from, day_to
        self.start, self.end = calendar_bounds(day_from, day_to)
        self.shop_ids = list(shop_ids) if shop_ids is not None else None

        query = db.query(ShopShift).filter(ShopShift.started_at >= self.start,
                                           ShopShift.started_at <= self.end)
        if self.shop_ids is not None:
            query = query.filter(ShopShift.shop_id.in_(self.shop_ids))

        self.by_shop = {}
        self.day_of = {}
        for row in query.all():
            self.by_shop.setdefault(row.shop_id, set()).add(row.local_id)
            self.day_of[(row.shop_id, row.local_id)] = row.started_at.date()
        self._windows = None

    def where(self, shop_col, shift_col, time_col):
        """Условие для запроса: запись из смен периода или, без смены, — из его дней."""
        conds = [and_(shop_col == shop_id, shift_col.in_(sorted(ids)))
                 for shop_id, ids in self.by_shop.items()]
        conds.append(and_(shift_col.is_(None), time_col >= self.start, time_col <= self.end))
        return or_(*conds)

    def day(self, shop_id, shift_local_id, at):
        """Рабочий день записи: день открытия её смены, без смены — календарный."""
        found = self.day_of.get((shop_id, shift_local_id))
        if found is not None:
            return found
        return at.date() if at is not None else None

    # --- Момент: в какой смене он был ---------------------------------

    @property
    def wide_start(self):
        return self.start - LONGEST_SHIFT

    @property
    def wide_end(self):
        return self.end + LONGEST_SHIFT

    def _load_windows(self):
        query = self.db.query(ShopShift).filter(
            ShopShift.started_at >= self.wide_start - LONGEST_SHIFT,
            ShopShift.started_at <= self.wide_end)
        if self.shop_ids is not None:
            query = query.filter(ShopShift.shop_id.in_(self.shop_ids))
        now = shop_now()
        windows = {}
        for row in query.all():
            windows.setdefault(row.shop_id, []).append(
                (row.started_at, row.ended_at or now, row.started_at.date()))
        self._windows = windows

    def moment_day(self, shop_id, at):
        """
        Рабочий день момента: шла смена — день её открытия, не шла —
        календарный. Нужен для возвратов: у них своей смены нет, есть время.
        """
        if at is None:
            return None
        if self._windows is None:
            self._load_windows()
        for started, ended, day in self._windows.get(shop_id, ()):
            if started <= at <= ended:
                return day
        return at.date()

    def has_moment(self, shop_id, at):
        day = self.moment_day(shop_id, at)
        return day is not None and self.day_from <= day <= self.day_to
