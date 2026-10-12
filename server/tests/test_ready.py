"""
«Машина готова» — клиенту, который уехал ждать.

Человек оставил машину и ушёл по делам. Пока сказать ему, что всё
сделано, можно было только звонком: приёмщик снимает трубку, человек
не берёт, машина занимает пост.

Сообщение уходит сразу, а не кладётся в очередь до следующего прохода
рассыльщика: через десять минут человек прочтёт его уже у ворот.

Главное в этой проверке — честный ответ. «Отправлено» вместо «не
дошло» хуже, чем отказ: приёмщик решит, что клиента позвали, и будет
ждать его до вечера.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_ready_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-ready'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-ready'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Client, Notice, Shop, KIND_READY, SENT, SKIPPED
from app.services import notices, telegram, webpush

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


# Единственный выход наружу подменяем: проверяем свою логику, а не
# доступность телеграма
sent_to_telegram = []
sent_to_browser = []


def fake_telegram(account, chat_id, text, **kwargs):
    sent_to_telegram.append((chat_id, text))


def fake_push(db, client, title, body, **kwargs):
    sent_to_browser.append((client.id, title, body))
    return 1


telegram.send_message = fake_telegram
webpush.send = fake_push
notices.telegram.send_message = fake_telegram
notices.webpush.send = fake_push

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

with TestClient(app) as client:
    db = SessionLocal()
    shop = db.query(Shop).first()
    account_id = shop.account_id

    # Трое: один в Телеграме, один с уведомлениями в браузере, один
    # ни там ни там — он и есть главный случай
    in_telegram = Client(account_id=account_id, phone='79160000001',
                         name='Пётр', telegram_chat_id='555')
    in_browser = Client(account_id=account_id, phone='79160000002',
                        name='Анна')
    nowhere = Client(account_id=account_id, phone='79160000003',
                     name='Сергей')
    db.add_all([in_telegram, in_browser, nowhere])
    db.commit()
    ids = (in_telegram.id, in_browser.id, nowhere.id)
    db.close()

    # Бот у заказчика подключён, иначе Телеграм не считается каналом
    db = SessionLocal()
    from app.models import Account

    account = db.query(Account).filter(Account.id == account_id).first()
    account.telegram_bot_token = 'test-token'
    db.commit()
    db.close()

    print('=== Клиенту в Телеграме говорим в Телеграм ===')
    answer = client.post('/sync/ready', headers=KEY, json={
        'client_phone': '+7 916 000-00-01',
        'license_plate': 'а123вв777',
        'order_local_id': 42}).json()

    check('отправлено', answer['sent'] is True, str(answer))
    check('каналом назван Телеграм', answer['channel'] == 'telegram',
          str(answer))
    check('сообщение ушло в его чат',
          sent_to_telegram and sent_to_telegram[-1][0] == '555',
          str(sent_to_telegram[-1:]))
    check('в тексте сказано, что готово',
          'готова' in sent_to_telegram[-1][1], sent_to_telegram[-1][1])
    check('и номер машины',
          'А123ВВ777' in sent_to_telegram[-1][1], sent_to_telegram[-1][1])

    db = SessionLocal()
    row = db.query(Notice).filter(Notice.kind == KIND_READY).first()
    check('осталась запись об отправке', row is not None)
    check('помечена отправленной', row.state == SENT, str(row.state))
    check('привязана к наряду',
          row.about == 'order' and row.about_id == 42,
          f'{row.about} {row.about_id}')
    db.close()

    print()
    print('=== Клиенту без Телеграма — в браузер ===')
    db = SessionLocal()
    webpush.connected = lambda db, client: client.id == ids[1]
    webpush.available = lambda: True
    notices.webpush.connected = webpush.connected
    notices.webpush.available = webpush.available
    db.close()

    answer = client.post('/sync/ready', headers=KEY, json={
        'client_phone': '79160000002', 'license_plate': 'К900ОР99'}).json()
    check('отправлено', answer['sent'] is True, str(answer))
    check('каналом назван браузер', answer['channel'] == 'webpush',
          str(answer))
    check('ушло именно ему',
          sent_to_browser and sent_to_browser[-1][0] == ids[1],
          str(sent_to_browser[-1:]))

    print()
    print('=== Некуда сказать — говорим об этом приёмщику ===')
    answer = client.post('/sync/ready', headers=KEY, json={
        'client_phone': '79160000003', 'license_plate': 'Т111ТТ77'}).json()

    check('не отправлено', answer['sent'] is False, str(answer))
    check('сказано, почему',
          'не подключил' in answer['reason'], answer['reason'])

    db = SessionLocal()
    skipped = db.query(Notice).filter(
        Notice.client_id == ids[2]).first()
    check('строка всё равно осталась', skipped is not None)
    check('помечена пропущенной', skipped.state == SKIPPED, str(skipped.state))
    db.close()

    print()
    print('=== Незнакомый номер ===')
    answer = client.post('/sync/ready', headers=KEY, json={
        'client_phone': '79169999999'}).json()
    check('честно сказано, что такого клиента нет',
          answer['sent'] is False and 'кабинет' in answer['reason'],
          str(answer))

    print()
    print('=== Без телефона ===')
    answer = client.post('/sync/ready', headers=KEY, json={
        'license_plate': 'Х555ХХ99'}).json()
    check('просим телефон', answer['sent'] is False
          and 'телефон' in answer['reason'], str(answer))

    print()
    print('=== Чужому ключом не сказать ===')
    refused = client.post('/sync/ready',
                          headers={'X-Sync-Key': 'guessed-key'},
                          json={'client_phone': '79160000001'})
    check('без своего ключа не пускают', refused.status_code in (401, 403),
          str(refused.status_code))

    print()
    print('=== Сбой доставки не выдаётся за успех ===')
    def broken(account, chat_id, text, **kwargs):
        raise telegram.TelegramError('бот заблокирован')

    notices.telegram.send_message = broken

    answer = client.post('/sync/ready', headers=KEY, json={
        'client_phone': '79160000001', 'license_plate': 'А123ВВ777'}).json()
    check('ответ честный', answer['sent'] is False, str(answer))
    check('причина названа', 'бот заблокирован' in answer['reason'],
          answer['reason'])

finish()
