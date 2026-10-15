"""
Вход по звонку: человек звонит нам, а не мы ему.

Он вводит телефон, видит номер и кнопку «Позвонить». Вызов
сбрасывается до соединения, номер подтверждается сам. Ни кода, ни
ожидания SMS, и звонок бесплатный.

Главное, что здесь проверяется, — чужой вход нельзя забрать себе.
Номера проверок у любого сервиса идут подряд, и если бы «дозвонился
ли?» мог спросить кто угодно, достаточно было бы перебирать номера и
ждать, пока кто-нибудь войдёт: токен достался бы спрашивающему.
Поэтому проверку закрываем билетом, который знает только тот браузер,
что начал вход.

Второе — честность ответов. «Ждём» и «время вышло» это разные вещи:
в первом случае человек дозванивается, во втором ему надо начинать
заново, и крутить колёсико до вечера он не должен.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_call_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-31'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-call'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-call'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_CALL_PROVIDER'] = 'flashcall'
os.environ['SERVER_CALL_TOKEN'] = 'test-token'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Client, LoginCode
from app.services import callcheck

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


# Подменяем единственный выход наружу: проверяем свою логику, а не
# доступность сервиса звонков
state = {'next_id': 1, 'answers': {}, 'started': []}


def fake_start(phone, db=None, shop=None):
    check_id = str(state['next_id'])
    state['next_id'] += 1
    state['started'].append((check_id, phone))
    state['answers'][check_id] = callcheck.PENDING
    return check_id, '+7 495 000-11-22', 60


def fake_status(check_id, db=None, shop=None):
    return state['answers'].get(check_id, callcheck.PENDING)


callcheck.start = fake_start
callcheck.status = fake_status

import app.services.auth_service as auth_service
import app.services.staff_service as staff_service

auth_service.callcheck.start = fake_start
auth_service.callcheck.status = fake_status
staff_service.callcheck.start = fake_start
staff_service.callcheck.status = fake_status

PHONE = '+7 916 000-00-01'

with TestClient(app) as client:
    print('=== Страница узнаёт, что звонок доступен ===')
    start = client.post('/auth/start', json={'phone': PHONE}).json()
    check('сказано, что можно звонком', start['call_available'] is True,
          str(start))

    print()
    print('=== Начали вход звонком ===')
    begun = client.post('/auth/call', json={'phone': PHONE})
    check('приняли', begun.status_code == 200, str(begun.json()))

    answer = begun.json()
    check('дали номер для звонка', answer['dial'] == '+7 495 000-11-22',
          str(answer))
    check('дали билет', len(answer['ticket']) > 20, str(answer['ticket']))
    check('сказали, сколько секунд', answer['seconds'] == 60, str(answer))
    check('номер ушёл сервису', state['started'][-1][1] == '79160000001',
          str(state['started'][-1:]))

    ticket = answer['ticket']

    print()
    print('=== Пока не дозвонился — ждём, а не пускаем ===')
    waiting = client.post('/auth/call/check',
                          json={'phone': PHONE, 'ticket': ticket})
    check('ответ «ждём»', waiting.status_code == 202, str(waiting.status_code))
    check('токена в нём нет', 'token' not in waiting.text, waiting.text[:80])

    print()
    print('=== Чужой билет не пускает ===')
    # Номера проверок идут подряд, и без билета чужой вход можно было бы
    # подкараулить перебором
    stranger = client.post('/auth/call/check',
                           json={'phone': PHONE, 'ticket': 'подобранный'})
    check('отказано', stranger.status_code == 400, str(stranger.status_code))
    check('сказано начать заново',
          'заново' in stranger.json()['detail'], stranger.json()['detail'])

    print()
    print('=== Дозвонился — вход ===')
    state['answers'][state['started'][-1][0]] = callcheck.CONFIRMED

    entered = client.post('/auth/call/check',
                          json={'phone': PHONE, 'ticket': ticket})
    check('пустили', entered.status_code == 200, str(entered.status_code))
    check('токен выдан', bool(entered.json()['token']), str(entered.json()))
    check('это тот же номер', '916' in entered.json()['phone'],
          str(entered.json()['phone']))
    check('видно, что ПИН ещё не задан',
          entered.json()['pin_is_set'] is False, str(entered.json()))

    db = SessionLocal()
    person = db.query(Client).filter(Client.phone == '79160000001').first()
    check('клиент заведён', person is not None)
    check('номер отмечен подтверждённым',
          person.phone_verified_at is not None)
    db.close()

    print()
    print('=== Второй раз тот же билет не работает ===')
    # Иначе перехваченный билет открывал бы вход сколько угодно раз
    repeat = client.post('/auth/call/check',
                         json={'phone': PHONE, 'ticket': ticket})
    check('отказано', repeat.status_code == 400, str(repeat.status_code))

    print()
    print('=== Время вышло — говорим прямо ===')
    begun = client.post('/auth/call', json={'phone': '+7 916 000-00-02'}).json()
    state['answers'][state['started'][-1][0]] = callcheck.EXPIRED

    late = client.post('/auth/call/check',
                       json={'phone': '+7 916 000-00-02',
                             'ticket': begun['ticket']})
    check('отказано', late.status_code == 400, str(late.status_code))
    check('сказано, что звонка не было',
          'звонка не было' in late.json()['detail'].lower(),
          late.json()['detail'])

    print()
    print('=== Сервис звонков молчит — вход не рушим ===')
    # Сеть моргнула. Это не повод объявлять отказ: срок проверки и так
    # ограничен, пусть человек дозванивается
    begun = client.post('/auth/call', json={'phone': '+7 916 000-00-03'}).json()

    def broken(check_id, db=None, shop=None):
        raise callcheck.CallError('сервис не ответил')

    auth_service.callcheck.status = broken

    quiet = client.post('/auth/call/check',
                        json={'phone': '+7 916 000-00-03',
                              'ticket': begun['ticket']})
    check('по-прежнему «ждём»', quiet.status_code == 202,
          str(quiet.status_code))

    auth_service.callcheck.status = fake_status

    print()
    print('=== Владелец входит в дашборд так же ===')
    start = client.post('/staff/start', json={'phone': OWNER_PHONE}).json()
    check('звонок предложен и здесь', start['call_available'] is True,
          str(start))

    begun = client.post('/staff/call', json={'phone': OWNER_PHONE}).json()
    state['answers'][state['started'][-1][0]] = callcheck.CONFIRMED

    entered = client.post('/staff/call/check',
                          json={'phone': OWNER_PHONE,
                                'ticket': begun['ticket']})
    check('пустили', entered.status_code == 200, str(entered.json()))
    check('токен выдан', bool(entered.json()['token']))

    print()
    print('=== Чужой номер в дашборд не пускают ===')
    # Номер подтвердится — он же настоящий. Но доступа у него нет, и
    # ответ должен быть такой же, как при неверном коде
    begun = client.post('/staff/call', json={'phone': '+7 916 777-66-55'}).json()
    state['answers'][state['started'][-1][0]] = callcheck.CONFIRMED

    refused = client.post('/staff/call/check',
                          json={'phone': '+7 916 777-66-55',
                                'ticket': begun['ticket']})
    check('не пустили', refused.status_code == 400, str(refused.status_code))
    check('без подсказки, что номера нет в списке',
          'списке' not in refused.json()['detail'].lower(),
          refused.json()['detail'])

    print()
    print('=== Без подключённого сервиса звонок не предлагаем ===')
    from app.config import settings

    settings.CALL_PROVIDER = 'off'

    start = client.post('/auth/start', json={'phone': PHONE}).json()
    check('кнопки не будет', start['call_available'] is False, str(start))

    nope = client.post('/auth/call', json={'phone': PHONE})
    check('и напрямую нельзя', nope.status_code == 400, str(nope.status_code))

    print()
    print('=== Ключ из программы цеха включает звонок ===')
    # Менять ключ должен владелец из программы, а не тот, у кого есть
    # доступ к серверу. Поэтому присланное цехом главнее окружения
    KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
    client.post('/sync/push', headers=KEY, json={'settings': {
        'call_provider': 'flashcall', 'call_token': 'ключ-из-цеха'}})

    start = client.post('/auth/start', json={'phone': PHONE}).json()
    check('звонок снова предлагается', start['call_available'] is True,
          str(start))

    print()
    print('=== Ключ без провайдера ничего не включает ===')
    client.post('/sync/push', headers=KEY, json={'settings': {
        'call_provider': 'off', 'call_token': 'ключ-из-цеха'}})

    start = client.post('/auth/start', json={'phone': PHONE}).json()
    check('по-прежнему выключено', start['call_available'] is False,
          str(start))

    print()
    print('=== Пустой ключ из цеха не затирает серверный ===')
    # Иначе обмен со старой версией программы, которая этих настроек
    # не шлёт, выключал бы вход всем
    settings.CALL_PROVIDER = 'flashcall'
    client.post('/sync/push', headers=KEY, json={'settings': {
        'call_provider': '', 'call_token': ''}})

    start = client.post('/auth/start', json={'phone': PHONE}).json()
    check('работает по серверному ключу', start['call_available'] is True,
          str(start))

    print()
    print('=== Какой ключ в итоге уходит провайдеру ===')
    from app.services import callcheck as real_callcheck
    from app.database import SessionLocal as Session
    from app.services import tenancy

    client.post('/sync/push', headers=KEY, json={'settings': {
        'call_provider': 'flashcall', 'call_token': 'ключ-из-цеха'}})

    db = Session()
    shop = tenancy.shops_of(db, 1)[0]
    provider, token = real_callcheck.setup(db, shop)
    db.close()

    check('провайдер из цеха', provider == 'flashcall', str(provider))
    check('и ключ из цеха', token == 'ключ-из-цеха', str(token))

finish()
