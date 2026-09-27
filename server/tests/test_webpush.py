"""
Уведомления в браузере — второй канал напоминаний.

Проверяем то, что легко сделать неправильно:

  · без ключей VAPID канала нет, и кабинет его не предлагает;
  · подписка принадлежит устройству: телефон и компьютер — две, и
    уведомление уходит на оба;
  · один и тот же браузер, подписавшийся дважды, — одна строка;
  · телеграм важнее: если он подключён, в браузер не дублируем;
  · мёртвая подписка (человек снёс кабинет) выбрасывается, а не
    получает отказы годами;
  · чужую подписку нельзя ни увидеть, ни отключить.

Настоящий сервер пуша здесь не участвует: подменяется отправка, потому
что зашифровать сообщение может только настоящий браузер.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_webpush_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-webpush'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

# Ключей пока нет намеренно: первая проверка — что без них канала нет
os.environ['SERVER_PUSH_PUBLIC_KEY'] = ''
os.environ['SERVER_PUSH_PRIVATE_KEY'] = ''

from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import (Appointment, Client, Notice, PushSubscription,
                        BY_PUSH, BY_TELEGRAM, KIND_BOOKED, SENT, SKIPPED)
from app.security import hash_secret, create_token
from app.services import notices, tenancy, telegram, webpush
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


# ----------------------------------------------------------------------
# Подменяем отправку: наружу ничего не уходит
# ----------------------------------------------------------------------
pushed = []               # что «ушло» в браузер
dead = set()              # адреса, которые отвечают «меня больше нет»
broken = set()            # адреса, которые просто не отвечают


def fake_deliver(subscription, payload):
    if subscription.endpoint in dead:
        raise webpush.PushError('Gone', gone=True)

    if subscription.endpoint in broken:
        raise webpush.PushError('Сервер пуша не ответил')

    pushed.append((subscription.endpoint, payload))


webpush.deliver = fake_deliver


# Телеграм тоже подменяем: он в этом наборе нужен только затем, чтобы
# проверить, что при живом телеграме в браузер не дублируем
telegrammed = []


def fake_call(token, method, payload=None):
    if method == 'getMe':
        return {'id': 1, 'username': 'rif_bot'}
    if method == 'sendMessage':
        telegrammed.append((str(payload['chat_id']), payload['text']))
        return {'message_id': len(telegrammed)}
    return True


telegram.call = fake_call


PHONE = '79099018931'
POINT = 'https://fcm.googleapis.com/fcm/send/телефон-андрей'
DESKTOP = 'https://fcm.googleapis.com/fcm/send/компьютер-андрей'

with TestClient(app) as client:
    db = SessionLocal()
    account, shop, _key = tenancy.create_account(db, 'Шиномонтаж «РИФ»')
    other, _other_shop, _other_key = tenancy.create_account(db, 'Колесо')
    account_id, shop_id, shop_slug = account.id, shop.id, shop.slug

    person = Client(account_id=account_id, phone=PHONE, name='Андрей',
                    phone_verified_at=shop_now())
    person.pin_hash = hash_secret(PHONE, '4831')
    db.add(person)

    stranger = Client(account_id=other.id, phone=PHONE, name='Чужой',
                      phone_verified_at=shop_now())
    db.add(stranger)
    db.commit()

    person_id, stranger_id = person.id, stranger.id
    headers = {'Authorization': f'Bearer {create_token(person_id)}',
               'X-Shop': shop_slug}

    print('=== Без ключей канала нет ===')
    answer = client.get('/me/push', headers=headers).json()
    check('кабинету предлагать нечего', answer['available'] is False,
          str(answer))
    check('ключ не отдаётся', answer['public_key'] is None)

    refused = client.post('/me/push', headers=headers, json={
        'endpoint': POINT, 'keys': {'p256dh': 'x', 'auth': 'y'}})
    check('подписаться нельзя', refused.status_code == 503,
          str(refused.status_code))

    print('\n=== Заводим ключи ===')
    public, private = webpush.generate_keys()
    check('открытый ключ нужной длины', len(public) == 87, str(len(public)))
    check('закрытый ключ нужной длины', len(private) == 43, str(len(private)))

    settings.PUSH_PUBLIC_KEY = public
    settings.PUSH_PRIVATE_KEY = private
    check('канал появился', webpush.available() is True)

    answer = client.get('/me/push', headers=headers).json()
    check('кабинет получил ключ', answer['public_key'] == public)
    check('пока не подписан', answer['connected'] is False, str(answer))

    print('\n=== Подписываем телефон ===')
    body = client.post('/me/push', headers=headers, json={
        'endpoint': POINT,
        'keys': {'p256dh': 'ключ-шифрования', 'auth': 'ключ-подписи'}}).json()
    check('подписался', body['connected'] is True, str(body))
    check('устройство одно', body['devices'] == 1, str(body['devices']))

    print('\n=== Тот же браузер второй раз — не вторая строка ===')
    client.post('/me/push', headers=headers, json={
        'endpoint': POINT,
        'keys': {'p256dh': 'новый-ключ', 'auth': 'ключ-подписи'}})

    rows = db.query(PushSubscription).filter(
        PushSubscription.client_id == person_id).all()
    check('строка одна', len(rows) == 1, str(len(rows)))
    db.expire_all()
    rows = db.query(PushSubscription).filter(
        PushSubscription.client_id == person_id).all()
    check('ключи обновились', rows[0].p256dh == 'новый-ключ', rows[0].p256dh)

    print('\n=== Добавили компьютер — устройств два ===')
    body = client.post('/me/push', headers=headers, json={
        'endpoint': DESKTOP,
        'keys': {'p256dh': 'ключ-2', 'auth': 'подпись-2'}}).json()
    check('устройств два', body['devices'] == 2, str(body['devices']))

    print('\n=== Уведомление уходит на оба устройства ===')
    pushed.clear()
    db.expire_all()
    person = db.query(Client).get(person_id)

    count = webpush.send(db, person, 'Шиномонтаж «РИФ»',
                         'Записали вас на 29.09 в 10:00', url='/z')
    check('доставлено на два', count == 2, str(count))
    check('оба адреса задеты',
          {endpoint for endpoint, _ in pushed} == {POINT, DESKTOP},
          str(len(pushed)))
    check('в уведомлении есть заголовок и текст',
          pushed[0][1]['title'] == 'Шиномонтаж «РИФ»'
          and 'Записали' in pushed[0][1]['body'], str(pushed[0][1]))

    print('\n=== Записался — уведомление идёт в браузер ===')
    appointment = Appointment(shop_id=shop_id, client_id=person_id,
                              scheduled_at=shop_now() + timedelta(days=2),
                              duration_minutes=60,
                              license_plate='А123ВВ777', status='scheduled')
    db.add(appointment)
    db.commit()

    pushed.clear()
    made = notices.plan_for_appointment(db, person, 'Шиномонтаж «РИФ»',
                                        appointment)
    check('уведомления поставлены в очередь', len(made) == 2, str(len(made)))

    result = notices.send_due(db)
    check('ушло одно', result['sent'] == 1, str(result))
    check('и именно в браузер', result[BY_PUSH] == 1, str(result))
    check('в телеграм ничего', result[BY_TELEGRAM] == 0, str(result))

    db.expire_all()
    sent = db.query(Notice).filter(Notice.state == SENT).first()
    check('канал записан в строку', sent.channel == BY_PUSH, str(sent.channel))

    print('\n=== Заголовок берётся из первой строки, разметки в нём нет ===')
    title, body_text = notices.for_browser(sent)
    check('заголовок — название шиномонтажа',
          title == 'Шиномонтаж «РИФ»', title)
    check('разметка убрана', '<' not in body_text and '>' not in body_text,
          body_text)
    check('текст не потерялся', 'Записали вас' in body_text, body_text)

    print('\n=== Телеграм важнее: дважды об одном не пишем ===')
    person.telegram_chat_id = '555001'
    db.commit()
    telegram.connect_bot(db, db.query(type(account)).get(account_id),
                         'токен-от-ботфазера')

    pushed.clear()
    telegrammed.clear()

    notices.add(db, person, KIND_BOOKED, '<b>Шиномонтаж «РИФ»</b>\nПроверка')
    result = notices.send_due(db)
    check('ушло телеграмом', result[BY_TELEGRAM] == 1, str(result))
    check('в браузер не дублировали', not pushed, str(len(pushed)))

    person.telegram_chat_id = None
    db.commit()

    print('\n=== Мёртвая подписка выбрасывается ===')
    dead.add(DESKTOP)
    pushed.clear()

    count = webpush.send(db, person, 'Шиномонтаж', 'Проверка живого')
    check('доставлено на живое устройство', count == 1, str(count))

    left = {row.endpoint for row in webpush.subscriptions(db, person)}
    check('мёртвая убрана', left == {POINT}, str(left))
    dead.clear()

    print('\n=== Молчащий адрес выбрасываем не сразу ===')
    broken.add(POINT)
    for _ in range(webpush.MAX_FAILURES - 1):
        try:
            webpush.send(db, person, 'Шиномонтаж', 'Проверка')
        except webpush.PushError:
            pass

    check('подписка ещё держится',
          len(webpush.subscriptions(db, person)) == 1,
          str(len(webpush.subscriptions(db, person))))

    try:
        webpush.send(db, person, 'Шиномонтаж', 'Проверка')
    except webpush.PushError:
        pass

    check('после десятой неудачи убрана',
          not webpush.subscriptions(db, person),
          str(len(webpush.subscriptions(db, person))))
    broken.clear()

    print('\n=== Некому писать — уведомление помечается пропущенным ===')
    notice = notices.add(db, person, KIND_BOOKED, 'Записали вас')
    check('в очередь не попало', notice.state == SKIPPED, notice.state)

    print('\n=== Чужая подписка недосягаема ===')
    client.post('/me/push', headers=headers, json={
        'endpoint': POINT, 'keys': {'p256dh': 'снова', 'auth': 'подпись'}})

    outsider = {'Authorization': f'Bearer {create_token(stranger_id)}',
                'X-Shop': shop_slug}
    body = client.get('/me/push', headers=outsider).json()
    check('чужой не видит подписок', body['connected'] is False, str(body))

    client.delete('/me/push', headers=outsider)
    db.expire_all()
    person = db.query(Client).get(person_id)
    check('и отключить не смог',
          len(webpush.subscriptions(db, person)) == 1,
          str(len(webpush.subscriptions(db, person))))

    print('\n=== Отключение одного устройства не гасит остальные ===')
    client.post('/me/push', headers=headers, json={
        'endpoint': DESKTOP, 'keys': {'p256dh': 'к2', 'auth': 'п2'}})

    body = client.delete(f'/me/push?endpoint={DESKTOP}',
                         headers=headers).json()
    check('осталось одно', body['devices'] == 1, str(body))
    check('осталось именно то',
          [row.endpoint for row in webpush.subscriptions(db, person)] == [POINT],
          str([row.endpoint for row in webpush.subscriptions(db, person)]))

    print('\n=== Отключение без адреса гасит все ===')
    body = client.delete('/me/push', headers=headers).json()
    check('подписок нет', body['connected'] is False, str(body))
    check('в базе тоже', not webpush.subscriptions(db, person))

    db.close()

finish()
