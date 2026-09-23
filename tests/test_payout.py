"""
Выдача зарплаты: остаток, PIN, аванс, ведомость.

Начислено и выдано — разные вещи. Начисление появляется само при
оплате наряда, выдача — когда деньги отдали. Остаток считается за всё
время работы, а не за месяц: иначе прошлый невыданный хвост потеряется
при смене периода.

Выдать сверх остатка можно, но только осознанно: молча выданный аванс
через месяц превращается в вопрос «почему у него минус».
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('payout')

from datetime import timedelta

from config import init_db, SessionLocal
from models import Service, SalaryPayout, AuditLog, METHOD_CASH, METHOD_CARD
from services import (OrderService, SalaryService, EmployeeService,
                      PayoutService, PayoutError, AuthService)
from services.shift_service import ShiftService
from utils import get_moscow_time

init_db()
db = SessionLocal()

PIN = '0000'          # по умолчанию в программе именно такой

ShiftService(db).open_shift()
employees = EmployeeService(db)
employees.register_employee(1, 'Игорь')
employees.register_employee(2, 'Пётр')
employees.start_shift(1)
employees.start_shift(2)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0,
               consumable_cost=0.0))
db.commit()
service_id = db.query(Service).first().id

orders = OrderService(db)
salaries = SalaryService(db)
payouts = PayoutService(db)


def pay_order(plate, employee_ids):
    order = orders.create_order(plate, 'R16', 'car')
    orders.add_service_to_order(order.id, service_id)
    order.employee_ids = employee_ids
    db.commit()
    salaries.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    return order


print('=== Пока ничего не выдано, остаток равен начисленному ===')
first = pay_order('А111АА77', '1')
second = pay_order('В222ВВ77', '1')

check('начислено 800', payouts.accrued(1) == 800.0, str(payouts.accrued(1)))
check('выдано ноль', payouts.paid(1) == 0.0)
check('остаток 800', payouts.balance(1) == 800.0, str(payouts.balance(1)))

print('\n=== Без верного PIN не выдаётся ===')
try:
    payouts.pay(1, 500, METHOD_CASH, pin='9999')
    check('чужой PIN не пускает', False)
except PayoutError as e:
    check('чужой PIN не пускает', 'PIN' in str(e), str(e))

check('запись о выдаче не появилась', db.query(SalaryPayout).count() == 0)
check('неверный PIN попал в журнал',
      db.query(AuditLog).filter(AuditLog.action == 'auth.pin_failed').count() == 1)

print('\n=== Выдача наличными ===')
payout = payouts.pay(1, 500, METHOD_CASH, pin=PIN)
check('выдача записана', payout.id is not None)
check('способ — наличные', payout.method == METHOD_CASH)
check('не помечена авансом', payout.is_advance is False)
check('остаток уменьшился до 300', payouts.balance(1) == 300.0,
      str(payouts.balance(1)))
check('выдача попала в журнал',
      db.query(AuditLog).filter(AuditLog.action == 'salary.payout').count() == 1)

print('\n=== Сумма должна быть числом больше нуля ===')
for bad in (0, -100, 'много'):
    try:
        payouts.pay(1, bad, METHOD_CASH, pin=PIN)
        check(f'«{bad}» не принимается', False)
    except PayoutError:
        check(f'«{bad}» не принимается', True)

print('\n=== Способ выплаты только из списка ===')
try:
    payouts.pay(1, 100, 'крипта', pin=PIN)
    check('неизвестный способ отвергнут', False)
except PayoutError as e:
    check('неизвестный способ отвергнут', 'способ' in str(e).lower(), str(e))

print('\n=== Аванс: молча не выдаётся, с подтверждением — да ===')
try:
    payouts.pay(1, 1000, METHOD_CARD, pin=PIN)
    check('без подтверждения аванс не выдаётся', False)
except PayoutError as e:
    check('без подтверждения аванс не выдаётся', 'аванс' in str(e), str(e))
    check('в отказе названа сумма к выдаче', '300' in str(e), str(e))

advance = payouts.pay(1, 1000, METHOD_CARD, pin=PIN, allow_advance=True)
check('аванс выдан', advance.id is not None)
check('помечен как аванс', advance.is_advance is True)
check('остаток ушёл в минус', payouts.balance(1) == -700.0,
      str(payouts.balance(1)))

print('\n=== Выплата из дашборда PIN не требует ===')
from_dashboard = payouts.pay(2, 300, METHOD_CARD, source='dashboard',
                             server_id=77, allow_advance=True)
check('выдача с сервера записана', from_dashboard.source == 'dashboard')
check('номер на сервере сохранён', from_dashboard.server_id == 77)
# Петру пока ничего не начисляли — значит, эти 300 ушли авансом
check('остаток Петра ушёл в минус на выданное', payouts.balance(2) == -300.0,
      str(payouts.balance(2)))
check('выдача помечена авансом', from_dashboard.is_advance is True)

print('\n=== Удалённый наряд не приносит начислений ===')
third = pay_order('С333СС77', '2')
before = payouts.accrued(2)
third.is_deleted = True
db.commit()
check('начисление по удалённому наряду не считается',
      payouts.accrued(2) == before - 400.0,
      f'{payouts.accrued(2)} против {before}')

print('\n=== Отмена выдачи ===')
try:
    payouts.cancel(advance.id, pin='1234')
    check('без PIN отменить нельзя', False)
except PayoutError:
    check('без PIN отменить нельзя', True)

payouts.cancel(advance.id, pin=PIN)
check('запись удалена',
      db.query(SalaryPayout).filter(SalaryPayout.id == advance.id).first() is None)
check('остаток вернулся к 300', payouts.balance(1) == 300.0,
      str(payouts.balance(1)))
check('отмена попала в журнал',
      db.query(AuditLog).filter(
          AuditLog.action == 'salary.payout_cancel').count() == 1)

print('\n=== Остатки по всем сотрудникам ===')
everyone = {row['employee_id']: row for row in payouts.everyone()}
check('в списке оба сотрудника', sorted(everyone) == [1, 2], str(sorted(everyone)))
check('имя показано', everyone[1]['title'] == 'Игорь (№1)', everyone[1]['title'])
check('остаток Игоря 300', everyone[1]['balance'] == 300.0,
      str(everyone[1]['balance']))

print('\n=== Ведомость за период ===')
today = get_moscow_time()
statement = {row['employee_id']: row
             for row in payouts.statement(today - timedelta(days=1),
                                          today + timedelta(days=1))}

check('в ведомости оба', sorted(statement) == [1, 2], str(sorted(statement)))
check('у Игоря начислено 800', statement[1]['accrued'] == 800.0,
      str(statement[1]['accrued']))
check('у Игоря выдано 500 наличными', statement[1]['cash'] == 500.0,
      str(statement[1]['cash']))
check('картой у Игоря ноль — аванс отменили', statement[1]['card'] == 0.0,
      str(statement[1]['card']))
check('у Петра выдано картой 300', statement[2]['card'] == 300.0,
      str(statement[2]['card']))
check('в строке лежат сами выдачи', len(statement[1]['payouts']) == 1)

old = payouts.statement(today - timedelta(days=30), today - timedelta(days=10))
check('за прошлый период ведомость пустая', old == [], str(old))

db.close()
finish()
