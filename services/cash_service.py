"""
Касса: ордера, остаток наличных, пересчёт при закрытии (docs/cash.md).

Касса одна на объект, как и смена. Остаток не хранится, а считается:

    на начало смены + оплаты нарядов наличными − возвраты наличными
    + приходные наличными − расходные наличными.
"""
import json
import uuid

from sqlalchemy import func

from logger import log
from models import Shift, WorkOrder
from models.cash import (CashOrder, KIND_IN, KIND_OUT, KIND_TITLES, METHOD_CASH,
                         METHOD_NONCASH, DEFAULT_CATEGORIES, SALARY_CATEGORY,
                         REFUND_CATEGORY)
from utils import get_moscow_time, as_naive


class CashError(ValueError):
    """Понятная человеку причина, почему не вышло."""


def money(value):
    return f'{value:,.0f} ₽'.replace(',', ' ')


def parse_amount(value):
    try:
        amount = round(float(str(value).replace(' ', '').replace(',', '.')), 2)
    except (TypeError, ValueError):
        raise CashError('Сумма — числом, например 1500')
    if amount != amount or amount < 0:
        raise CashError('Сумма не может быть меньше нуля')
    return amount


class CashService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Статьи
    # ------------------------------------------------------------------

    @staticmethod
    def _key(kind):
        return f'cash_categories_{kind}'

    def categories(self, kind):
        from services.settings_service import SettingsService
        raw = SettingsService(self.db).get(self._key(kind))
        try:
            values = json.loads(raw) if raw else None
        except ValueError:
            values = None
        if not isinstance(values, list) or not values:
            return list(DEFAULT_CATEGORIES[kind])
        return [str(v) for v in values if str(v).strip()]

    def set_categories(self, kind, values):
        from services.settings_service import SettingsService
        clean = []
        for value in values:
            value = str(value).strip()[:60]
            if value and value not in clean:
                clean.append(value)
        if not clean:
            raise CashError('Нужна хотя бы одна статья')
        SettingsService(self.db).set(self._key(kind), json.dumps(clean, ensure_ascii=False))
        return clean

    # ------------------------------------------------------------------
    # Смена: начало, остаток, пересчёт
    # ------------------------------------------------------------------

    def current_shift(self):
        return self.db.query(Shift).filter(Shift.status == 'open').first()

    def suggested_start(self):
        """Что предложить при открытии: пересчитанное при прошлом закрытии."""
        last = self.db.query(Shift).filter(Shift.status == 'closed').order_by(Shift.id.desc()).first()
        if last is None:
            return None
        for value in (last.cash_counted, last.cash_expected):
            if value is not None:
                return value
        return None

    def set_start(self, shift, amount):
        shift.cash_start = parse_amount(amount)
        self.db.commit()
        self._nudge('касса: начало смены')
        return shift

    def _period(self, shift):
        return as_naive(shift.start_time), as_naive(shift.end_time) or get_moscow_time()

    def paid_orders(self, shift):
        return self.db.query(WorkOrder).filter(
            WorkOrder.shift_id == shift.id, WorkOrder.status == 'paid',
            WorkOrder.is_deleted.isnot(True)).all()

    def orders(self, shift=None):
        query = self.db.query(CashOrder)
        if shift is not None:
            query = query.filter(CashOrder.shift_id == shift.id)
        return query.order_by(CashOrder.created_at, CashOrder.id).all()

    def totals(self, shift):
        """{'start', 'paid_cash', 'came', 'went', 'expected'}. Возвраты — в ордерах."""
        start = shift.cash_start or 0.0
        paid_cash = sum(o.total_amount or 0 for o in self.paid_orders(shift) if o.payment_method == 'cash')
        came = went = 0.0
        for row in self.orders(shift):
            effect = row.cash_effect
            if effect > 0:
                came += effect
            else:
                went -= effect
        came_total = paid_cash + came
        went_total = went
        return {'start': round(start, 2), 'paid_cash': round(paid_cash, 2),
                'came': round(came_total, 2),
                'went': round(went_total, 2),
                'expected': round(start + came_total - went_total, 2)}

    def expected(self, shift):
        return self.totals(shift)['expected']

    def lines(self, shift):
        """
        Всё, что было в кассе за смену, по времени:
        [{'time', 'what', 'tag', 'text', 'amount', 'effect', 'order'}].
        effect — сколько изменилось наличных (0 — серая строка).
        """
        rows = []
        if shift.cash_start is not None:
            rows.append({'time': as_naive(shift.start_time), 'tag': 'start', 'what': 'Открытие',
                         'text': f'Пересчитали: {money(shift.cash_start)}',
                         'amount': shift.cash_start, 'effect': 0.0, 'order': None})
        for o in self.paid_orders(shift):
            cash = o.payment_method == 'cash'
            plate = o.car.license_plate if o.car else ''
            rows.append({'time': as_naive(o.paid_at), 'tag': 'paid' if cash else 'card',
                         'what': f'Наряд №{o.id}',
                         'text': f'{plate} · ' + ('оплата наличными' if cash else 'оплата картой — в кассу не идёт'),
                         'amount': o.total_amount or 0, 'effect': (o.total_amount or 0) if cash else 0.0,
                         'order': None})
        for row in self.orders(shift):
            title = f'{KIND_TITLES[row.kind]} №{row.number}'
            text = row.category + (f' · {row.note}' if row.note else '')
            if row.method == METHOD_NONCASH:
                text += ' · безнал'
            if row.reverses_id:
                original = self.db.query(CashOrder).get(row.reverses_id)
                text = f'отмена №{original.number if original else "?"} · ' + text
            rows.append({'time': as_naive(row.created_at), 'tag': row.kind if row.method == METHOD_CASH else 'noncash',
                         'what': title, 'text': text, 'amount': row.amount,
                         'effect': row.cash_effect, 'order': row})
        rows.sort(key=lambda r: r['time'] or get_moscow_time())
        return rows

    def count(self, shift, counted, reason=None):
        """Пересчёт при закрытии: должно быть против есть."""
        self.db.refresh(shift)
        if shift.status != 'open':
            # Забытую смену программа закрыла сама, пока было открыто окно
            raise CashError('Смена уже закрыта — пересчитайте кассу при открытии новой')
        counted = parse_amount(counted)
        expected = self.expected(shift)
        diff = round(counted - expected, 2)
        reason = (reason or '').strip()[:300] or None
        if diff and not reason:
            raise CashError('Касса не сошлась — напишите причину')
        shift.cash_expected = expected
        shift.cash_counted = counted
        shift.cash_diff = diff
        shift.cash_diff_reason = reason if diff else None
        self.db.commit()
        return diff

    def refresh_expected(self, shift=None):
        """Открытой смене — текущий остаток, для дашборда."""
        shift = shift or self.current_shift()
        if shift is not None and shift.status == 'open':
            value = self.expected(shift)
            if shift.cash_expected != value:
                shift.cash_expected = value
                self.db.commit()

    # ------------------------------------------------------------------
    # Ордера
    # ------------------------------------------------------------------

    def _next_number(self, kind):
        last = self.db.query(func.max(CashOrder.number)).filter(CashOrder.kind == kind).scalar()
        return (last or 0) + 1

    def create(self, kind, category, amount, method=METHOD_CASH, note=None,
               employee_id=None, payout_id=None, check_category=True, commit=True,
               work_order_id=None):
        if kind not in (KIND_IN, KIND_OUT):
            raise CashError('Приходный или расходный?')
        amount = parse_amount(amount)
        if amount <= 0:
            raise CashError('Сумма должна быть больше нуля')
        category = (category or '').strip()
        if not category:
            raise CashError('Выберите статью')
        if check_category and category not in self.categories(kind):
            raise CashError('Такой статьи нет в списке')
        if method not in (METHOD_CASH, METHOD_NONCASH):
            raise CashError('Наличные или безнал?')
        shift = self.current_shift()
        now = get_moscow_time()
        row = CashOrder(uid=str(uuid.uuid4()), kind=kind, number=self._next_number(kind),
                        category=category[:60], amount=amount, method=method,
                        note=(note or '').strip()[:300] or None, employee_id=employee_id,
                        shift_id=shift.id if shift else None, payout_id=payout_id,
                        work_order_id=work_order_id, created_at=now, changed_at=now)
        self.db.add(row)
        if not commit:
            # Вызывающий проводит ордер вместе со своей записью одним commit
            self.db.flush()
            return row
        self.db.commit()
        self._log(f'{KIND_TITLES[kind]} ордер №{row.number}: {category}, {money(amount)}'
                  + (' безнал' if method == METHOD_NONCASH else ''))
        self._nudge('кассовый ордер')
        return row

    def reverse(self, row, employee_id=None, commit=True):
        """Отменить ошибочный ордер: проводим обратный, оба остаются."""
        if row.reverses_id:
            raise CashError('Это уже отмена — отменять её нельзя')
        if self.db.query(CashOrder).filter(CashOrder.reverses_id == row.id).first():
            raise CashError(f'Ордер №{row.number} уже отменён')
        shift = self.current_shift()
        now = get_moscow_time()
        back = CashOrder(uid=str(uuid.uuid4()), kind=row.kind, number=self._next_number(row.kind),
                         category=row.category, amount=row.amount, method=row.method,
                         note=row.note, employee_id=employee_id, reverses_id=row.id,
                         shift_id=shift.id if shift else None, payout_id=row.payout_id,
                         work_order_id=row.work_order_id, created_at=now, changed_at=now)
        self.db.add(back)
        if not commit:
            self.db.flush()
            return back
        self.db.commit()
        self._log(f'Отменён {KIND_TITLES[row.kind].lower()} ордер №{row.number}: '
                  f'{row.category}, {money(row.amount)}')
        self._nudge('отмена кассового ордера')
        return back

    def is_reversed(self, row):
        return self.db.query(CashOrder).filter(CashOrder.reverses_id == row.id).first() is not None

    # ------------------------------------------------------------------
    # Зарплата
    # ------------------------------------------------------------------

    def from_payout(self, payout, commit=True):
        """Выдали зарплату — расходный ордер сам. На карту — безнал."""
        from models import Employee, METHOD_CASH as PAY_CASH
        employee = self.db.query(Employee).filter(Employee.id == payout.employee_id).first()
        who = employee.title if employee is not None else f'сотрудник №{payout.employee_id}'
        way = 'наличными' if payout.method == PAY_CASH else 'на карту'
        return self.create(KIND_OUT, SALARY_CATEGORY, payout.amount,
                           METHOD_CASH if payout.method == PAY_CASH else METHOD_NONCASH,
                           note=f'{who} · {way}' + (' · аванс' if payout.is_advance else ''),
                           employee_id=payout.employee_id, payout_id=payout.id,
                           check_category=False, commit=commit)

    def payout_cancelled(self, payout_id, commit=True):
        rows = self.db.query(CashOrder).filter(CashOrder.payout_id == payout_id,
                                               CashOrder.reverses_id.is_(None)).all()
        for row in rows:
            if not self.is_reversed(row):
                return self.reverse(row, commit=commit)
        return None

    def from_refund(self, order, amount):
        """Вернули клиенту наличными — расходный ордер в открытой смене."""
        plate = order.car.license_plate if order.car else ''
        return self.create(KIND_OUT, REFUND_CATEGORY, amount, METHOD_CASH,
                           note=f'Наряд №{order.id} {plate}'.strip(), check_category=False,
                           commit=False, work_order_id=order.id)

    # ------------------------------------------------------------------
    # Сводка и обмен
    # ------------------------------------------------------------------

    def summary_lines(self, shift):
        """Строки для сводки смены в Telegram."""
        if shift.cash_start is None and shift.cash_counted is None:
            return []
        totals = self.totals(shift)
        lines = ['', '<b>Касса</b>',
                 f'На начало: {money(totals["start"])}',
                 f'Пришло: {money(totals["came"])} · ушло: {money(totals["went"])}',
                 f'Должно быть: {money(totals["expected"])}']
        if shift.cash_counted is None:
            lines.append('Пересчёта не было')
        elif shift.cash_diff:
            word = 'недостача' if shift.cash_diff < 0 else 'излишек'
            lines.append(f'Пересчитали: {money(shift.cash_counted)} · <b>{word} '
                         f'{money(abs(shift.cash_diff))}</b>')
            if shift.cash_diff_reason:
                lines.append(f'Причина: {shift.cash_diff_reason}')
        else:
            lines.append(f'Пересчитали: {money(shift.cash_counted)} · сошлось')
        out = {}
        for row in self.orders(shift):
            if row.kind == KIND_OUT:
                out[row.category] = out.get(row.category, 0) + row.amount * (-1 if row.reverses_id else 1)
        spent = [f'{name} {money(value)}' for name, value in out.items() if round(value, 2)]
        if spent:
            lines.append('Расходы: ' + ', '.join(spent))
        return lines

    def payload(self, changed_since=None):
        query = self.db.query(CashOrder)
        if changed_since is not None:
            query = query.filter(CashOrder.changed_at >= changed_since)
        uids = {row.id: row.uid for row in self.db.query(CashOrder.id, CashOrder.uid)}
        return [{
            'uid': row.uid, 'kind': row.kind, 'number': row.number, 'category': row.category,
            'amount': row.amount, 'method': row.method, 'note': row.note,
            'employee_local_id': row.employee_id, 'shift_local_id': row.shift_id,
            'created_at': as_naive(row.created_at),
            'reverses_uid': uids.get(row.reverses_id) if row.reverses_id else None,
            'payout_local_id': row.payout_id,
            'changed_at': as_naive(row.changed_at),
        } for row in query.order_by(CashOrder.id).all()]

    def _log(self, text):
        try:
            from services.audit_service import AuditService
            AuditService(self.db).log(AuditService.CASH, text, entity_type='cash')
        except Exception as e:
            self.db.rollback()
            log.warning(f'Журнал кассы: {e}')

    @staticmethod
    def _nudge(reason):
        try:
            from services import sync_nudge
            sync_nudge.request(reason)
        except Exception:
            pass
