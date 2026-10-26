"""
Исправления по ревью 26.10.2026.

  · токен сотрудника не открывает кабинет клиента (подписан тем же ключом);
  · зарплату нельзя «перевести» в точку чужой сети;
  · аккаунт без работающих точек не видит ничего, а не всё;
  · клиент без телефона не отклоняет весь обмен;
  · у каждой точки сети свои номера строк: клиент №5 одной точки и №5
    другой — разные люди, и вторая точка не переписывает первую;
  · отменённая в цеху выдача зарплаты убирается с сервера.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_review_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-77-51'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-review'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-review'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Client, Car, Visit, Shop, SalaryPayout, StaffUser
from app.security import create_staff_token, create_token
from app.services import tenancy
from app.services.dashboard_service import DashboardService

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
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


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify', json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def visit(local_id, client_local_id, plate):
    return {'local_id': local_id, 'client_local_id': client_local_id, 'license_plate': plate,
            'visited_at': '2026-10-26T12:00:00', 'total_amount': 1000, 'services': 'Шиномонтаж'}


with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4832')
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_id = shop.id
    second, second_key = tenancy.add_shop(db, shop.account, 'РИФ на Южной')
    second_id = second.id
    _, stranger, stranger_key = tenancy.create_account(db, 'Чужой шиномонтаж')
    stranger_id = stranger.id
    db.close()
    SECOND = {'X-Sync-Key': second_key}
    STRANGER = {'X-Sync-Key': stranger_key}

    print('=== Клиент без телефона не ломает обмен ===')
    answer = http.post('/sync/push', headers=KEY, json={
        'clients': [{'local_id': 5, 'phone': '+7 916 000-00-05', 'name': 'Иван'},
                    {'local_id': 6, 'phone': None, 'name': 'Без телефона'}],
        'cars': [{'local_id': 5, 'license_plate': 'А123ВВ777', 'client_local_id': 5}],
        'visits': [visit(100, 5, 'А123ВВ777')]})
    check('обмен принят', answer.status_code == 200, answer.text[:200])

    print()
    print('=== Вторая точка сети: свои номера строк ===')
    answer = http.post('/sync/push', headers=SECOND, json={
        'clients': [{'local_id': 5, 'phone': '+7 916 000-00-77', 'name': 'Пётр'}],
        'cars': [{'local_id': 5, 'license_plate': 'К555КК77', 'client_local_id': 5}],
        'visits': [visit(100, 5, 'К555КК77')]})
    check('обмен второй точки принят', answer.status_code == 200, answer.text[:200])
    db = SessionLocal()
    ivan = db.query(Client).filter(Client.name == 'Иван').first()
    petr = db.query(Client).filter(Client.name == 'Пётр').first()
    check('первую точку не переписало: Иван на месте', ivan is not None and ivan.phone.endswith('0005'))
    check('Пётр — отдельный человек', petr is not None and petr.id != ivan.id)
    first_visit = db.query(Visit).filter(Visit.shop_id == shop_id, Visit.local_id == 100).first()
    second_visit = db.query(Visit).filter(Visit.shop_id == second_id, Visit.local_id == 100).first()
    check('наряды — каждый своему клиенту',
          first_visit.client_id == ivan.id and second_visit.client_id == petr.id)
    check('машины — своим владельцам',
          db.query(Car).filter(Car.license_plate == 'А123ВВ777').first().client_id == ivan.id
          and db.query(Car).filter(Car.license_plate == 'К555КК77').first().client_id == petr.id)
    db.close()

    print()
    print('=== Тот же человек во второй точке — один клиент ===')
    http.post('/sync/push', headers=SECOND, json={
        'clients': [{'local_id': 9, 'phone': '+7 916 000-00-05', 'name': 'Иван'}]})
    db = SessionLocal()
    check('по телефону — тот же Иван', db.query(Client).filter(
        Client.phone.like('%0005')).count() == 1)
    db.close()

    print()
    print('=== Токен сотрудника не открывает кабинет клиента ===')
    answer = http.get('/auth/me', headers=owner)
    check('токен дашборда в кабинете — отказ', answer.status_code == 401, answer.text[:200])
    db = SessionLocal()
    client_token = create_token(ivan.id)
    db.close()
    check('клиентский токен работает', http.get(
        '/auth/me', headers={'Authorization': f'Bearer {client_token}'}).status_code == 200)

    print()
    print('=== Зарплата в чужую сеть ===')
    answer = http.post('/dashboard/salary/pay', headers=owner, json={
        'shop_id': stranger_id, 'employee_local_id': 1, 'amount': 100000})
    check('чужая точка — отказ', answer.status_code in (400, 404), answer.text[:200])
    db = SessionLocal()
    check('выплата не создана', db.query(SalaryPayout).filter(
        SalaryPayout.shop_id == stranger_id).count() == 0)
    db.close()

    print()
    print('=== Аккаунт без точек не видит чужое ===')
    db = SessionLocal()
    empty = DashboardService(db, account_id=999, shop_ids=[])
    check('пустой список точек — пустая сводка', empty._only_mine(db.query(Visit)).count() == 0)
    db.close()

    print()
    print('=== Отменённая выдача убирается с сервера ===')
    http.post('/sync/push', headers=KEY, json={'payouts': [
        {'local_id': 7, 'employee_local_id': 1, 'amount': 500, 'method': 'cash',
         'paid_at': '2026-10-26T18:00:00'}]})
    db = SessionLocal()
    check('выдача пришла', db.query(SalaryPayout).filter(
        SalaryPayout.shop_id == shop_id, SalaryPayout.local_id == 7).count() == 1)
    db.close()
    http.post('/sync/push', headers=KEY, json={'payouts': [
        {'local_id': 7, 'employee_local_id': 1, 'amount': 500, 'method': 'cash',
         'paid_at': '2026-10-26T18:00:00', 'cancelled': True}]})
    db = SessionLocal()
    check('отменили в цеху — с сервера убрана', db.query(SalaryPayout).filter(
        SalaryPayout.shop_id == shop_id, SalaryPayout.local_id == 7).count() == 0)
    db.close()

finish()
