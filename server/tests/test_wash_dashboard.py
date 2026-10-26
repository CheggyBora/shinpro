"""
Мойка на дашборде: переключатель «Шиномонтаж | Мойка» (docs/wash_dashboard.md).

  · обмен принимает направление наряда, позиции и начисления, мойщика
    и класс машины; непонятное направление — шиномонтаж; старая
    программа, которая этого не шлёт, — всё шиномонтаж;
  · смешанный наряд делится по строкам: позиции мойки — выручка мойки,
    остальные — шиномонтажа; наряд считается в обоих направлениях;
  · наряд без позиций — по своему полю directions;
  · возврат и расходники делятся в доле направления;
  · зарплата — начисления этого направления; откат при возврате тоже;
  · без направления (и с непонятным) — ровно прежние цифры, и
    шиномонтаж плюс мойка дают общую;
  · список нарядов, карточка, смены и начисления за смену — по
    направлению; карточка показывает, кто мыл.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_wash_dashboard_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-51'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-wash-dashboard'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-wash-dashboard'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging
from datetime import date, datetime

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Visit, VisitItem, SalaryAccrual

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

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
TODAY = date.today()
PERIOD = {'from': TODAY.isoformat(), 'to': TODAY.isoformat()}


def at(hour, minute=0):
    return datetime.combine(TODAY, datetime.min.time()).replace(
        hour=hour, minute=minute).isoformat()


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify',
                      json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def line(name, total, direction=None, employee=None, consumable=0.0, **extra):
    row = {'service_name': name, 'quantity': 1, 'unit_price': total,
           'total': total, 'consumable_cost': consumable}
    if direction is not None:
        row['direction'] = direction
    if employee is not None:
        row['employee_local_id'] = employee
    row.update(extra)
    return row


def accrual(employee, amount, direction=None, hour=12):
    row = {'employee_local_id': employee, 'amount': amount,
           'accrued_at': at(hour)}
    if direction is not None:
        row['direction'] = direction
    return row


def visit(local_id, hour, total, items, accruals, payment='cash', **extra):
    row = {'local_id': local_id, 'visited_at': at(hour),
           'license_plate': f'А{local_id}АА77', 'total_amount': total,
           'payment_method': payment, 'shift_local_id': 20,
           'salary_base': total, 'items': items, 'accruals': accruals}
    row.update(extra)
    return row


VISITS = [
    # Смешанный: шиномонтаж 2000 и мойка 1000. Игорю начислено и за то,
    # и за другое — двумя строками с одним временем; Алина мыла.
    # Вечером вернули 600 — и откатили Игорю 80 тоже двумя строками
    visit(201, 10, 3000.0,
          [line('Шиномонтаж', 2000.0, 'tire', consumable=100.0),
           line('Мойка кузова', 1000.0, 'wash', employee=3, consumable=50.0)],
          [accrual(1, 700.0, 'tire', 10), accrual(1, 100.0, 'wash', 10),
           accrual(3, 300.0, 'wash', 10),
           accrual(1, -70.0, 'tire', 18), accrual(1, -10.0, 'wash', 18)],
          payment='card', directions='tire,wash', wash_class='crossover',
          consumables_amount=150.0, salary_base=2850.0,
          refunded_amount=600.0, refunded_at=at(18), refund_type='refund'),
    # Только мойка
    visit(202, 11, 1500.0,
          [line('Комплексная мойка', 1500.0, 'wash', employee=3)],
          [accrual(3, 450.0, 'wash', 11)],
          directions='wash', wash_class='sedan'),
    # Только шиномонтаж
    visit(203, 12, 4000.0, [line('Сезонная смена', 4000.0, 'tire')],
          [accrual(1, 1600.0, 'tire', 12)], directions='tire'),
    # Старая программа цеха: ни направлений, ни мойщика
    visit(204, 13, 800.0, [line('Балансировка', 800.0)],
          [accrual(1, 320.0, hour=13)]),
    # Мойка без позиций: делить не по чему — по полю наряда
    visit(206, 14, 500.0, [], [], directions='wash'),
    # Мусор в направлениях — шиномонтаж, а не отказ принять оплаченное
    visit(207, 15, 600.0, [line('Ремонт прокола', 600.0, 'мойка')], [],
          directions='junk', wash_class='танк'),
]


def get(http, path, headers, **params):
    answer = http.get(path, headers=headers, params=dict(PERIOD, **params))
    assert answer.status_code == 200, (path, params, answer.text)
    return answer.json()


with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4851')

    print('=== Обмен: направления доезжают до базы ===')
    pushed = http.post('/sync/push', headers=KEY, json={
        'employees': [{'local_id': 1, 'name': 'Игорь'},
                      {'local_id': 3, 'name': 'Алина'}],
        'shifts': [{'local_id': 20, 'started_at': at(8), 'status': 'closed',
                    'ended_at': at(21), 'open_posts': 2,
                    'total_salary': 3390.0}],
        'visits': VISITS,
    })
    check('обмен принят', pushed.status_code == 200, pushed.text[:200])

    db = SessionLocal()
    rows = {row.local_id: row for row in db.query(Visit).all()}
    check('смешанный наряд помнит оба направления',
          rows[201].directions == 'tire,wash', rows[201].directions)
    check('класс машины сохранён', rows[201].wash_class == 'crossover',
          str(rows[201].wash_class))
    lines = {item.service_name: item for item in rows[201].items}
    check('у позиции мойки направление и мойщик',
          lines['Мойка кузова'].direction == 'wash'
          and lines['Мойка кузова'].employee_local_id == 3,
          f"{lines['Мойка кузова'].direction} {lines['Мойка кузова'].employee_local_id}")
    check('у позиции шиномонтажа мойщика нет',
          lines['Шиномонтаж'].direction == 'tire'
          and lines['Шиномонтаж'].employee_local_id is None)
    check('начисления пришли с направлением',
          sorted((row.employee_local_id, row.direction, row.amount)
                 for row in rows[201].accruals)
          == [(1, 'tire', -70.0), (1, 'tire', 700.0), (1, 'wash', -10.0),
              (1, 'wash', 100.0), (3, 'wash', 300.0)],
          str([(row.employee_local_id, row.direction, row.amount)
               for row in rows[201].accruals]))
    check('старая программа — наряд шиномонтажа',
          rows[204].directions == 'tire' and rows[204].wash_class is None,
          str(rows[204].directions))
    check('старая программа — позиция и начисление шиномонтажа',
          [item.direction for item in rows[204].items] == ['tire']
          and [row.direction for row in rows[204].accruals] == ['tire'])
    check('мусорное направление наряда — шиномонтаж',
          rows[207].directions == 'tire', rows[207].directions)
    check('мусорное направление позиции — шиномонтаж',
          [item.direction for item in rows[207].items] == ['tire'])
    check('непонятный класс машины не сохраняется',
          rows[207].wash_class is None, str(rows[207].wash_class))
    db.close()

    print('\n=== Сводка: без направления — прежние цифры ===')
    whole = get(http, '/dashboard/summary', owner)
    # 3000 + 1500 + 4000 + 800 + 500 + 600 — суммы нарядов, как раньше
    check('выручка — суммы нарядов', whole['revenue'] == 10400.0,
          str(whole['revenue']))
    check('возврат целиком', whole['refunded'] == 600.0, str(whole['refunded']))
    check('машин шесть', whole['cars'] == 6, str(whole['cars']))
    check('зарплата — все начисления с откатом',
          whole['salary'] == 3390.0, str(whole['salary']))
    check('расходники наряда', whole['consumables'] == 150.0,
          str(whole['consumables']))
    check('направление в ответе — всё', whole['direction'] == 'all')

    same = [get(http, '/dashboard/summary', owner, direction=value)
            for value in ('all', '', 'юла')]
    for value, answer in zip(('all', 'пусто', 'мусор'), same):
        answer.pop('direction', None)
        reference = dict(whole)
        reference.pop('direction', None)
        check(f'direction={value} — те же цифры', answer == reference)

    print('\n=== Сводка мойки ===')
    wash = get(http, '/dashboard/summary', owner, direction='wash')
    # 1000 строкой смешанного + 1500 + 500 наряда без позиций
    check('выручка мойки по строкам', wash['revenue'] == 3000.0,
          str(wash['revenue']))
    # Возврат 600 по наряду, где мойка — треть: 200
    check('возврат в доле мойки', wash['refunded'] == 200.0,
          str(wash['refunded']))
    check('чистая выручка мойки', wash['net_revenue'] == 2800.0,
          str(wash['net_revenue']))
    check('машин мойки три — со смешанной', wash['cars'] == 3, str(wash['cars']))
    check('карта мойки — строка смешанного', wash['card'] == 1000.0,
          str(wash['card']))
    check('наличные мойки', wash['cash'] == 2000.0, str(wash['cash']))
    # 150 расходников делятся как 100 : 50 по себестоимости позиций
    check('расходники мойки в доле материалов', wash['consumables'] == 50.0,
          str(wash['consumables']))
    # 100 + 300 + 450 − 10 отката
    check('зарплата мойки — её начисления', wash['salary'] == 840.0,
          str(wash['salary']))
    check('средний чек мойки', wash['average_check'] == 1000.0,
          str(wash['average_check']))
    check('осталось мойке = 2800 − 840 − 50', wash['left'] == 1910.0,
          str(wash['left']))
    day = wash['by_day'][-1]
    check('по дням: мойка за вычетом своей доли возврата',
          day['revenue'] == 2800.0 and day['cars'] == 3, str(day))
    check('направление в ответе — мойка', wash['direction'] == 'wash')

    print('\n=== Сводка шиномонтажа ===')
    tire = get(http, '/dashboard/summary', owner, direction='tire')
    check('выручка шиномонтажа', tire['revenue'] == 7400.0, str(tire['revenue']))
    check('возврат в доле шиномонтажа', tire['refunded'] == 400.0,
          str(tire['refunded']))
    check('машин шиномонтажа четыре — со смешанной и старой',
          tire['cars'] == 4, str(tire['cars']))
    check('зарплата шиномонтажа', tire['salary'] == 2550.0, str(tire['salary']))
    check('расходники шиномонтажа', tire['consumables'] == 100.0,
          str(tire['consumables']))

    for field in ('revenue', 'refunded', 'net_revenue', 'cash', 'card',
                  'consumables', 'salary', 'left'):
        check(f'шиномонтаж + мойка = всё: {field}',
              abs(tire[field] + wash[field] - whole[field]) < 0.01,
              f'{tire[field]} + {wash[field]} против {whole[field]}')

    print('\n=== Услуги и продажи ===')
    names = {row['service_name'] for row in get(
        http, '/dashboard/services', owner, direction='wash')}
    check('в услугах мойки только мойка',
          names == {'Мойка кузова', 'Комплексная мойка'}, str(names))
    names = {row['service_name'] for row in get(
        http, '/dashboard/services', owner, direction='tire')}
    check('в услугах шиномонтажа нет мойки',
          names == {'Шиномонтаж', 'Сезонная смена', 'Балансировка',
                    'Ремонт прокола'}, str(names))
    names = {row['service_name'] for row in get(
        http, '/dashboard/services', owner)}
    check('без направления — все услуги', len(names) == 6, str(names))
    sales = get(http, '/dashboard/sales', owner, direction='wash')
    check('продажи мойки — её строки', sales['total_amount'] == 2500.0,
          str(sales['total_amount']))

    print('\n=== Мастера ===')
    masters = {row['employee_local_id']: row
               for row in get(http, '/dashboard/masters', owner)}
    check('без направления Игорю — всё', masters[1]['salary'] == 2640.0,
          str(masters[1]['salary']))
    # Строк начислений у Игоря в смешанном наряде четыре, наряд — один
    check('наряды мастера — разные наряды, а не строки начислений',
          masters[1]['orders'] == 3, str(masters[1]))
    check('выработка Игоря — суммы его нарядов',
          masters[1]['revenue'] == 7800.0, str(masters[1]['revenue']))

    masters = {row['employee_local_id']: row
               for row in get(http, '/dashboard/masters', owner,
                              direction='wash')}
    check('мойка: Алине 750 за два наряда',
          masters[3]['salary'] == 750.0 and masters[3]['orders'] == 2,
          str(masters[3]))
    check('мойка: выработка Алины — строки мойки',
          masters[3]['revenue'] == 2500.0, str(masters[3]['revenue']))
    check('мойка: Игорю его часть за мойку', masters[1]['salary'] == 90.0
          and masters[1]['orders'] == 1, str(masters[1]))

    masters = {row['employee_local_id']: row
               for row in get(http, '/dashboard/masters', owner,
                              direction='tire')}
    check('шиномонтаж: Алины нет', 3 not in masters, str(list(masters)))
    check('шиномонтаж: Игорю 2550', masters[1]['salary'] == 2550.0,
          str(masters[1]['salary']))
    # 2850 базы смешанного в доле шиномонтажа (2/3) + 4000 + 800
    check('шиномонтаж: база в доле направления',
          masters[1]['salary_base'] == 6700.0, str(masters[1]['salary_base']))

    print('\n=== Наряды ===')
    orders = get(http, '/dashboard/orders', owner, direction='wash')
    ids = {row['local_id'] for row in orders}
    check('наряды мойки', ids == {201, 202, 206}, str(ids))
    mixed = next(row for row in orders if row['local_id'] == 201)
    check('у смешанного — метка обоих направлений',
          mixed['directions'] == ['tire', 'wash'], str(mixed['directions']))
    check('сумма мойки в смешанном наряде', mixed['direction_amount'] == 1000.0
          and mixed['total_amount'] == 3000.0, str(mixed))
    check('мастера мойки в строке наряда, без повторов',
          mixed['masters'] == ['Игорь (№1)', 'Алина (№3)'], str(mixed['masters']))

    ids = {row['local_id'] for row in get(
        http, '/dashboard/orders', owner, direction='tire')}
    check('наряды шиномонтажа', ids == {201, 203, 204, 207}, str(ids))

    plain = get(http, '/dashboard/orders', owner)
    check('без направления — все наряды и без суммы направления',
          len(plain) == 6 and all('direction_amount' not in row for row in plain),
          str(len(plain)))
    check('метка у наряда без позиций — по его полю',
          next(row for row in plain if row['local_id'] == 206)['directions']
          == ['wash'])
    mixed = next(row for row in plain if row['local_id'] == 201)
    check('имя мастера в списке одно, хоть строк у него четыре',
          mixed['masters'] == ['Игорь (№1)', 'Алина (№3)'], str(mixed['masters']))

    by_master = [row['local_id'] for row in get(
        http, '/dashboard/orders', owner, employee_local_id=1)]
    check('наряды мастера не двоятся', sorted(by_master) == [201, 203, 204],
          str(by_master))
    by_master = {row['local_id'] for row in get(
        http, '/dashboard/orders', owner, employee_local_id=3,
        direction='wash')}
    check('наряды мойщицы на мойке', by_master == {201, 202}, str(by_master))

    print('\n=== Карточка наряда ===')
    card = http.get('/dashboard/orders/201', headers=owner).json()
    items = {row['service_name']: row for row in card['items']}
    check('у строки направление', items['Мойка кузова']['direction'] == 'wash'
          and items['Шиномонтаж']['direction'] == 'tire')
    check('у строки мойки — кто мыл',
          items['Мойка кузова']['employee_title'] == 'Алина (№3)',
          str(items['Мойка кузова']))
    check('у строки шиномонтажа мойщика нет',
          items['Шиномонтаж']['employee_title'] is None)
    check('у начисления направление',
          {row['direction'] for row in card['accruals']} == {'tire', 'wash'})
    check('класс машины в карточке', card['wash_class'] == 'crossover')

    print('\n=== Смены ===')
    shifts = {row['local_id']: row for row in get(http, '/dashboard/shifts', owner)}
    check('без направления — итог из цеха', shifts[20]['total_salary'] == 3390.0,
          str(shifts[20]))
    shifts = {row['local_id']: row for row in get(
        http, '/dashboard/shifts', owner, direction='wash')}
    check('мойка — её начисления в смене', shifts[20]['total_salary'] == 840.0,
          str(shifts[20]))
    shifts = {row['local_id']: row for row in get(
        http, '/dashboard/shifts', owner, direction='tire')}
    check('шиномонтаж — его начисления в смене',
          shifts[20]['total_salary'] == 2550.0, str(shifts[20]))

    salary = http.get('/dashboard/shifts/20/salary', headers=owner).json()
    igor = next(row for row in salary['employees']
                if row['employee_local_id'] == 1)
    # Части одного начисления — одна строка; откат — своя
    check('части начисления сложены в одну строку наряда',
          [(row['order_id'], row['amount']) for row in igor['orders']]
          == [(201, 800.0), (201, -80.0), (203, 1600.0), (204, 320.0)],
          str(igor['orders']))
    check('итог смены без направления', salary['total'] == 3390.0,
          str(salary['total']))

    salary = http.get('/dashboard/shifts/20/salary', headers=owner,
                      params={'direction': 'wash'}).json()
    people = {row['employee_local_id']: row for row in salary['employees']}
    check('мойка: в смене Алина и Игорь', set(people) == {1, 3}, str(list(people)))
    check('мойка: итог смены', salary['total'] == 840.0, str(salary['total']))
    check('мойка: у Игоря строка мойки и её откат',
          [(row['order_id'], row['amount']) for row in people[1]['orders']]
          == [(201, 100.0), (201, -10.0)], str(people[1]['orders']))

    print('\n=== Остатки зарплаты не делятся ===')
    balances = http.get('/dashboard/salary', headers=owner,
                        params={'direction': 'wash'}).json()
    people = {row['employee_local_id']: row for row in balances['people']}
    check('остаток Игоря — одной суммой', people[1]['accrued'] == 2640.0,
          str(people[1]))

finish()
