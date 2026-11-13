"""
Работы у партнёров на сервере (решения владельца 13.11.2026).

  · работа приходит из цеха обменом задач со своими полями и уходит
    обратно с правками сервера;
  · партнёр привязывается к боту по нику или ссылке-приглашению;
  · заявка уходит с кнопками; «Назначить цену» → число → цена партнёра,
    статус «в работе»; ответ — в переписку; «Готово» — ждёт оплаты;
  · дашборд: оплата партнёрам, оплатить → статус «оплачено» и способ;
  · покраска: цена клиенту ссылкой, клиент «да» → в работу.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_partner_work_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-53'
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-partner-work'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-partner-work'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'
os.environ['SERVER_PHOTO_DIR'] = os.path.join(tempfile.gettempdir(), 'tire_partner_work_photos')

import logging

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Account, Counterparty, PartnerMessage, Task
from app.services import telegram

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
calls = []


def fake_call(token, method, payload=None):
    calls.append((method, payload))
    if method == 'getMe':
        return {'username': 'rif_bot'}
    if method == 'sendMessage':
        return {'message_id': 500 + len(calls)}
    return True


telegram.call = fake_call
KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify', json={'phone': phone, 'code': CodeCatcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def job_item(uid, title, kind='work', status='agree', our=3500, theirs=None, needs_client=False,
             updated='2026-11-13T10:00:00'):
    return {'uid': uid, 'category': 'work' if kind == 'work' else 'paint', 'direction': 'tire',
            'due_date': '2026-11-13', 'title': title, 'counterparty_uid': 'party-weld-0001',
            'license_plate': 'А123ВВ777', 'client_phone': '+79001112233', 'amount': our,
            'source': 'shop', 'updated_at': updated, 'created_at': updated,
            'partner_kind': kind, 'partner_status': status, 'our_price': our,
            'partner_price': theirs, 'needs_client': needs_client, 'order_local_id': 41}


def last_sent(chat):
    return [p for m, p in calls if m == 'sendMessage' and p['chat_id'] in (chat, int(chat))][-1]


with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4832')
    http.post('/dashboard/bot', headers={**owner, 'host': 'admin.example.ru'}, json={'token': '1:A'})
    db = SessionLocal()
    secret = db.query(Account).first().telegram_secret
    db.close()

    print('=== Работа приходит из цеха ===')
    answer = http.post('/sync/tasks', headers=KEY, json={
        'since': None,
        'counterparties': [{'uid': 'party-weld-0001', 'name': 'Сварка Плюс', 'telegram': '@Serg_Svarka',
                            'updated_at': '2026-11-13T09:00:00'}],
        'tasks': [job_item('job-1', 'Сварка диска · А123ВВ777'),
                  job_item('job-2', 'Покраска R17 × 4', kind='paint', our=8000, needs_client=True)]}).json()
    check('обмен принял', not answer['rejected'], str(answer['rejected']))
    listed = http.get('/dashboard/partners', headers=owner).json()
    check('в дашборде две работы, обе на согласовании', len(listed['jobs']) == 2
          and {j['status'] for j in listed['jobs']} == {'agree'}, str(listed)[:300])

    print('\n=== Партнёр и бот ===')
    http.post(f'/telegram/{secret}', json={'update_id': 1, 'message': {
        'message_id': 1, 'text': '/start', 'chat': {'id': 777, 'first_name': 'Сергей',
                                                    'username': 'Serg_Svarka'}}})
    answer = http.post('/dashboard/partners/job-1/send', headers=owner)
    check('заявка ушла партнёру по нику', answer.status_code == 200, answer.text[:200])
    sent = last_sent('777')
    buttons = sent.get('reply_markup', {}).get('inline_keyboard', [[]])[0]
    check('с кнопками «Назначить цену» и «Не возьмусь»',
          [b['text'] for b in buttons] == ['Назначить цену', 'Не возьмусь'], str(buttons))
    price_data = buttons[0]['callback_data']
    http.post(f'/telegram/{secret}', json={'update_id': 2, 'callback_query': {
        'id': 'cb1', 'data': price_data, 'message': {'message_id': 9, 'chat': {'id': 777}}}})
    check('бот просит цену числом', 'числом' in last_sent('777')['text'])
    http.post(f'/telegram/{secret}', json={'update_id': 3, 'message': {
        'message_id': 2, 'text': '2 000 ₽', 'chat': {'id': 777, 'username': 'Serg_Svarka'}}})
    job = http.get('/dashboard/partners/job-1', headers=owner).json()
    check('цена партнёра 2000 — в работе, маржа 1500', job['partner_price'] == 2000
          and job['status'] == 'work' and job['margin'] == 1500, str(job)[:300])
    check('в переписке: «Партнёр назначил цену»',
          any('назначил цену' in m['text'] for m in job['messages']), str(job['messages']))
    http.post(f'/telegram/{secret}', json={'update_id': 4, 'message': {
        'message_id': 3, 'text': 'Будет завтра к 14:00', 'chat': {'id': 777}}})
    job = http.get('/dashboard/partners/job-1', headers=owner).json()
    check('ответ партнёра — в переписке', any(m['author'] == 'partner' and 'завтра' in m['text']
                                              for m in job['messages']))
    http.post('/dashboard/partners/job-1/message', headers=owner, json={'text': 'Ок, ждём'})
    check('сообщение сотрудника ушло партнёру', 'Ок, ждём' in last_sent('777')['text'])

    http.post('/dashboard/partners/job-1/send', headers=owner)
    done_button = last_sent('777')['reply_markup']['inline_keyboard'][0][0]
    check('в работе — кнопка «Готово, можно забирать»', done_button['text'] == 'Готово, можно забирать')
    http.post(f'/telegram/{secret}', json={'update_id': 5, 'callback_query': {
        'id': 'cb2', 'data': done_button['callback_data'], 'message': {'message_id': 9, 'chat': {'id': 777}}}})
    listed = http.get('/dashboard/partners', headers=owner).json()
    check('партнёр нажал «Готово» — ждёт оплаты, к оплате 2000',
          next(j for j in listed['jobs'] if j['uid'] == 'job-1')['status'] == 'wait_pay'
          and listed['summary']['owe'] == 2000, str(listed['summary']))

    print('\n=== Оплата из дашборда ===')
    answer = http.post('/dashboard/partners/pay', headers=owner,
                       json={'uids': ['job-1'], 'method': 'cash', 'note': 'Сергею лично'})
    check('оплачено', answer.status_code == 200
          and next(j for j in answer.json()['jobs'] if j['uid'] == 'job-1')['status'] == 'paid')
    back = http.post('/sync/tasks', headers=KEY, json={'since': '2026-11-13T09:59:00', 'tasks': []}).json()
    mine = next((t for t in back['tasks'] if t['uid'] == 'job-1'), {})
    check('цех получает: оплачено, наличные, цена 2000 — проведёт РКО',
          mine.get('partner_status') == 'paid' and mine.get('pay_method') == 'cash'
          and mine.get('partner_price') == 2000, str(mine)[:300])

    print('\n=== Покраска: цена клиенту ===')
    http.post('/dashboard/partners/job-2/price', headers=owner, json={'price': '3500'})
    job = http.get('/dashboard/partners/job-2', headers=owner).json()
    check('цена партнёра — теперь согласование с клиентом', job['status'] == 'client')
    answer = http.post('/dashboard/partners/job-2/quote', headers={**owner, 'host': 'admin.example.ru'})
    link = answer.json()['quote_sent']['link']
    check('ссылка клиенту', link.startswith('https://admin.example.ru/pq/'), link)
    token = link.rsplit('/', 1)[1]
    page = http.get(f'/pq/{token}')
    check('страница открывается', page.status_code == 200 and 'Цена работы' in page.text)
    data = http.get(f'/public/quote/{token}').json()
    check('на странице — наша цена 8000, не цена партнёра', data['price'] == 8000 and '3500' not in str(data))
    data = http.post(f'/public/quote/{token}', json={'answer': 'yes'}).json()
    job = http.get('/dashboard/partners/job-2', headers=owner).json()
    check('клиент «да» — в работе', data['state'] == 'yes' and job['status'] == 'work')

    print('\n=== Ссылка-приглашение и чужие ===')
    check('у работы есть ссылка-приглашение партнёру',
          (job.get('invite') or '').startswith('https://t.me/rif_bot?start=p-'), str(job.get('invite')))
    http.post(f'/telegram/{secret}', json={'update_id': 6, 'callback_query': {
        'id': 'cb3', 'data': price_data, 'message': {'message_id': 9, 'chat': {'id': 999}}}})
    db = SessionLocal()
    check('чужой чат не может нажать кнопки партнёра',
          db.query(Task).filter(Task.uid == 'job-1').first().partner_status == 'paid')
    db.close()
    check('кабинет без входа — отказ', http.get('/m/partners').status_code in (401, 403))

    print('\n=== Кабинет сотрудника на телефоне ===')
    import hashlib

    def pin_hash(pin):
        return hashlib.sha256(f'tire-master-pin:{pin}'.encode('utf-8')).hexdigest()

    http.post('/sync/push', headers=KEY, json={'employees': [
        {'local_id': 1, 'name': 'Иван', 'pin_hash': pin_hash('4827'), 'can_partners': True},
        {'local_id': 2, 'name': 'Пётр', 'pin_hash': pin_hash('9153'), 'can_partners': False}]})
    link = http.post('/sync/master-link', headers=KEY).json()['link']
    phone = TestClient(app)
    phone.post('/m/connect', json={'link': link})
    phone.post('/m/login', json={'employee_local_id': 2, 'pin': '9153'})
    check('Пётр не согласует — вкладки нет, доступа нет',
          not phone.get('/m/me').json()['partners'] and phone.get('/m/partners').status_code == 403)
    phone.post('/m/logout')
    phone.post('/m/login', json={'employee_local_id': 1, 'pin': '4827'})
    check('Иван согласует — вкладка «Партнёры» есть', phone.get('/m/me').json()['partners'])
    listed = phone.get('/m/partners').json()
    check('в кабинете — открытые работы (оплаченная — нет)',
          [j['uid'] for j in listed['jobs']] == ['job-2'], str([j['uid'] for j in listed['jobs']]))
    job = phone.post('/m/partners/job-2/message',
                     files={'photo': ('p.jpg', b'\xff\xd8\xff\xe0' + b'0' * 100, 'image/jpeg')},
                     data={'text': 'Вот диск'}).json()
    shot = next((m for m in job['messages'] if m['photo']), None)
    check('фото с телефона — в переписке', shot is not None and shot['text'] == 'Вот диск', str(job)[:300])
    picture = phone.get(f"/m/partners/job-2/photo/{shot['id']}")
    check('фото открывается', picture.status_code == 200 and len(picture.content) > 50)
    job = phone.post('/m/partners/job-2/status', json={'action': 'finish'}).json()
    check('«Партнёр сделал» с телефона — ждёт оплаты', job['status'] == 'wait_pay')

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
