"""
Дашборд: выручка, услуги, мастера, наряды, начисления за смену.

Главное, что здесь проверяется, — цифры считаются по тем же правилам,
что и отчёты в программе цеха: удалённые наряды не в счёт, возврат
вычитается из дня возврата, гарантия прибавляет машину, но не деньги.

И второе: кто что видит. Мастер, спросивший чужой наряд напрямую,
получает отказ, а не чужие деньги.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_dashboard_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-31'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-dashboard'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-key'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE

import logging
from datetime import datetime, date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Visit, VisitItem, SalaryAccrual, ShopEmployee,
                        ShopShift, QueueSnapshot)

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" +
          (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


def finish():
    print('-' * 60)
    if _failures:
        print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
        for item in _failures:
            print(f'  - {item}')
        sys.exit(1)
    print('Все проверки пройдены')
    sys.exit(0)


class CodeCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.code = None

    def emit(self, record):
        message = record.getMessage()
        if 'код' in message:
            self.code = message.strip().split()[-1]


catcher = CodeCatcher()
logging.getLogger('tire_server').addHandler(catcher)

MASTER_PHONE = '+7 916 000-11-22'
MANAGER_PHONE = '+7 916 222-33-44'
OWNER_PIN = '4831'
MASTER_PIN = '9274'
MANAGER_PIN = '5927'

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def at(day, hour=12, minute=0):
    return datetime.combine(day, datetime.min.time()).replace(
        hour=hour, minute=minute)


# ----------------------------------------------------------------------
# Данные: такие, какие присылает цех
# ----------------------------------------------------------------------

def seed():
    db = SessionLocal()

    db.add(ShopEmployee(shop_id=1, name='Игорь', salary_percent=40.0))
    db.add(ShopEmployee(shop_id=2, name='Пётр', salary_percent=50.0))

    db.add(ShopShift(shop_id=10, started_at=at(YESTERDAY, 9), status='closed',
                     ended_at=at(YESTERDAY, 21), open_posts=2,
                     total_salary=1000.0))
    db.add(ShopShift(shop_id=11, started_at=at(TODAY, 9), status='open',
                     open_posts=2, total_salary=0.0))
    db.flush()

    def order(shop_id, day, hour, plate, total, base, consumables, payment,
              shift, accruals, items, **extra):
        visit = Visit(shop_id=shop_id, visited_at=at(day, hour),
                      license_plate=plate, total_amount=total,
                      salary_base=base, consumables_amount=consumables,
                      payment_method=payment, shift_shop_id=shift,
                      changed_at=at(day, hour), **extra)
        db.add(visit)
        db.flush()
        for name, quantity, price, line_total in items:
            db.add(VisitItem(visit_id=visit.id, service_name=name,
                             quantity=quantity, unit_price=price,
                             total=line_total))
        for employee_id, amount in accruals:
            db.add(SalaryAccrual(visit_id=visit.id,
                                 employee_shop_id=employee_id, amount=amount,
                                 accrued_at=at(day, hour)))
        return visit

    # Вчера: два наряда, один на двоих
    order(101, YESTERDAY, 10, 'А111АА77', 1000.0, 1000.0, 0.0, 'cash', 10,
          [(1, 400.0)], [('Шиномонтаж', 4, 250.0, 1000.0)])
    order(102, YESTERDAY, 15, 'В222ВВ77', 2000.0, 1800.0, 200.0, 'card', 10,
          [(1, 360.0), (2, 450.0)],
          [('Шиномонтаж', 4, 250.0, 1000.0),
           ('Правка литого диска', 2, 500.0, 1000.0)])

    # Сегодня: наряд, гарантия и удалённый
    order(103, TODAY, 11, 'С333СС77', 3000.0, 3000.0, 0.0, 'cash', 11,
          [(2, 1500.0)], [('Сезонная смена', 4, 750.0, 3000.0)])
    order(104, TODAY, 12, 'Д444ДД77', 0.0, 0.0, 0.0, 'cash', 11,
          [], [('Гарантийный ремонт', 1, 0.0, 0.0)], is_warranty=True)
    order(105, TODAY, 13, 'Е555ЕЕ77', 9999.0, 9999.0, 0.0, 'cash', 11,
          [(1, 4000.0)], [('Ошибка приёмщика', 1, 9999.0, 9999.0)],
          is_deleted=True)

    # Возврат по вчерашнему наряду, оформленный сегодня
    db.query(Visit).filter(Visit.shop_id == 101).update(
        {'refunded_amount': 300.0, 'refunded_at': at(TODAY, 14),
         'refund_type': 'refund', 'refund_reason': 'Клиент вернул колесо'})

    db.add(QueueSnapshot(taken_at=at(TODAY, 14), cars_in_work=2,
                         cars_waiting=1, open_posts=2, shift_is_open=True))

    db.commit()
    db.close()


def enter(client, phone, pin):
    client.post('/staff/code', json={'phone': phone})
    token = client.post('/staff/verify',
                        json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = client.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


PERIOD = {'from': YESTERDAY.isoformat(), 'to': TODAY.isoformat()}

with TestClient(app) as client:
    seed()

    owner = enter(client, OWNER_PHONE, OWNER_PIN)

    client.post('/staff/people', headers=owner, json={
        'phone': MASTER_PHONE, 'name': 'Игорь', 'role': 'master',
        'employee_shop_id': 1})
    client.post('/staff/people', headers=owner, json={
        'phone': MANAGER_PHONE, 'name': 'Ольга', 'role': 'manager'})

    master = enter(client, MASTER_PHONE, MASTER_PIN)
    manager = enter(client, MANAGER_PHONE, MANAGER_PIN)

    print('=== Сводка за период ===')
    summary = client.get('/dashboard/summary', params=PERIOD,
                         headers=owner).json()

    # 1000 + 2000 + 3000 = 6000. Удалённый наряд на 9999 не в счёт
    check('выручка без удалённого наряда', summary['revenue'] == 6000.0,
          str(summary['revenue']))
    check('возврат учтён отдельно', summary['refunded'] == 300.0,
          str(summary['refunded']))
    check('чистая выручка за вычетом возврата',
          summary['net_revenue'] == 5700.0, str(summary['net_revenue']))
    check('машин — четыре, включая гарантийную', summary['cars'] == 4,
          str(summary['cars']))
    check('гарантийная посчитана отдельно', summary['warranty_cars'] == 1,
          str(summary['warranty_cars']))
    check('средний чек без гарантийной машины',
          summary['average_check'] == 2000.0, str(summary['average_check']))
    check('наличные', summary['cash'] == 4000.0, str(summary['cash']))
    check('карта', summary['card'] == 2000.0, str(summary['card']))
    check('расходники', summary['consumables'] == 200.0,
          str(summary['consumables']))
    # 400 + 360 + 450 + 1500, начисление по удалённому не считается
    check('зарплата без удалённого наряда', summary['salary'] == 2710.0,
          str(summary['salary']))
    check('осталось цеху = 5700 - 2710 - 200',
          summary['left'] == 2790.0, str(summary['left']))

    print('\n=== Выручка по дням ===')
    days = {row['day']: row for row in summary['by_day']}
    check('вчера 3000', days[YESTERDAY.isoformat()]['revenue'] == 3000.0,
          str(days[YESTERDAY.isoformat()]))
    check('возврат вычтен из сегодня, а не из вчера',
          days[TODAY.isoformat()]['revenue'] == 2700.0,
          str(days[TODAY.isoformat()]))

    print('\n=== Услуги ===')
    services = client.get('/dashboard/services', params=PERIOD,
                          headers=owner).json()
    names = [row['service_name'] for row in services]
    check('удалённый наряд не принёс услуг', 'Ошибка приёмщика' not in names,
          str(names))
    check('первой идёт самая денежная', names[0] == 'Сезонная смена',
          str(names))
    check('шиномонтаж сложен по двум нарядам',
          [row for row in services
           if row['service_name'] == 'Шиномонтаж'][0]['amount'] == 2000.0,
          str(services))
    check('доля посчитана', abs(sum(row['share'] for row in services) - 100) < 1,
          str([row['share'] for row in services]))

    print('\n=== Мастера ===')
    masters = client.get('/dashboard/masters', params=PERIOD,
                         headers=owner).json()
    by_id = {row['employee_shop_id']: row for row in masters}
    check('Пётр заработал больше', masters[0]['employee_shop_id'] == 2,
          str(masters[0]))
    check('имя показано', by_id[1]['title'] == 'Игорь (№1)', by_id[1]['title'])
    check('у Игоря два наряда', by_id[1]['orders'] == 2, str(by_id[1]))
    check('начислено Игорю 760', by_id[1]['salary'] == 760.0,
          str(by_id[1]['salary']))
    check('начислено Петру 1950', by_id[2]['salary'] == 1950.0,
          str(by_id[2]['salary']))

    print('\n=== Наряды ===')
    orders = client.get('/dashboard/orders', params=PERIOD, headers=owner).json()
    ids = [row['shop_id'] for row in orders]
    check('удалённого наряда в списке нет', 105 not in ids, str(ids))
    check('остальные на месте', set(ids) == {101, 102, 103, 104}, str(ids))
    check('свежие сверху', ids[0] == 104 or ids[0] == 103, str(ids))

    only_card = client.get('/dashboard/orders',
                           params=dict(PERIOD, payment_method='card'),
                           headers=owner).json()
    check('фильтр по оплате картой', [row['shop_id'] for row in only_card] == [102],
          str([row['shop_id'] for row in only_card]))

    by_master = client.get('/dashboard/orders',
                           params=dict(PERIOD, employee_shop_id=2),
                           headers=owner).json()
    check('фильтр по мастеру',
          set(row['shop_id'] for row in by_master) == {102, 103},
          str([row['shop_id'] for row in by_master]))

    print('\n=== Карточка наряда ===')
    card = client.get('/dashboard/orders/102', headers=owner).json()
    check('позиции на месте', len(card['items']) == 2, str(len(card['items'])))
    check('расходники видны', card['consumables_amount'] == 200.0,
          str(card['consumables_amount']))
    check('база для зарплаты видна', card['salary_base'] == 1800.0,
          str(card['salary_base']))
    check('начисления обоим мастерам', len(card['accruals']) == 2,
          str(card['accruals']))
    check('в начислении имя мастера',
          any(row['title'] == 'Пётр (№2)' for row in card['accruals']),
          str(card['accruals']))

    check('возврат виден в карточке',
          client.get('/dashboard/orders/101',
                     headers=owner).json()['refunded_amount'] == 300.0)
    # В отчётах его нет, но карточка открывается: по таким нарядам и
    # разбирают, почему выручка меньше, чем помнилось
    deleted = client.get('/dashboard/orders/105', headers=owner)
    check('удалённый наряд открывается для разбора',
          deleted.status_code == 200, str(deleted.status_code))
    check('и помечен как удалённый', deleted.json()['is_deleted'] is True)

    print('\n=== Начисления за смену ===')
    salary = client.get('/dashboard/shifts/10/salary', headers=owner).json()
    check('смена закрыта — сумма окончательная', salary['is_final'] is True,
          str(salary['is_final']))
    check('в смене два сотрудника', len(salary['employees']) == 2,
          str(len(salary['employees'])))

    igor = [row for row in salary['employees']
            if row['employee_shop_id'] == 1][0]
    check('у Игоря два наряда в смене', len(igor['orders']) == 2,
          str(igor['orders']))
    check('в строке номер наряда и машина',
          igor['orders'][0]['order_id'] == 101
          and igor['orders'][0]['license_plate'] == 'А111АА77',
          str(igor['orders'][0]))
    check('итог сходится со строками',
          igor['salary'] == sum(row['amount'] for row in igor['orders']),
          str(igor['salary']))

    open_shift = client.get('/dashboard/shifts/11/salary', headers=owner).json()
    check('открытая смена помечена как незавершённая',
          open_shift['is_final'] is False)
    check('удалённый наряд не попал в начисления смены',
          all(105 not in [row['order_id'] for row in person['orders']]
              for person in open_shift['employees']),
          str(open_shift['employees']))

    print('\n=== Текущая смена и очередь ===')
    now = client.get('/dashboard/shifts/current', headers=owner).json()
    check('открытая смена найдена', now['shift']['shop_id'] == 11, str(now))
    check('очередь с отметкой времени', now['queue']['taken_at'] is not None,
          str(now['queue']))
    check('в работе две машины', now['queue']['cars_in_work'] == 2)

    print('\n=== Мастер видит только своё ===')
    mine = client.get('/dashboard/orders', params=PERIOD, headers=master).json()
    check('только наряды Игоря',
          set(row['shop_id'] for row in mine) == {101, 102},
          str([row['shop_id'] for row in mine]))

    sneaky = client.get('/dashboard/orders',
                        params=dict(PERIOD, employee_shop_id=2),
                        headers=master).json()
    check('подменить мастера в запросе не выйдет',
          set(row['shop_id'] for row in sneaky) == {101, 102},
          str([row['shop_id'] for row in sneaky]))

    check('чужой наряд не открыть',
          client.get('/dashboard/orders/103', headers=master).status_code == 404)

    own_card = client.get('/dashboard/orders/102', headers=master).json()
    check('в своём наряде видно только своё начисление',
          len(own_card['accruals']) == 1
          and own_card['accruals'][0]['employee_shop_id'] == 1,
          str(own_card['accruals']))

    own_shift = client.get('/dashboard/shifts/10/salary', headers=master).json()
    check('в смене мастер видит только себя',
          [row['employee_shop_id'] for row in own_shift['employees']] == [1],
          str(own_shift['employees']))

    check('выручка мастеру закрыта',
          client.get('/dashboard/summary', params=PERIOD,
                     headers=master).status_code == 403)
    check('чужие зарплаты закрыты',
          client.get('/dashboard/masters', params=PERIOD,
                     headers=master).status_code == 403)

    print('\n=== Управляющий без права на зарплаты ===')
    check('выручку видит',
          client.get('/dashboard/summary', params=PERIOD,
                     headers=manager).status_code == 200)
    check('наряды видит',
          client.get('/dashboard/orders', params=PERIOD,
                     headers=manager).status_code == 200)
    check('зарплаты закрыты',
          client.get('/dashboard/masters', params=PERIOD,
                     headers=manager).status_code == 403)
    check('начисления за смену тоже закрыты',
          client.get('/dashboard/shifts/10/salary',
                     headers=manager).status_code == 403)

    print('\n=== Период по умолчанию и перевёрнутые даты ===')
    default = client.get('/dashboard/summary', headers=owner).json()
    check('по умолчанию последние 30 дней',
          (date.fromisoformat(default['to'])
           - date.fromisoformat(default['from'])).days == 29,
          f"{default['from']} — {default['to']}")

    flipped = client.get('/dashboard/summary',
                         params={'from': TODAY.isoformat(),
                                 'to': YESTERDAY.isoformat()},
                         headers=owner).json()
    check('перевёрнутые даты поменялись местами',
          flipped['revenue'] == 6000.0, str(flipped['revenue']))

    print('\n=== Мастер без номера сотрудника ===')
    db = SessionLocal()
    from app.models import StaffUser
    db.query(StaffUser).filter(StaffUser.phone == '79160001122').update(
        {'employee_shop_id': None})
    db.commit()
    db.close()

    master = enter(client, MASTER_PHONE, MASTER_PIN)
    lost = client.get('/dashboard/orders', params=PERIOD, headers=master)
    check('сказано, что номер не привязан', lost.status_code == 409,
          str(lost.status_code))
    check('объяснено, к кому идти',
          'владельц' in lost.json()['detail'].lower(), lost.json()['detail'])

finish()
