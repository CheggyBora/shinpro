"""
Работы у партнёров (решения владельца 13.11.2026). Ожидаемое — руками.

  · постоянная услуга контрагента: наша цена, цена партнёра, начисление;
  · работа из наряда и отдельно (наряд заводится сам);
  · статусы: согласование → в работе → ждёт оплаты → оплачено; покраска —
    ещё «согласование с клиентом»; отказ убирает строку из наряда;
  · в наряде — только наша цена; мастерам наряда с работы партнёра 0;
    сотрудникам — по правилу работы; администратору — % с полной цены;
  · цену партнёра вписали после оплаты наряда — маржа досчитывается;
  · оплата партнёру: наличные — РКО, безнал — касса не меняется, другое —
    никаких ордеров; несколько работ одного партнёра — один ордер.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('partners')
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, Employee, SalaryTransaction, WorkOrder
from models.cash import CashOrder, METHOD_CASH, METHOD_NONCASH
from services import EmployeeService, OrderService, SalaryService
from services.calendar_service import CalendarService
from services.cash_service import CashService
from services.partner_service import (PartnerService, PartnerError, ST_AGREE, ST_CLIENT, ST_WORK,
                                      ST_WAIT, ST_PAID, ST_REFUSED, KIND_PAINT, PAY_CASH,
                                      PAY_NONCASH, PAY_OTHER, SAL_CREATOR, SAL_PEOPLE,
                                      MODE_MARGIN_PCT, MODE_MARGIN_ALL, MODE_PRICE_PCT, MODE_FIXED)
from services.shift_service import ShiftService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
MOUNT = 1
IVAN, PETR, OLGA = 1, 2, 3
staff = EmployeeService(db)
staff.register_employee(IVAN, name='Иван')
staff.register_employee(PETR, name='Пётр')
staff.register_employee(OLGA, name='Ольга', admin_percent=5)
for e in db.query(Employee).all():
    e.salary_percent = 40
db.commit()
shift = ShiftService(db).open_shift(open_posts=2, cash_start=10000)
for n in (IVAN, OLGA):
    staff.start_shift(n)

orders = OrderService(db)
salary = SalaryService(db)
partners = PartnerService(db)
weld = CalendarService(db).save_counterparty(name='Сварка Плюс', kind='сварка дисков')
paint = CalendarService(db).save_counterparty(name='Колор-Сервис', kind='покраска')


def pay(order):
    salary.process_payment(order.id, 'cash', orders.calculate_total(order.id))
    result = {}
    for t in db.query(SalaryTransaction).filter_by(work_order_id=order.id):
        result[t.employee_id] = round(result.get(t.employee_id, 0) + t.amount, 2)
    return {k: v for k, v in result.items() if v}


print('=== Постоянная услуга контрагента ===')
try:
    partners.save_offering(counterparty_uid=weld.uid, name='Сварка диска', salary_to=SAL_CREATOR)
    check('начисление без способа — отказ', False)
except PartnerError as e:
    check('начисление без способа — отказ', 'как начислять' in str(e), str(e))
db.rollback()
offer = partners.save_offering(counterparty_uid=weld.uid, name='Сварка диска', our_price='3 500',
                               partner_price=2000, salary_to=SAL_CREATOR,
                               salary_mode=MODE_MARGIN_PCT, salary_value=10)
check('услуга сохранена: 3500 / 2000, 10% от маржи оформившему',
      offer.our_price == 3500 and offer.partner_price == 2000 and offer.salary_mode == MODE_MARGIN_PCT)
check('в списке контрагента', [o.name for o in partners.offerings(weld.uid)] == ['Сварка диска'])

print('\n=== Из наряда: цена партнёра ещё не известна ===')
order = orders.create_order('А123ВВ777', 'R16', 'car', create_client=False)
orders.add_service_to_order(order.id, MOUNT)
job = partners.create_job(weld.uid, offer.name, offer.our_price, kind='work', order_id=order.id,
                          creator_id=IVAN, salary={'salary_to': offer.salary_to,
                                                   'salary_mode': offer.salary_mode,
                                                   'salary_value': offer.salary_value})
check('статус — согласование с партнёром', job.partner_status == ST_AGREE)
line = partners.line_of(job)
check('в наряде строка 3500, без цены партнёра', line.price == 3500 and line.order_id == order.id
      if hasattr(line, 'order_id') else line.price == 3500)
check('итог наряда 2000 + 3500', orders.calculate_total(order.id) == 5500, str(orders.calculate_total(order.id)))
check('в прайсе строку не видно', not db.query(Service).filter(Service.id == line.service_id).first().is_active)
partners.set_partner_price(job, 2000)
check('цена партнёра 2000 — в работе', job.partner_status == ST_WORK)
got = pay(order)
# Иван — мастер наряда: шиномонтаж 2000 × 40% = 800; со сварки — по правилу работы:
# 10% от маржи (3500 − 2000) = 150 → 950. Ольга — 5% со всего: 5% × 5500 = 275
check('Иван 950 (800 + 150 со сварки), Ольга 275', got == {IVAN: 950.0, OLGA: 275.0}, str(got))

print('\n=== Цену партнёра вписали после оплаты ===')
order2 = orders.create_order('В222ВВ77', 'R16', 'car', create_client=False)
job2 = partners.create_job(weld.uid, 'Сварка диска R17', 3500, order_id=order2.id, creator_id=IVAN,
                           salary={'salary_to': SAL_CREATOR, 'salary_mode': MODE_MARGIN_ALL})
got = pay(order2)
check('наряд только с работой партнёра пробивается без мастеров; Ивану пока 0, Ольге 175',
      got == {OLGA: 175.0}, str(got))
partners.set_partner_price(job2, 1000)
got = {}
for t in db.query(SalaryTransaction).filter_by(work_order_id=order2.id):
    got[t.employee_id] = round(got.get(t.employee_id, 0) + t.amount, 2)
check('вписали 1000 — Ивану досчитана вся маржа 2500', got.get(IVAN) == 2500.0, str(got))
partners.set_partner_price(job2, 1200)
got = {}
for t in db.query(SalaryTransaction).filter_by(work_order_id=order2.id):
    got[t.employee_id] = round(got.get(t.employee_id, 0) + t.amount, 2)
check('поправили на 1200 — у Ивана 2300, не задвоилось', got.get(IVAN) == 2300.0, str(got))

print('\n=== Другие правила начисления ===')
for mode, value, to, people, expected in (
        (MODE_PRICE_PCT, 5, SAL_PEOPLE, [IVAN, PETR], {IVAN: 87.5, PETR: 87.5}),
        (MODE_FIXED, 300, SAL_PEOPLE, [PETR], {PETR: 300.0})):
    order3 = orders.create_order('С333СС77', 'R16', 'car', create_client=False)
    partners.create_job(weld.uid, 'Сварка', 3500, partner_price=2000, order_id=order3.id,
                        salary={'salary_to': to, 'salary_mode': mode, 'salary_value': value,
                                'salary_people': people})
    got = pay(order3)
    got.pop(OLGA, None)
    check(f'{mode}: {expected}', got == expected, str(got))

print('\n=== Закрыто → оплата партнёру ===')
partners.finish(job)
partners.finish(job2)
check('ждут оплаты — обе', {j.uid for j in partners.to_pay()} == {job.uid, job2.uid})
before = CashService(db).totals(shift)['went']
made = partners.pay([job, job2], PAY_CASH, note='отдали Сергею')
check('один РКО на партнёра: 2000 + 1200 = 3200, наличные, статья «Партнёры»',
      len(made) == 1 and made[0].amount == 3200 and made[0].method == METHOD_CASH
      and made[0].category == 'Партнёры', str([(m.amount, m.method, m.category) for m in made]))
check('из кассы ушло 3200', round(CashService(db).totals(shift)['went'] - before, 2) == 3200)
check('обе оплачены', job.partner_status == ST_PAID and job2.partner_status == ST_PAID)
try:
    partners.pay([job], PAY_CASH)
    check('второй раз не платим', False)
except PartnerError:
    check('второй раз не платим', True)

order4 = orders.create_order('Е444ЕЕ77', 'R16', 'car', create_client=False)
job4 = partners.create_job(weld.uid, 'Сварка', 3000, partner_price=1500, order_id=order4.id)
partners.finish(job4)
before = CashService(db).totals(shift)['went']
made = partners.pay([job4], PAY_NONCASH)
check('безнал: ордер есть, касса не изменилась', len(made) == 1 and made[0].method == METHOD_NONCASH
      and CashService(db).totals(shift)['went'] == before)
order5 = orders.create_order('К555КК77', 'R16', 'car', create_client=False)
job5 = partners.create_job(weld.uid, 'Сварка', 3000, partner_price=1500, order_id=order5.id)
partners.finish(job5)
count = db.query(CashOrder).count()
made = partners.pay([job5], PAY_OTHER, note='взаимозачёт')
check('другое: ордеров нет, только пометка', not made and db.query(CashOrder).count() == count
      and job5.pay_note == 'взаимозачёт' and job5.partner_status == ST_PAID)

print('\n=== Покраска отдельно, без наряда ===')
job6 = partners.create_job(paint.uid, 'Покраска дисков R17 × 4', 8000, kind=KIND_PAINT,
                           plate='м777мм77', client_phone='+79001112233')
order6 = partners.order_of(job6)
check('наряд завёлся сам на машину', order6 is not None and order6.car.license_plate == 'М777ММ77'
      and orders.calculate_total(order6.id) == 8000)
partners.set_partner_price(job6, 3500)
check('цена партнёра — теперь согласование с клиентом', job6.partner_status == ST_CLIENT)
partners.client_answer(job6, True)
check('клиент согласен — в работе', job6.partner_status == ST_WORK)

job7 = partners.create_job(paint.uid, 'Покраска R16 × 2', 4000, kind=KIND_PAINT, plate='Р888РР77',
                           partner_price=1800)
check('цена партнёра известна сразу — всё равно ждём клиента', job7.partner_status == ST_CLIENT)
order7 = partners.order_of(job7)
partners.client_answer(job7, False)
check('клиент отказался — отказ, строки в наряде нет',
      job7.partner_status == ST_REFUSED and orders.calculate_total(order7.id) == 0)

print('\n=== Без машины ===')
job8 = partners.create_job(weld.uid, 'Сварка для своих', 1000, partner_price=500)
check('наряд на «ПАРТНЁР»', partners.order_of(job8).car.license_plate == 'ПАРТНЁР')
check('задача в календаре без номера', job8.license_plate is None)

db.close()
finish()
