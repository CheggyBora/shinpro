"""
Касса: приём ордеров из цеха и раздел дашборда «Касса» (docs/cash.md).

Кассу ведёт цех. Сюда приезжают ордера, изменённые с прошлого обмена,
и поля кассы у смен. Дашборд только показывает: сколько сейчас в
кассе, на что ушли деньги за период и где касса не сошлась.

Присланное чистим, а не принимаем на веру: старая или сломанная
программа цеха не должна уронить весь обмен одним кривым ордером.
Ордер, вид или сумму которого понять нельзя, пропускаем — гадать,
приход это или расход, в деньгах нельзя.
"""
import math
from datetime import datetime

from app.models import CashOrder, ShopEmployee, ShopShift
from app.models.cash import KINDS, KIND_OUT, METHOD_CASH, METHOD_NONCASH
from app.utils import now as shop_now

# Больше этого ордер в шиномонтаже не бывает; больше — значит мусор
MAX_AMOUNT = 1e9

# Безнал цех называет noncash. Похожее на безнал тоже понимаем как
# безнал: ошибиться в другую сторону значило бы «вынуть» из кассы
# деньги, которых там не было
NONCASH_WORDS = {METHOD_NONCASH, 'card', 'transfer', 'bank', 'безнал',
                 'карта'}


