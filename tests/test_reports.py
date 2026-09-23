"""
Отчёты: по нарядам, по услугам, по мастерам, выгрузка.

Владелец должен видеть, из чего сложился результат каждого наряда:
сколько ушло на материалы, сколько мастерам и что осталось.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('reports')

import os
from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Service
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService
from services.statistics_service import StatisticsService
from services.export_service import export_rows, get_exports_dir

init_db()
db = SessionLocal()

ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.register_employee(2)
emp.start_shift(1)

order_service = OrderService(db)
salary_service = SalaryService(db)
stats = StatisticsService(db)

# Шиномонтаж: 1000 ₽, материалов на 100
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0,
               consumable_cost=100.0))
db.add(Service(name='Балансировка', vehicle_type='car', price_r16=500.0,
               consumable_cost=0.0))
db.commit()
services = {s.name: s for s in db.query(Service).all()}

# Наряд 1: один мастер, без скидки
o1 = order_service.create_order('А123ВВ777', 'R16', 'car',
                                client_name='Андрей', client_phone='79099018931')
order_service.add_service_to_order(o1.id, services['Шиномонтаж'].id)
salary_service.process_payment(o1.id, 'cash', order_service.calculate_total(o1.id))

# Наряд 2: двое мастеров, со скидкой
emp.start_shift(2)
o2 = order_service.create_order('К900ОР99', 'R16', 'car')
order_service.add_service_to_order(o2.id, services['Шиномонтаж'].id)
order_service.add_service_to_order(o2.id, services['Балансировка'].id)
order_service.update_general_discount(o2.id, 10)
salary_service.process_payment(o2.id, 'card', order_service.calculate_total(o2.id))

PERIOD = (datetime.now() - timedelta(days=1), datetime.now() + timedelta(days=1))

print('=== Отчёт по нарядам ===')
report = stats.get_orders_report(*PERIOD)
check('оба наряда в отчёте', len(report) == 2, str(len(report)))

first = next(r for r in report if r['id'] == o1.id)
# У наряда указаны и имя, и телефон — значит сработала автоскидка 5%:
# 1000 -> 950. База для ЗП = 950 - 100 материалов = 850, мастеру 40% = 340.
check('сумма с автоскидкой 950', first['total'] == 950.0, str(first['total']))
check('автоскидка 50 показана', first['discount'] == 50.0, str(first['discount']))
check('сумма без скидки 1000', first['full_price'] == 1000.0, str(first['full_price']))
check('расходники 100', first['consumables'] == 100.0, str(first['consumables']))
check('зарплата 40% от базы 850 = 340', first['salary_total'] == 340.0,
      str(first['salary_total']))
check('маржа 950 - 100 - 340 = 510', first['margin'] == 510.0, str(first['margin']))
check('автомобиль указан', first['license_plate'] == 'А123ВВ777')
check('клиент указан', first['client_name'] == 'Андрей')
check('способ оплаты', first['payment_method'] == 'Наличные')

print('\n=== Разбивка зарплаты по мастерам ===')
second = next(r for r in report if r['id'] == o2.id)
check('в наряде двое мастеров', len(second['salaries']) == 2,
      str(len(second['salaries'])))
check('сумма разбивки равна итогу',
      round(sum(s['amount'] for s in second['salaries']), 2) == second['salary_total'],
      f"{second['salaries']} vs {second['salary_total']}")
check('видны номера мастеров',
      sorted(s['employee_id'] for s in second['salaries']) == [1, 2],
      str([s['employee_id'] for s in second['salaries']]))

print('\n=== Скидка видна в отчёте ===')
check('скидка посчитана', second['discount'] > 0, str(second['discount']))
check('сумма без скидки больше итога', second['full_price'] > second['total'],
      f"{second['full_price']} vs {second['total']}")
check('сумма без скидки минус скидка = итог',
      round(second['full_price'] - second['discount'], 2) == second['total'],
      f"{second['full_price']} - {second['discount']} != {second['total']}")

print('\n=== Состав наряда доступен ===')
check('позиции наряда переданы', len(second['items']) == 2, str(len(second['items'])))
check('услуги названы',
      {i.service.name for i in second['items']} == {'Шиномонтаж', 'Балансировка'})

print('\n=== Сводка по услугам с расходниками ===')
summary = stats.get_sales_statistics(*PERIOD)
tyre = next(s for s in summary['services'] if s['name'] == 'Шиномонтаж')
check('расходники по услуге посчитаны', tyre['consumables'] == 200.0,
      str(tyre['consumables']))
check('маржа по услуге = выручка минус расходники',
      round(tyre['revenue'] - tyre['consumables'], 2) == tyre['margin'],
      f"{tyre['revenue']} - {tyre['consumables']} vs {tyre['margin']}")

balance = next(s for s in summary['services'] if s['name'] == 'Балансировка')
check('услуга без материалов имеет нулевые расходники', balance['consumables'] == 0.0)

print('\n=== Итоговая маржа учитывает зарплату ===')
check('зарплата в сводке есть', summary['total_salary'] > 0, str(summary['total_salary']))
check('маржа = выручка - расходники - зарплата',
      round(summary['total_revenue'] - summary['total_consumables']
            - summary['total_salary'], 2) == summary['margin'],
      f"{summary['total_revenue']} - {summary['total_consumables']} "
      f"- {summary['total_salary']} vs {summary['margin']}")

print('\n=== Отчёт по мастерам ===')
masters = stats.get_masters_report(*PERIOD)
check('оба мастера в отчёте', len(masters) == 2, str(len(masters)))
check('у мастера 1 два наряда',
      next(m for m in masters if m['employee_id'] == 1)['orders'] == 2,
      str(next(m for m in masters if m['employee_id'] == 1)['orders']))
check('у мастера 2 один наряд',
      next(m for m in masters if m['employee_id'] == 2)['orders'] == 1)
check('сумма начислений сходится с нарядами',
      round(sum(m['salary'] for m in masters), 2) == summary['total_salary'],
      f"{sum(m['salary'] for m in masters)} vs {summary['total_salary']}")

print('\n=== Удалённый наряд из отчёта уходит ===')
order_service.delete_work_order(o1.id, reason='проверка')
after = stats.get_orders_report(*PERIOD)
check('в отчёте остался один наряд', len(after) == 1, str(len(after)))
masters_after = stats.get_masters_report(*PERIOD)
check('начисления по удалённому наряду откатились',
      round(sum(m['salary'] for m in masters_after), 2)
      == round(second['salary_total'], 2),
      f"{sum(m['salary'] for m in masters_after)} vs {second['salary_total']}")

print('\n=== Выгрузка в файл ===')
path = export_rows('тест_отчёта',
                   ['Услуга', 'Количество', 'Выручка'],
                   [['Шиномонтаж', 2, 1900.0], ['Балансировка', 1, 450.0]],
                   'Период: проверка')
check('файл создан', os.path.exists(path), path)
check('файл не пустой', os.path.getsize(path) > 0)

with open(path, encoding='utf-8-sig') as handle:
    content = handle.read()
check('кириллица читается', 'Шиномонтаж' in content, content[:80])
check('разделитель — точка с запятой', ';' in content)
check('дробные с запятой для Excel', '1900,00' in content, content[:200])
check('заголовок периода записан', 'Период: проверка' in content)

os.remove(path)
db.close()
finish()
