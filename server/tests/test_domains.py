"""
У каждой организации свой адрес: по нему сервер понимает, чей кабинет.

Решение владельца 27.10.2026: программу продают другим организациям,
и у каждой свой сайт записи и свой дашборд. Сервер один, поэтому
главное здесь — адрес «Колеса» никогда не открывает данные «РИФа» и
наоборот, а вход в дашборд «РИФа» не ломается, когда на сервере
появляется вторая организация (до 27.10 ломался: без имени точки при
двух заказчиках сервер отказывал).

    lk.rif-test.ru / admin.rif-test.ru   -> тот, кто держит сервер
    koleso.rif-test.ru                   -> запись «Колеса»
    koleso-admin.rif-test.ru             -> дашборд «Колеса»
    zapis.koleso.ru                      -> свой домен «Колеса»
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_domains_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-domains'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_CORS_ORIGINS'] = 'https://lk.rif-test.ru,https://admin.rif-test.ru'
os.environ.pop('SERVER_PLATFORM_DOMAIN', None)
os.environ.pop('SERVER_HOME_HOSTS', None)

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import Account, AccountDomain
from app.models.account import ROLE_LK, ROLE_ADMIN, DOMAIN_ACTIVE
from app.services import tenancy
from app.services.staff_service import StaffService
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


PHONE = '+7 909 901-89-31'      # владелец и там, и там — один человек


def host(name):
    return {'Host': name}


with TestClient(app) as client:
    print('=== Домен сервера берётся из его же адресов ===')
    check('домашние адреса из SERVER_CORS_ORIGINS',
          settings.HOME_HOSTS == ['lk.rif-test.ru', 'admin.rif-test.ru'],
          str(settings.HOME_HOSTS))
    check('домен для организаций — rif-test.ru',
          settings.PLATFORM_DOMAIN == 'rif-test.ru', settings.PLATFORM_DOMAIN)

    db = SessionLocal()
    rif, rif_shop, _ = tenancy.create_account(db, 'Шиномонтаж «РИФ»', 'РИФ')
    koleso, koleso_shop, _ = tenancy.create_account(db, 'Колесо', 'Колесо на Ленина')
    for shop in (rif_shop, koleso_shop):
        shop.last_sync_at = shop_now()
    db.commit()

    owners = {}
    for account, pin in ((rif, '2580'), (koleso, '1470')):
        owner = StaffService(db, account.id).ensure_owner(PHONE, 'Владелец')
        StaffService(db, account.id).set_pin(owner, pin)
        owners[account.id] = owner.id

    rif_id, koleso_id = rif.id, koleso.id
    rif_slug, koleso_slug = rif_shop.slug, koleso_shop.slug
    check('у «Колеса» короткое имя koleso', koleso.slug == 'koleso', koleso.slug)

    print('\n=== Чей адрес ===')
    check('lk. — запись того, кто держит сервер',
          tenancy.host_target(db, 'lk.rif-test.ru') == (rif_id, ROLE_LK))
    check('admin. — его дашборд',
          tenancy.host_target(db, 'admin.rif-test.ru') == (rif_id, ROLE_ADMIN))
    check('koleso. — запись «Колеса»',
          tenancy.host_target(db, 'koleso.rif-test.ru') == (koleso_id, ROLE_LK))
    check('koleso-admin. — дашборд «Колеса»',
          tenancy.host_target(db, 'KOLESO-ADMIN.rif-test.ru:443') == (koleso_id, ROLE_ADMIN))
    check('неизвестное имя — ничьё',
          tenancy.host_target(db, 'nikto.rif-test.ru') == (None, None))
    check('чужой домен — ничей',
          tenancy.host_target(db, 'example.com') == (None, None))
    check('мусор вместо адреса — ничей',
          tenancy.host_target(db, 'a b<c>.ru') == (None, None))

    print('\n=== Вход в дашборд: две организации, один телефон ===')
    answer = client.post('/staff/login', json={'phone': PHONE, 'pin': '2580'},
                         headers=host('admin.rif-test.ru'))
    check('на admin. входит владелец «РИФа» — вторая организация не мешает',
          answer.status_code == 200, answer.text[:120])
    if answer.status_code == 200:
        check('и попадает к себе', answer.json()['staff']['id'] == owners[rif_id])

    answer = client.post('/staff/login', json={'phone': PHONE, 'pin': '2580'},
                         headers=host('koleso-admin.rif-test.ru'))
    check('ПИН «РИФа» в дашборд «Колеса» не пускает', answer.status_code == 401, answer.text)

    answer = client.post('/staff/login', json={'phone': PHONE, 'pin': '1470'},
                         headers=host('koleso-admin.rif-test.ru'))
    check('свой ПИН «Колеса» пускает — к себе',
          answer.status_code == 200 and answer.json()['staff']['id'] == owners[koleso_id],
          answer.text[:120])

    answer = client.post('/staff/login', json={'phone': PHONE, 'pin': '1470'})
    check('без адреса и без имени при двух организациях — отказ, а не угадывание',
          answer.status_code == 409, answer.text)

    print('\n=== Страница записи ===')
    info = client.get('/public/info', headers=host('koleso.rif-test.ru'))
    check('на адресе «Колеса» без имени точки — его точка',
          info.status_code == 200 and info.json()['shop'] == koleso_slug, info.text)

    info = client.get('/public/info', params={'shop': rif_slug},
                      headers=host('koleso.rif-test.ru'))
    check('точку «РИФа» на адресе «Колеса» не открыть', info.status_code == 404, info.text)

    info = client.get('/public/info', headers=host('lk.rif-test.ru'))
    check('на lk. — точка «РИФа»',
          info.status_code == 200 and info.json()['shop'] == rif_slug, info.text)

    shops = client.get('/public/shops', headers=host('koleso.rif-test.ru')).json()
    check('в выборе точек — только свои', [row['slug'] for row in shops] == [koleso_slug],
          str(shops))

    answer = client.post('/auth/start', json={'phone': PHONE},
                         headers={**host('koleso.rif-test.ru'), 'X-Shop': rif_slug})
    check('вход клиента с чужим именем точки на адресе «Колеса» — отказ',
          answer.status_code == 409, answer.text)

    print('\n=== Свой домен ===')
    koleso = db.get(Account, koleso_id)
    row = tenancy.add_domain(db, koleso, ' https://Zapis.Koleso.ru/z ')
    check('адрес приведён к виду zapis.koleso.ru', row.name == 'zapis.koleso.ru', row.name)
    check('ждёт запись у регистратора', row.status == 'waiting')
    check('по своему домену — «Колесо»',
          tenancy.host_target(db, 'zapis.koleso.ru') == (koleso_id, ROLE_LK))

    for bad, why in (('zapis koleso.ru', 'с пробелом'),
                     ('koleso', 'без зоны'),
                     ('zapis.koleso.ru;', 'с лишним знаком'),
                     ('x.rif-test.ru', 'наш домен'),
                     ('admin.rif-test.ru', 'домашний адрес'),
                     ('zapis.koleso.ru', 'повторно')):
        try:
            tenancy.add_domain(db, koleso, bad)
            check(f'не принимается: {why}', False)
        except tenancy.DomainError:
            check(f'не принимается: {why}', True)

    rif = db.get(Account, rif_id)
    try:
        tenancy.add_domain(db, rif, 'zapis.koleso.ru')
        check('чужой домен себе не забрать', False)
    except tenancy.DomainError as e:
        check('чужой домен себе не забрать', 'занят' in str(e), str(e))

    admin_row = tenancy.add_domain(db, koleso, 'admin.koleso.ru', role=ROLE_ADMIN)
    answer = client.post('/staff/login', json={'phone': PHONE, 'pin': '1470'},
                         headers=host('admin.koleso.ru'))
    check('дашборд «Колеса» на своём домене пускает', answer.status_code == 200, answer.text[:120])

    print('\n=== Что заводить в nginx и под что выпускать сертификаты ===')
    plan = tenancy.domains_plan(db)
    names = {name for name, _, _ in plan}
    check('поддомены «Колеса» есть',
          {'koleso.rif-test.ru', 'koleso-admin.rif-test.ru'} <= names, str(plan))
    check('свои домены «Колеса» есть', {'zapis.koleso.ru', 'admin.koleso.ru'} <= names)
    check('у «РИФа» поддоменов нет — у него lk. и admin.',
          not any(name.startswith('shinomontazh-rif') for name in names), str(names))
    check('свой домен помечен своим',
          ('zapis.koleso.ru', ROLE_LK, True) in plan)

    tenancy.set_domain_status(db, 'zapis.koleso.ru', DOMAIN_ACTIVE, 'Работает')
    db.refresh(row)
    check('статус записан', row.status == DOMAIN_ACTIVE and row.checked_at is not None)

    tenancy.remove_domain(db, koleso, admin_row.id)
    check('убранный домен больше ничей',
          tenancy.host_target(db, 'admin.koleso.ru') == (None, None))

    print('\n=== Имена, которые организация получить не может ===')
    taken = tenancy.taken_slugs(db)
    check('admin занято сервером', tenancy.make_slug('Admin', taken) != 'admin')
    check('lk занято сервером', tenancy.make_slug('LK', taken) != 'lk')
    check('«-admin» в конце — нельзя: это чужой дашборд',
          not tenancy.make_slug('Колесо admin', taken).endswith('-admin'),
          tenancy.make_slug('Колесо admin', taken))

    db.close()

finish()
