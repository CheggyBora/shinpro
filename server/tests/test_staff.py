"""
Дашборд: вход персонала, роли и права.

Вход тот же, что у клиента, — телефон, код, ПИН. Разница в том, кого
пускают: сотрудника заводит владелец, и человек с улицы сюда не войдёт,
даже зная чужой номер.

Проверяем настоящими запросами: так же, как в сервер будет ходить
дашборд в браузере.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_staff_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-31'
OWNER_NORMALIZED = '79099018931'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-staff'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-key'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Хозяин'

import logging

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import StaffUser, StaffAction

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
    """Код перехватываем из журнала — SMS в тесте никуда не уходит."""

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
STRANGER_PHONE = '+7 916 555-44-33'
OWNER_PIN = '4831'
MASTER_PIN = '9274'


def enter(client, phone, pin):
    """Полный первый вход: код, затем свой ПИН. Возвращает токен."""
    client.post('/staff/code', json={'phone': phone})
    answer = client.post('/staff/verify',
                         json={'phone': phone, 'code': catcher.code})
    if answer.status_code != 200:
        return None, answer

    token = answer.json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = client.post('/staff/pin', json={'pin': pin}, headers=headers)
    return given.json()['token'], given


with TestClient(app) as client:
    print('=== Владелец заводится при запуске сервера ===')
    db = SessionLocal()
    owner = db.query(StaffUser).filter(
        StaffUser.phone == OWNER_NORMALIZED).first()
    check('владелец есть', owner is not None)
    check('роль владельца', owner.role == 'owner', owner.role)
    check('у него все права', 'staff' in owner.allowed() and
          'salary_all' in owner.allowed(), str(owner.allowed()))
    db.close()

    print('\n=== Без входа дашборд закрыт ===')
    check('кто я — закрыто', client.get('/staff/me').status_code == 401)
    check('список людей закрыт', client.get('/staff/people').status_code == 401)

    print('\n=== Чужой номер не выдаёт себя ===')
    stranger = client.post('/staff/start', json={'phone': STRANGER_PHONE}).json()
    check('ответ такой же, как для своего', stranger['step'] == 'verify',
          str(stranger))
    sent = client.post('/staff/code', json={'phone': STRANGER_PHONE})
    check('код будто бы выслан', sent.status_code == 200, str(sent.json()))

    catcher.code = None
    client.post('/staff/code', json={'phone': OWNER_PHONE})
    owner_code = catcher.code
    check('своему код и правда ушёл', owner_code is not None)

    guess = client.post('/staff/verify',
                        json={'phone': STRANGER_PHONE, 'code': owner_code})
    check('чужой не войдёт даже с подсмотренным кодом',
          guess.status_code == 400, str(guess.json()))

    print('\n=== Владелец входит: код, потом ПИН ===')
    token, given = enter(client, OWNER_PHONE, OWNER_PIN)
    check('ПИН принят', given.status_code == 200, str(given.json()))
    owner_headers = {'Authorization': f'Bearer {token}'}

    me = client.get('/staff/me', headers=owner_headers).json()
    check('вошёл владельцем', me['role'] == 'owner', str(me))
    check('ПИН отмечен как заданный', me['pin_is_set'] is True)

    simple = client.post('/staff/pin', json={'pin': '1111'},
                         headers=owner_headers)
    check('простой ПИН не принимается', simple.status_code == 400)

    again = client.post('/staff/login',
                        json={'phone': OWNER_PHONE, 'pin': OWNER_PIN})
    check('следующий вход — сразу по ПИНу', again.status_code == 200)
    owner_headers = {'Authorization': f"Bearer {again.json()['token']}"}

    wrong = client.post('/staff/login',
                        json={'phone': OWNER_PHONE, 'pin': '2846'})
    check('неверный ПИН не пускает', wrong.status_code == 401)
    check('сказано, сколько попыток осталось',
          'осталось' in wrong.json()['detail'].lower(), wrong.json()['detail'])

    print('\n=== Владелец заводит мастера ===')
    added = client.post('/staff/people', headers=owner_headers, json={
        'phone': MASTER_PHONE, 'name': 'Игорь', 'role': 'master',
        'employee_shop_id': 1})
    check('мастер заведён', added.status_code == 200, str(added.json()))
    master_id = added.json()['id']
    check('права мастера — только своя зарплата',
          added.json()['permissions'] == ['salary_own'],
          str(added.json()['permissions']))
    check('привязан к номеру сотрудника',
          added.json()['employee_shop_id'] == 1)

    twice = client.post('/staff/people', headers=owner_headers,
                        json={'phone': MASTER_PHONE, 'role': 'master'})
    check('второй раз тот же номер не заводится', twice.status_code == 400,
          str(twice.json()))

    print('\n=== Мастер входит и видит только своё ===')
    master_token, _ = enter(client, MASTER_PHONE, MASTER_PIN)
    master_headers = {'Authorization': f'Bearer {master_token}'}

    mine = client.get('/staff/me', headers=master_headers).json()
    check('вошёл мастером', mine['role'] == 'master', str(mine))

    check('чужие зарплаты закрыты',
          client.get('/staff/people', headers=master_headers).status_code == 403)
    check('заводить людей не может',
          client.post('/staff/people', headers=master_headers,
                      json={'phone': '+7 916 777-66-55'}).status_code == 403)
    check('журнал доступа закрыт',
          client.get('/staff/log', headers=master_headers).status_code == 403)

    print('\n=== Управляющий: зарплаты по решению владельца ===')
    manager = client.post('/staff/people', headers=owner_headers, json={
        'phone': '+7 916 222-33-44', 'name': 'Ольга', 'role': 'manager'}).json()
    check('выручку видит', 'revenue' in manager['permissions'],
          str(manager['permissions']))
    check('зарплат по умолчанию не видит',
          'salary_all' not in manager['permissions'],
          str(manager['permissions']))

    opened = client.patch(f"/staff/people/{manager['id']}",
                          headers=owner_headers,
                          json={'permissions': ['revenue', 'orders',
                                                'salary_all']}).json()
    check('владелец открыл зарплаты', 'salary_all' in opened['permissions'],
          str(opened['permissions']))
    check('лишнего не прибавилось', 'staff' not in opened['permissions'])

    print('\n=== Смена прав выкидывает из системы сразу ===')
    check('пока права те же, мастер работает',
          client.get('/staff/me', headers=master_headers).status_code == 200)

    client.patch(f'/staff/people/{master_id}', headers=owner_headers,
                 json={'role': 'receptionist'})
    stale = client.get('/staff/me', headers=master_headers)
    check('старый токен больше не годится', stale.status_code == 401,
          str(stale.status_code))
    check('сказано войти заново', 'заново' in stale.json()['detail'],
          stale.json()['detail'])

    print('\n=== Закрытый доступ действует немедленно ===')
    master_token, _ = enter(client, MASTER_PHONE, MASTER_PIN)
    master_headers = {'Authorization': f'Bearer {master_token}'}
    check('мастер снова вошёл',
          client.get('/staff/me', headers=master_headers).status_code == 200)

    client.patch(f'/staff/people/{master_id}', headers=owner_headers,
                 json={'is_active': False})
    closed = client.get('/staff/me', headers=master_headers)
    check('доступ закрылся на месте', closed.status_code in (401, 403),
          str(closed.status_code))

    denied = client.post('/staff/login',
                         json={'phone': MASTER_PHONE, 'pin': MASTER_PIN})
    check('и войти заново нельзя', denied.status_code == 401,
          str(denied.json()))
    check('сказано, к кому идти', 'владельц' in denied.json()['detail'].lower(),
          denied.json()['detail'])

    print('\n=== Последнего владельца не отключить ===')
    db = SessionLocal()
    owner_id = db.query(StaffUser).filter(
        StaffUser.phone == OWNER_NORMALIZED).first().id
    db.close()

    locked = client.patch(f'/staff/people/{owner_id}', headers=owner_headers,
                          json={'is_active': False})
    check('сервер не дал запереть дашборд', locked.status_code == 400,
          str(locked.json()))
    check('объяснено почему', 'владелец' in locked.json()['detail'].lower(),
          locked.json()['detail'])

    demote = client.patch(f'/staff/people/{owner_id}', headers=owner_headers,
                          json={'role': 'manager'})
    check('и роль последнему владельцу не понизить',
          demote.status_code == 400, str(demote.json()))

    print('\n=== Журнал помнит, кто что делал ===')
    log = client.get('/staff/log', headers=owner_headers).json()
    kinds = {row['action'] for row in log}
    check('вход записан', 'login' in kinds or 'verify' in kinds, str(kinds))
    check('заведение сотрудника записано', 'staff_add' in kinds, str(kinds))
    check('изменение прав записано', 'staff_update' in kinds, str(kinds))

    db = SessionLocal()
    check('журнал лежит в базе', db.query(StaffAction).count() > 0)
    db.close()

    print('\n=== Роли и права отдаются для экрана настройки ===')
    roles = client.get('/staff/roles', headers=owner_headers).json()
    check('роли перечислены', len(roles['roles']) == 4, str(len(roles['roles'])))
    check('права названы по-человечески',
          any(item['title'] == 'Выручка и отчёты'
              for item in roles['permissions']), str(roles['permissions']))

finish()
