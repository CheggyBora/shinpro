"""
Бот организации на сервере (решение владельца 13.11.2026).

  · владелец подключает бота в дашборде: токеном или одной кнопкой —
    тем, что вписан в программе на точке; сервер ставит вебхук;
  · кто нажал «Старт» — сервер запоминает и отдаёт цеху при обмене
    вместе с токеном; цех больше не опрашивает телеграм сам;
  · сообщения для своих (задачи, склад) уходят ботом организации;
  · отключили — цех снова сам по себе.

Телеграм в тесте подменён: настоящих запросов нет.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_org_bot_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-52'
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-org-bot'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-org-bot'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Account, Shop
from app.services import notify, telegram

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


class CodeCatcher(logging.Handler):
    code = None

    def emit(self, record):
        message = record.getMessage()
        if 'код' in message:
            CodeCatcher.code = message.strip().split()[-1]


logging.getLogger('tire_server').addHandler(CodeCatcher())

# Телеграм — подменённый
calls = []


def fake_call(token, method, payload=None):
    calls.append((token, method, payload))
    if token == 'bad':
        raise telegram.TelegramError('Unauthorized')
    if method == 'getMe':
        return {'username': 'rif_shop_bot' if token == 'shop-token' else 'other_bot'}
    return True


telegram.call = fake_call
KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify', json={'phone': phone, 'code': CodeCatcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4832')

    print('=== Бот в программе на точке ===')
    pushed = http.post('/sync/push', headers=KEY, json={'settings': {'telegram_token': 'shop-token'}}).json()
    check('бота на сервере нет — цеху пусто', not pushed.get('org_bot'), str(pushed.get('org_bot')))
    state = http.get('/dashboard/bot', headers=owner).json()
    check('дашборд предлагает перенести бота с точки', state == {'connected': False, 'username': '',
                                                                'people': 0, 'shop_bot': True}, str(state))

    print('\n=== Перенести одной кнопкой ===')
    answer = http.post('/dashboard/bot', headers={**owner, 'host': 'admin.example.ru'},
                       json={'from_shop': True})
    state = answer.json()
    check('подключён: @rif_shop_bot', answer.status_code == 200 and state['connected']
          and state['username'] == 'rif_shop_bot' and not state['shop_bot'], str(state))
    webhook = next((c for c in calls if c[1] == 'setWebhook'), None)
    check('вебхук — на адрес дашборда, https, с секретом, и кнопки тоже',
          webhook and webhook[2]['url'].startswith('https://admin.example.ru/telegram/')
          and 'callback_query' in webhook[2]['allowed_updates'], str(webhook))

    db = SessionLocal()
    account = db.query(Account).first()
    secret = account.telegram_secret
    shop = db.query(Shop).first()
    check('сообщения своим — ботом организации', notify.token_of(db, shop) == 'shop-token')
    db.close()

    print('\n=== Кто нажал «Старт» ===')
    for chat_id, first, nick in ((111, 'Сергей', 'Serg_Svarka'), (222, 'Ольга', None)):
        http.post(f'/telegram/{secret}', json={'update_id': chat_id, 'message': {
            'message_id': 1, 'text': '/start', 'chat': {'id': chat_id, 'first_name': first,
                                                       **({'username': nick} if nick else {})}}})
    http.post(f'/telegram/{secret}', json={'update_id': 3, 'message': {
        'message_id': 2, 'text': 'привет', 'chat': {'id': 111, 'first_name': 'Сергей Петров',
                                                     'username': 'Serg_Svarka'}}})
    greeted = [c for c in calls if c[1] == 'sendMessage' and c[2]['chat_id'] in (111, 222)]
    check('нажавшим «Старт» бот ответил', len(greeted) >= 2, str(len(greeted)))
    pushed = http.post('/sync/push', headers=KEY, json={'settings': {}}).json()
    people = sorted(pushed.get('telegram_people', []), key=lambda p: p['chat_id'])
    check('цех получает бота с токеном', pushed.get('org_bot') == {'username': 'rif_shop_bot',
                                                                  'token': 'shop-token'}, str(pushed.get('org_bot')))
    check('и кто писал: двое, без повторов, ник маленькими, имя свежее',
          people == [{'chat_id': '111', 'username': 'serg_svarka', 'name': 'Сергей Петров'},
                     {'chat_id': '222', 'username': '', 'name': 'Ольга'}], str(people))
    check('в дашборде — двое написали', http.get('/dashboard/bot', headers=owner).json()['people'] == 2)

    print('\n=== Чужой токен и отключение ===')
    answer = http.post('/dashboard/bot', headers=owner, json={'token': 'bad'})
    check('неверный токен — понятный отказ', answer.status_code == 400
          and 'Телеграм не принял' in answer.json()['detail'], answer.text)
    answer = http.delete('/dashboard/bot', headers=owner)
    check('отключили', answer.status_code == 200 and not answer.json()['connected'])
    check('вебхук снят', any(c[1] == 'deleteWebhook' for c in calls))
    pushed = http.post('/sync/push', headers=KEY, json={'settings': {}}).json()
    check('цеху снова пусто — опрашивает сам', not pushed.get('org_bot'))

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
