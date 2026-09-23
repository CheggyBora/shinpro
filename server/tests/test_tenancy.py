"""
Два шиномонтажа на одном сервере не видят друг друга.

Это условие, при котором программу вообще можно продать второму
заказчику. Не настройка видимости, не фильтр в интерфейсе, а свойство
самих запросов: чужие данные не приходят, даже если попросить их
напрямую — подставив чужой номер, чужой ключ или чужое имя точки.

Проверяем три границы:

    аккаунт   клиенты, персонал, коды входа
    точка     записи, наряды, зарплаты, настройки, хранение
    номер     мастер №1 в одной точке и мастер №1 в другой — разные люди
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_tenancy_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-tenancy'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

import logging
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Account, Shop, Client, Visit, ShopEmployee, ShopShift,
                        SalaryAccrual, Appointment, StaffUser)
from app.services import tenancy, shop_settings
from app.utils import now as shop_now

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

PHONE = '+7 909 901-89-31'      # один и тот же человек у обоих заказчиков
NORMALIZED = '79099018931'


def at(hour):
    return shop_now().replace(hour=hour, minute=0, second=0, microsecond=0)


with TestClient(app) as client:
    print('=== Два заказчика, у одного — две точки ===')
    db = SessionLocal()

    first, north, north_key = tenancy.create_account(
        db, 'Шиномонтаж «РИФ»', 'РИФ на Северной')
    south, south_key = tenancy.add_shop(db, first, 'РИФ на Южной')

    second, alien, alien_key = tenancy.create_account(db, 'Колесо', 'Колесо')

    check('аккаунтов двое', db.query(Account).count() == 2)
    check('точек трое', db.query(Shop).count() == 3)
    check('имена для ссылок переведены в латиницу',
          north.slug.startswith('rif') or 'rif' in north.slug, north.slug)
    check('ключи разные', north_key != south_key != alien_key)
    check('ключ лежит отпечатком, а не строкой',
          north.sync_key_hash != north_key and len(north.sync_key_hash) == 64)

    north_id, south_id, alien_id = north.id, south.id, alien.id
    north_slug, alien_slug = north.slug, alien.slug
    first_id, second_id = first.id, second.id
    first_slug, second_slug = first.slug, second.slug
    db.close()

    print('\n=== Обмен: ключ решает, чьи это данные ===')
    def push(key, payload):
        return client.post('/sync/push', json=payload, headers={'X-Sync-Key': key})

    answer = push(north_key, {
        'clients': [{'local_id': 1, 'phone': PHONE, 'name': 'Андрей'}],
        'employees': [{'local_id': 1, 'name': 'Игорь', 'salary_percent': 40.0}],
        'visits': [{'local_id': 100, 'client_local_id': 1,
                    'license_plate': 'А111АА77',
                    'visited_at': at(10).isoformat(), 'total_amount': 5000.0,
                    'accruals': [{'employee_local_id': 1, 'amount': 2000.0}],
                    'items': [{'service_name': 'Шиномонтаж', 'quantity': 4,
                               'unit_price': 1250.0, 'total': 5000.0}]}],
        'settings': {'shop_name': 'РИФ на Северной'},
    })
    check('северная точка отдала свои данные', answer.status_code == 200,
          str(answer.json()))

    answer = push(alien_key, {
        'clients': [{'local_id': 1, 'phone': PHONE, 'name': 'Андрей'}],
        'employees': [{'local_id': 1, 'name': 'Чужой мастер',
                       'salary_percent': 50.0}],
        'visits': [{'local_id': 100, 'client_local_id': 1,
                    'license_plate': 'В222ВВ77',
                    'visited_at': at(11).isoformat(), 'total_amount': 9000.0,
                    'accruals': [{'employee_local_id': 1, 'amount': 4500.0}],
                    'items': [{'service_name': 'Чужая услуга', 'quantity': 1,
                               'unit_price': 9000.0, 'total': 9000.0}]}],
        'settings': {'shop_name': 'Колесо'},
    })
    check('чужой шиномонтаж отдал свои', answer.status_code == 200)

    check('без ключа не пускает',
          client.post('/sync/push', json={}).status_code in (401, 503))
    check('выдуманный ключ не пускает',
          push('samo-pridumal', {}).status_code == 401)

    db = SessionLocal()
    print('\n=== Одинаковые номера — разные строки ===')
    visits = db.query(Visit).filter(Visit.local_id == 100).all()
    check('наряд №100 есть у обоих', len(visits) == 2, str(len(visits)))
    check('и они привязаны к разным точкам',
          {row.shop_id for row in visits} == {north_id, alien_id},
          str([row.shop_id for row in visits]))
    check('суммы не перепутаны',
          {row.total_amount for row in visits} == {5000.0, 9000.0})

    clients = db.query(Client).filter(Client.phone == NORMALIZED).all()
    check('один телефон — два разных клиента', len(clients) == 2,
          str(len(clients)))
    check('каждый в своём аккаунте',
          {row.account_id for row in clients} == {first_id, second_id})

    print('\n=== Настройки у каждой точки свои ===')
    check('у северной своё название',
          shop_settings.get(db, 'shop_name',
                            shop=db.query(Shop).get(north_id)) == 'РИФ на Северной')
    check('у чужой — своё',
          shop_settings.get(db, 'shop_name',
                            shop=db.query(Shop).get(alien_id)) == 'Колесо')
    check('у южной, которой ничего не слали, — значение по умолчанию',
          shop_settings.get(db, 'shop_name',
                            shop=db.query(Shop).get(south_id)) == 'Шиномонтаж')
    db.close()

    print('\n=== Цех видит в обмене только свои данные ===')
    state = client.get('/sync/state', headers={'X-Sync-Key': north_key}).json()
    check('северная видит один наряд', state['visits'] == 1, str(state))
    check('и одного клиента', state['clients'] == 1, str(state))
    check('и знает, как её зовут', state['shop']['id'] == north_id, str(state))

    state = client.get('/sync/state', headers={'X-Sync-Key': south_key}).json()
    check('южная не видит нарядов соседки', state['visits'] == 0, str(state))
    check('но клиентов сети видит', state['clients'] == 1, str(state))

    state = client.get('/sync/state', headers={'X-Sync-Key': alien_key}).json()
    check('чужой шиномонтаж видит только своё', state['visits'] == 1,
          str(state))

    print('\n=== Записи чужой точки не тронуть ===')
    made = client.post('/sync/appointments', headers={'X-Sync-Key': north_key},
                       json={'scheduled_at': at(15).isoformat(),
                             'duration_minutes': 60,
                             'license_plate': 'А111АА77'}).json()
    check('запись создана', 'id' in made, str(made))

    stolen = client.patch(f"/sync/appointments/{made['id']}",
                          headers={'X-Sync-Key': alien_key},
                          json={'status': 'cancelled'})
    check('чужой ключ не отменяет запись', stolen.status_code == 404,
          str(stolen.status_code))

    db = SessionLocal()
    row = db.query(Appointment).get(made['id'])
    check('запись осталась в силе', row.status == 'scheduled', row.status)
    check('и принадлежит северной точке', row.shop_id == north_id)
    db.close()

    print('\n=== Дашборд: владелец видит свои точки и только их ===')
    def enter(phone, pin, account_slug):
        headers = {'X-Shop': account_slug}
        client.post('/staff/code', json={'phone': phone}, headers=headers)
        token = client.post('/staff/verify',
                            json={'phone': phone, 'code': catcher.code},
                            headers=headers).json()['token']
        given = client.post('/staff/pin', json={'pin': pin},
                            headers={'Authorization': f'Bearer {token}'})
        return {'Authorization': f"Bearer {given.json()['token']}"}

    db = SessionLocal()
    tenancy_owner = StaffUser(account_id=first_id, phone='79160001122',
                              name='Хозяин РИФ', role='owner')
    alien_owner = StaffUser(account_id=second_id, phone='79160003344',
                            name='Хозяин Колеса', role='owner')
    db.add(tenancy_owner)
    db.add(alien_owner)
    db.commit()
    db.close()

    ours = enter('+7 916 000-11-22', '4831', first_slug)
    theirs = enter('+7 916 000-33-44', '9274', second_slug)

    period = {'from': (shop_now() - timedelta(days=1)).date().isoformat(),
              'to': shop_now().date().isoformat()}

    mine = client.get('/dashboard/summary', params=period, headers=ours).json()
    check('владелец РИФ видит свои 5000', mine['revenue'] == 5000.0,
          str(mine['revenue']))

    alien_summary = client.get('/dashboard/summary', params=period,
                               headers=theirs).json()
    check('владелец Колеса видит свои 9000',
          alien_summary['revenue'] == 9000.0, str(alien_summary['revenue']))

    shops = client.get('/dashboard/shops', headers=ours).json()
    check('у РИФ две точки', len(shops) == 2, str(shops))
    check('чужой точки в списке нет',
          all(row['id'] != alien_id for row in shops), str(shops))

    by_shop = client.get('/dashboard/summary',
                         params=dict(period, shop=str(north_id)),
                         headers=ours).json()
    check('по северной точке — её выручка', by_shop['revenue'] == 5000.0,
          str(by_shop['revenue']))

    by_south = client.get('/dashboard/summary',
                          params=dict(period, shop=str(south_id)),
                          headers=ours).json()
    check('по южной — ноль, там ещё не работали', by_south['revenue'] == 0,
          str(by_south['revenue']))

    sneaky = client.get('/dashboard/summary',
                        params=dict(period, shop=str(alien_id)),
                        headers=ours)
    check('чужую точку подставить в запрос нельзя',
          sneaky.status_code == 404, str(sneaky.status_code))

    print('\n=== Мастер №1 у двоих — разные люди ===')
    masters = client.get('/dashboard/masters', params=period,
                         headers=ours).json()
    check('в списке один мастер', len(masters) == 1, str(masters))
    check('это наш Игорь', masters[0]['title'].startswith('Игорь'),
          str(masters[0]))
    check('с нашими деньгами', masters[0]['salary'] == 2000.0,
          str(masters[0]['salary']))

    alien_masters = client.get('/dashboard/masters', params=period,
                               headers=theirs).json()
    check('у соседа свой мастер №1',
          alien_masters[0]['title'].startswith('Чужой'), str(alien_masters[0]))
    check('и своя сумма', alien_masters[0]['salary'] == 4500.0,
          str(alien_masters[0]['salary']))

    print('\n=== Персонал: чужого сотрудника не увидеть и не тронуть ===')
    people = client.get('/staff/people', headers=ours).json()
    phones = [row['phone'] for row in people]
    check('видно только своих', len(people) == 1, str(phones))

    alien_staff_id = None
    db = SessionLocal()
    alien_staff_id = db.query(StaffUser).filter(
        StaffUser.account_id == second_id).first().id
    db.close()

    attempt = client.patch(f'/staff/people/{alien_staff_id}', headers=ours,
                           json={'is_active': False})
    check('чужую учётку не отключить', attempt.status_code == 400,
          str(attempt.status_code))

    db = SessionLocal()
    still = db.query(StaffUser).get(alien_staff_id)
    check('она осталась рабочей', still.is_active is True)
    db.close()

    print('\n=== Страница записи: по имени точки ===')
    info = client.get('/public/info', params={'shop': north_slug}).json()
    check('северная отдаёт своё название',
          info['shop_name'] == 'РИФ на Северной', str(info))

    info = client.get('/public/info', params={'shop': alien_slug}).json()
    check('чужая — своё', info['shop_name'] == 'Колесо', str(info))

    check('несуществующее имя — не найдено',
          client.get('/public/info',
                     params={'shop': 'takogo-net'}).status_code == 404)

    check('без имени точки, когда их несколько, тоже не найдено',
          client.get('/public/info').status_code == 404)

    check('страница открывается по адресу с именем',
          client.get(f'/z/{north_slug}').status_code == 200)
    check('логотип не путается с именем точки',
          client.get('/z/logo.jpg').status_code in (200, 404))

finish()