def money(value):
    """Число из присланного: 1000, «1 000,50». Не число — None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(' ', '').replace(' ', '').replace(',', '.')
        if not value:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def amount_of(value):
    """Сумма ордера: число от нуля до предела. Иначе None."""
    number = money(value)
    if number is None or number < 0 or number > MAX_AMOUNT:
        return None
    return round(number, 2)


def shift_money(value):
    """
    Деньги смены: остаток, пересчёт, расхождение. Расхождение бывает
    отрицательным, остаток — тоже (ушли в минус по ошибке ввода), но
    бесконечность и не-число — нет.
    """
    number = money(value)
    if number is None or abs(number) > MAX_AMOUNT:
        return None
    return round(number, 2)


def _text(value, limit):
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] or None


def _int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
    return number if -2**31 < number < 2**31 else None


def _when(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.replace(tzinfo=None)


def clean_order(item):
    """
    Ордер из обмена в чистом виде или None, если понять его нельзя.

    Без uid ордер не найти при следующем обмене; без вида и суммы
    неясно, что он сделал с кассой.
    """
    if not isinstance(item, dict):
        return None

    uid = _text(item.get('uid'), 40)
    kind = str(item.get('kind') or '').strip().lower()
    amount = amount_of(item.get('amount'))
    if not uid or kind not in KINDS or amount is None:
        return None

    method = str(item.get('method') or '').strip().lower()
    method = METHOD_NONCASH if method in NONCASH_WORDS else METHOD_CASH

    number = _int(item.get('number'))
    return {
        'uid': uid,
        'kind': kind,
        'number': number if number is not None and number >= 0 else None,
        'category': _text(item.get('category'), 60),
        'amount': amount,
        'method': method,
        'note': _text(item.get('note'), 1000),
        'employee_local_id': _int(item.get('employee_local_id')),
        'shift_local_id': _int(item.get('shift_local_id')),
        'created_at': _when(item.get('created_at')),
        'reverses_uid': _text(item.get('reverses_uid'), 40),
        'payout_local_id': _int(item.get('payout_local_id')),
        'changed_at': _when(item.get('changed_at')),
    }


def upsert_orders(db, shop, items):
    """
    Принять ордера из обмена: обновить по uid, новые завести.

    Возвращает (принято, отклонено uid-ами). Ордера не удаляются никогда:
    цех их тоже не удаляет, а отменяет обратным.
    """
    accepted = 0
    rejected = []
    seen = {}

    for item in items or []:
        clean = clean_order(item)
        if clean is None:
            rejected.append(str((item or {}).get('uid') or '')[:40]
                            if isinstance(item, dict) else '')
            continue

        row = seen.get(clean['uid'])
        if row is None:
            row = db.query(CashOrder).filter(
                CashOrder.shop_id == shop.id,
                CashOrder.uid == clean['uid']).first()
        if row is None:
            row = CashOrder(shop_id=shop.id, uid=clean['uid'])
            db.add(row)

        for key, value in clean.items():
            if key == 'created_at':
                # Время ордера не теряем: без него он выпал бы из периода
                value = value or row.created_at or shop_now()
            setattr(row, key, value)

        seen[clean['uid']] = row
        accepted += 1

    db.flush()
    return accepted, rejected


def apply_shift(row, item):
    """Поля кассы у смены. Старая программа их не шлёт — тогда не трогаем."""
    sent = item.model_fields_set if hasattr(item, 'model_fields_set') else set()
    for key in ('cash_start', 'cash_expected', 'cash_counted', 'cash_diff'):
        if key in sent:
            setattr(row, key, shift_money(getattr(item, key)))
    if 'cash_diff_reason' in sent:
        row.cash_diff_reason = _text(item.cash_diff_reason, 255)


# ----------------------------------------------------------------------
# Дашборд
# ----------------------------------------------------------------------

def signed(order):
    """Сумма с учётом отмены: обратный ордер вычитает из своей статьи."""
    return -(order.amount or 0.0) if order.reverses_uid else (order.amount or 0.0)


def _people(db, shop_ids):
    rows = db.query(ShopEmployee).filter(
        ShopEmployee.shop_id.in_(shop_ids)).all() if shop_ids else []
    return {(row.shop_id, row.local_id): row.title for row in rows}


def now_in_cash(db, shops, titles):
    """
    Сколько сейчас в кассе каждой точки.

    Смена открыта — её «должно быть». Закрыта — сколько пересчитали при
    закрытии: это и лежит в ящике до следующего открытия. Ничего не
    считали (старая программа цеха) — пусто, а не ноль.
    """
    answer = []
    for shop in shops:
        open_shift = db.query(ShopShift).filter(
            ShopShift.shop_id == shop.id,
            ShopShift.status == 'open').order_by(
            ShopShift.started_at.desc().nullslast(),
            ShopShift.id.desc()).first()

        if open_shift is not None:
            answer.append({
                'shop_id': shop.id,
                'shop_name': titles.get(shop.id),
                'cash_expected': open_shift.cash_expected,
                'shift_started_at': open_shift.started_at,
                'shift_open': True,
            })
            continue

        last = db.query(ShopShift).filter(
            ShopShift.shop_id == shop.id,
            ShopShift.status != 'open').order_by(
            ShopShift.ended_at.desc().nullslast(),
            ShopShift.started_at.desc().nullslast()).first()
        counted = None
        if last is not None:
            counted = (last.cash_counted if last.cash_counted is not None
                       else last.cash_expected)
        answer.append({
            'shop_id': shop.id,
            'shop_name': titles.get(shop.id),
            'cash_expected': counted,
            'shift_started_at': None,
            'shift_open': False,
        })
    return answer


def orders_for(db, shop_ids, start, end, titles):
    """Ордера за период, новые сверху. Отменённые и отмены — оба."""
    if not shop_ids:
        return []

    rows = db.query(CashOrder).filter(
        CashOrder.shop_id.in_(shop_ids),
        CashOrder.created_at >= start,
        CashOrder.created_at <= end).order_by(
        CashOrder.created_at.desc(), CashOrder.id.desc()).all()

    # Кто кого отменил. Пара может разойтись по периодам: отменили на
    # следующий день — смотрим во всей точке, а не только в периоде
    uids = {row.uid for row in rows}
    wanted = {row.reverses_uid for row in rows if row.reverses_uid}
    related = {}
    if uids or wanted:
        for row in db.query(CashOrder).filter(
                CashOrder.shop_id.in_(shop_ids)).filter(
                CashOrder.reverses_uid.in_(uids) | CashOrder.uid.in_(wanted)
                ).all():
            related.setdefault(row.shop_id, []).append(row)

    reversed_by = {}
    originals = {}
    for group in list(related.values()) + [rows]:
        for row in group:
            if row.reverses_uid:
                reversed_by[(row.shop_id, row.reverses_uid)] = row
            originals[(row.shop_id, row.uid)] = row

    people = _people(db, shop_ids)

    def title(shop_id, local_id):
        if local_id is None:
            return None
        return people.get((shop_id, local_id)) or f'№{local_id}'

    answer = []
    for row in rows:
        back = reversed_by.get((row.shop_id, row.uid))
        original = (originals.get((row.shop_id, row.reverses_uid))
                    if row.reverses_uid else None)
        answer.append({
            'uid': row.uid,
            'shop_id': row.shop_id,
            'shop_name': titles.get(row.shop_id),
            'kind': row.kind,
            'number': row.number,
            'category': row.category,
            'amount': round(row.amount or 0.0, 2),
            'method': row.method,
            'note': row.note,
            'employee_local_id': row.employee_local_id,
            'employee_title': title(row.shop_id, row.employee_local_id),
            'shift_local_id': row.shift_local_id,
            'created_at': row.created_at,
            'reverses_uid': row.reverses_uid,
            # Номер отменённого — чтобы написать «отмена №31»
            'reverses_number': original.number if original else None,
            'payout_local_id': row.payout_local_id,
            # Этот ордер отменён: кем и когда
            'reversed_by_uid': back.uid if back else None,
            'reversed_by_number': back.number if back else None,
            'reversed_by_title': (title(back.shop_id, back.employee_local_id)
                                  if back else None),
        })
    return answer


def totals_for(orders):
    """
    Итоги по статьям: расход и приход наличными отдельно, безнал одной
    цифрой. Отмена идёт с минусом, и пара «ордер + отмена» даёт ноль.
    Статьи, которые обнулились, не показываем.
    """
    out, came = {}, {}
    noncash_out = 0.0
    for row in orders:
        value = -row['amount'] if row['reverses_uid'] else row['amount']
        name = row['category'] or 'Без статьи'
        if row['method'] == METHOD_NONCASH:
            if row['kind'] == KIND_OUT:
                noncash_out += value
            continue
        bucket = out if row['kind'] == KIND_OUT else came
        bucket[name] = bucket.get(name, 0.0) + value

    def tidy(bucket):
        return {name: round(value, 2) for name, value in
                sorted(bucket.items(), key=lambda pair: -pair[1])
                if abs(value) >= 0.005}

    return {'out': tidy(out), 'in': tidy(came),
            'noncash_out': round(noncash_out, 2)}


def shifts_for(db, shop_ids, start, end, titles):
    """Смены периода с пересчётом кассы. Без пересчёта — не показываем."""
    if not shop_ids:
        return []

    rows = db.query(ShopShift).filter(
        ShopShift.shop_id.in_(shop_ids),
        ShopShift.started_at >= start,
        ShopShift.started_at <= end).filter(
        (ShopShift.cash_start.isnot(None))
        | (ShopShift.cash_counted.isnot(None))
        | (ShopShift.cash_expected.isnot(None))).order_by(
        ShopShift.started_at.desc()).all()

    def diff_of(row):
        # Цех присылает расхождение сам; нет его, а обе цифры есть —
        # считаем так же, как цех: пересчитали минус «должно быть»
        if row.cash_diff is not None:
            return row.cash_diff
        if row.cash_counted is not None and row.cash_expected is not None:
            return round(row.cash_counted - row.cash_expected, 2)
        return None

    return [{
        'local_id': row.local_id,
        'shop_id': row.shop_id,
        'shop_name': titles.get(row.shop_id),
        'status': row.status,
        'started_at': row.started_at,
        'ended_at': row.ended_at,
        'cash_start': row.cash_start,
        'cash_expected': row.cash_expected,
        'cash_counted': row.cash_counted,
        'cash_diff': diff_of(row),
        'cash_diff_reason': row.cash_diff_reason,
    } for row in rows]
