"""
Контроль в отчётах (решение владельца 13.11.2026): без уведомлений —
в отчёте смены, в «Отчётах» и в сводке дашборда видно, что требует
внимания владельца:

  · крупные скидки — общая на наряд или на строку не меньше порога
    (Настройки → «Контроль», по умолчанию 15%);
  · удалённые наряды;
  · возвраты;
  · расхождение кассы при пересчёте на закрытии смены.

Ничего не запрещает и никого не будит — только показывает.
"""
from models import WorkOrder, WorkOrderItem
from models.shift import Shift
from utils import as_naive

THRESHOLD_KEY = 'control_discount_percent'
THRESHOLD_DEFAULT = 15


def threshold(db):
    from services.settings_service import SettingsService
    try:
        return max(1, int(SettingsService(db).get(THRESHOLD_KEY) or THRESHOLD_DEFAULT))
    except (TypeError, ValueError):
        return THRESHOLD_DEFAULT


def _plate(order):
    return order.car.license_plate if order.car else ''


def _within(moment, start, end):
    moment = as_naive(moment) if moment is not None else None
    return moment is not None and as_naive(start) <= moment <= as_naive(end)


def control(db, start, end):
    """Что показать за период: {'discounts', 'deleted', 'refunds', 'cash', 'threshold'}."""
    from services.order_service import OrderService
    edge = threshold(db)

    discounts = []
    paid = db.query(WorkOrder).filter(WorkOrder.status == 'paid', WorkOrder.paid_at.isnot(None)).all()
    for order in paid:
        if order.is_deleted or not _within(order.paid_at, start, end):
            continue
        items = db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order.id).all()
        biggest = max([int(order.general_discount or 0)] + [int(i.discount_percent or 0) for i in items])
        if biggest >= edge:
            full = sum(OrderService.item_total_without_discount(i) for i in items)
            discounts.append({'order_id': order.id, 'plate': _plate(order), 'percent': biggest,
                              'amount': round(full - float(order.total_amount or 0), 2)})

    deleted = [{'order_id': o.id, 'plate': _plate(o), 'total': float(o.total_amount or 0),
                'paid': o.status == 'paid', 'at': as_naive(o.deleted_at)}
               for o in db.query(WorkOrder).filter(WorkOrder.is_deleted.is_(True),
                                                   WorkOrder.deleted_at.isnot(None)).all()
               if _within(o.deleted_at, start, end)]

    refunds = [{'order_id': o.id, 'plate': _plate(o), 'amount': float(o.refunded_amount or 0),
                'reason': getattr(o, 'refund_reason', None) or ''}
               for o in db.query(WorkOrder).filter(WorkOrder.refunded_at.isnot(None)).all()
               if _within(o.refunded_at, start, end) and (o.refunded_amount or 0) > 0]

    cash = [{'shift_id': s.id, 'diff': round(float(s.cash_diff), 2), 'reason': s.cash_diff_reason or ''}
            for s in db.query(Shift).filter(Shift.cash_diff.isnot(None)).all()
            if abs(float(s.cash_diff or 0)) >= 0.01 and _within(s.end_time or s.start_time, start, end)]

    return {'discounts': discounts, 'deleted': deleted, 'refunds': refunds, 'cash': cash,
            'threshold': edge}


def lines(report):
    """Строки для сводки в Telegram. Пусто — «замечаний нет»."""
    out = []
    for row in report['discounts']:
        out.append(f"  скидка {row['percent']}%: №{row['order_id']} {row['plate']} — −{row['amount']:.0f} ₽")
    for row in report['deleted']:
        out.append(f"  удалён наряд №{row['order_id']} {row['plate']}"
                   + (f" ({row['total']:.0f} ₽, был оплачен)" if row['paid'] else ''))
    for row in report['refunds']:
        out.append(f"  возврат №{row['order_id']} {row['plate']}: {row['amount']:.0f} ₽"
                   + (f" — {row['reason']}" if row['reason'] else ''))
    for row in report['cash']:
        sign = 'излишек' if row['diff'] > 0 else 'недостача'
        out.append(f"  касса смены №{row['shift_id']}: {sign} {abs(row['diff']):.0f} ₽"
                   + (f" — {row['reason']}" if row['reason'] else ''))
    return out
