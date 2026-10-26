"""
Касса: приходные и расходные ордера, остаток, пересчёт (docs/cash.md).

Решения владельца от 26.10.2026:

  · при открытии смены вводят фактическую сумму наличных;
  · расходный вычитает, приходный прибавляет, безнал виден, но кассу
    не меняет;
  · выдача зарплаты сама проводит расходный ордер; на карту — ордер
    есть, касса не меняется;
  · статьи настраиваются; «Размена» нет — приход: Внесение, Прочее;
  · пересчёт при закрытии обязателен, расхождение — в сводку.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('cash')
os.chdir(_setup.PROJECT_DIR)
shown = _setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee
from models.cash import CashOrder, KIND_IN, KIND_OUT, METHOD_NONCASH
from services import EmployeeService, OrderService, SalaryService
from services.shift_service import ShiftService
from services.payout_service import PayoutService
from services.cash_service import CashService, CashError
from services.shift_report_service import ShiftReportService
from services.sync_service import SyncService

PIN = '0000'
init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
cash = CashService(db)
shifts = ShiftService(db)
orders = OrderService(db)
salary = SalaryService(db)

print('=== Статьи ===')
check('расход по умолчанию', cash.categories(KIND_OUT) ==
      ['Зарплата', 'Расходники', 'Вода', 'Аренда', 'Инкассация', 'Прочее'])
check('приход без «Размена»', cash.categories(KIND_IN) == ['Внесение', 'Прочее'])
cash.set_categories(KIND_OUT, cash.categories(KIND_OUT) + ['Мусор'])
check('статью можно добавить', 'Мусор' in cash.categories(KIND_OUT))
cash.set_categories(KIND_OUT, [c for c in cash.categories(KIND_OUT) if c != 'Аренда'])
check('и убрать', 'Аренда' not in cash.categories(KIND_OUT))
try:
    cash.set_categories(KIND_IN, [])
    check('пустой список нельзя', False)
except CashError:
    check('пустой список нельзя', True)

print()
print('=== Смена и остаток ===')
check('первая смена — подсказки нет', cash.suggested_start() is None)
shift = shifts.open_shift(cash_start='5 000')
check('на начало — что ввели', shift.cash_start == 5000)
for n in (1, 2):
    EmployeeService(db).register_employee(n)
    EmployeeService(db).start_shift(n)
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()

paid_cash = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
orders.add_service_to_order(paid_cash.id, 1)
salary.process_payment(paid_cash.id, 'cash', orders.calculate_total(paid_cash.id))
paid_card = orders.create_order('В200ВВ77', 'R16', 'car', create_client=False)
orders.add_service_to_order(paid_card.id, 1)
salary.process_payment(paid_card.id, 'card', orders.calculate_total(paid_card.id))
check('наличные прибавились, карта — нет', cash.expected(shift) == 7000)

cash.create(KIND_IN, 'Внесение', '3000', note='внёс владелец', employee_id=1)
water = cash.create(KIND_OUT, 'Вода', 1000, note='6 бутылей', employee_id=2)
cash.create(KIND_OUT, 'Расходники', 500, method=METHOD_NONCASH, note='по счёту')
check('приходный +, расходный −, безнал не трогает', cash.expected(shift) == 9000)
check('номера подряд у каждого вида',
      [o.number for o in cash.orders(shift) if o.kind == KIND_OUT] == [1, 2]
      and [o.number for o in cash.orders(shift) if o.kind == KIND_IN] == [1])
try:
    cash.create(KIND_OUT, 'Аренда', 100)
    check('убранной статьёй — нельзя', False)
except CashError:
    check('убранной статьёй — нельзя', True)
try:
    cash.create(KIND_OUT, 'Вода', 0)
    check('ноль — нельзя', False)
except CashError:
    check('ноль — нельзя', True)

back = cash.reverse(water, employee_id=1)
check('отмена вернула деньги в кассу', cash.expected(shift) == 10000)
check('в списке оба', db.query(CashOrder).count() == 4 and back.reverses_id == water.id)
try:
    cash.reverse(water)
    check('второй раз не отменить', False)
except CashError:
    check('второй раз не отменить', True)

print()
print('=== Выдача зарплаты ===')
payouts = PayoutService(db)
payout = payouts.pay(1, 400, 'cash', pin=PIN)
row = db.query(CashOrder).filter(CashOrder.payout_id == payout.id).first()
check('наличными — расходный «Зарплата»', row is not None and row.kind == KIND_OUT
      and row.category == 'Зарплата' and cash.expected(shift) == 9600)
card = payouts.pay(2, 400, 'card', pin=PIN)
row = db.query(CashOrder).filter(CashOrder.payout_id == card.id).first()
check('на карту — ордер есть, касса та же', row.method == METHOD_NONCASH and cash.expected(shift) == 9600)
payouts.cancel(payout.id, PIN)
check('отменили выдачу — ордер отменён обратным', cash.expected(shift) == 10000)
cash.set_categories(KIND_OUT, ['Вода', 'Прочее'])
payouts.pay(1, 100, 'cash', pin=PIN)
check('статью «Зарплата» убрали — выдача всё равно под ней',
      db.query(CashOrder).filter(CashOrder.category == 'Зарплата').count() == 4)

print()
print('=== Возврат наличными ===')
orders.refund_order(paid_cash.id, amount=500, reason='скидка задним числом')
check('возврат наличными уменьшил кассу', cash.expected(shift) == 9400)
lines = cash.lines(shift)
check('в списке операций всё по времени', [l['tag'] for l in lines][:2] == ['start', 'paid']
      and any(l['tag'] == 'card' and l['effect'] == 0 for l in lines))

print()
print('=== Обмен ===')
push = SyncService(db).collect_push()
sent = push['cash_orders']
check('ордера уходят на сервер', len(sent) == db.query(CashOrder).count())
reversal = next(o for o in sent if o['reverses_uid'])
check('отмена ссылается на uid ордера', reversal['reverses_uid'] == water.uid)
open_shift = next(s for s in push['shifts'] if s['local_id'] == shift.id)
check('у открытой смены — текущий остаток', open_shift['cash_start'] == 5000
      and open_shift['cash_expected'] == 9400)

print()
print('=== Закрытие: пересчёт ===')
try:
    cash.count(shift, 9200)
    check('расхождение без причины — нельзя', False)
except CashError:
    db.rollback()
    check('расхождение без причины — нельзя', True)
diff = cash.count(shift, 9200, 'не нашли')
check('недостача 200', diff == -200 and shift.cash_diff == -200 and shift.cash_counted == 9200)
summary = ShiftReportService(db)
text = summary.format_summary(summary.build_summary(shift))
check('в сводке — касса и расхождение', 'недостача 200 ₽' in text and 'Причина: не нашли' in text, text[-300:])
shifts.close_shift(shift.id)
check('подсказка на следующую смену — пересчитанное', cash.suggested_start() == 9200)
second = shifts.open_shift(cash_start=9200)
check('новая смена — свой остаток', cash.expected(second) == 9200 and cash.lines(second)[0]['tag'] == 'start')

print()
print('=== Окна ===')
import tkinter as tk
import styles
root = tk.Tk()
root.withdraw()
styles.apply_modern_styles(root)
from ui.cash_tab import CashTab, CashOrderDialog, CountDialog
tab = CashTab(root, db)
check('открыта текущая смена', tab.shift.id == second.id)
dialog = CashOrderDialog(tab.frame, db, KIND_OUT, tab._changed)
dialog.category.set('Вода')
dialog.amount.insert(0, '700')
dialog.save()
check('ордер из окна', cash.expected(second) == 8500 and len(tab.tree.get_children()) == 2)
tab.shift = shift
tab.load(keep=True)
check('прошлая смена: строки и пересчёт', tab.shift.id == shift.id and len(tab.tree.get_children()) > 5
      and any('9 200' in w.cget('text') for t in tab.tiles.winfo_children() for w in t.winfo_children()))
counting = CountDialog(tab.frame, db, second)
counting.save()
check('без суммы смену не закрыть', not counting.ok)
counting.counted.insert(0, '8500')
counting.save()
check('сошлось — можно закрывать', counting.ok and second.cash_diff == 0)
root.destroy()

db.close()
finish()
