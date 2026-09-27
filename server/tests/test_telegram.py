"""
Напоминания клиенту в Telegram.

Проверяем весь путь: заказчик подключил своего бота, клиент нажал
кнопку в кабинете, перешёл в бот, тот прислал код обратно — и с этого
момента человеку уходят напоминания.

Главные правила, которые легко нарушить:

  · пишем только тем, кто сам подключился;
  · бот принадлежит заказчику: клиент «Колеса» не получит сообщение
    от бота «РИФа»;
  · отменили запись — напоминание «завтра приезжать» не уходит;
  · одно и то же напоминание не уходит дважды.

Телеграм в тесте не настоящий: его ответы подменяются, и наружу не
уходит ни одного запроса.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_telegram_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-telegram'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Account, Client, Appointment, Notice, KIND_BOOKED,
                        KIND_REMINDER, WAITING, SENT, FAILED, SKIPPED)
from app.security import hash_secret, create_token
from app.services import notices, telegram, tenancy
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
# Подменяем телеграм: наружу ничего не уходит
# ----------------------------------------------------------------------
sent = []          # что бот «отправил»
fail_next = {'count': 0}


def fake_call(token, method, payload=None):
    if method == 'getMe':
        return {'id': 1, 'username': 'rif_shiny_bot'}

    if method == 'setWebhook':
        sent.append(('webhook', payload['url']))
        return True

    if method == 'sendMessage':
        if fail_next['count'] > 0:
            fail_next['count'] -= 1
            raise telegram.TelegramError('bot was blocked by the user')

        sent.append((str(payload['chat_id']), payload['text']))
        return {'message_id': len(sent)}

    return True


telegram.call = fake_call

with TestClient(app) as client:
    db = SessionLocal()
    account, shop, _key = tenancy.create_account(db, 'Шиномонтаж «РИФ»')
    other, _other_shop, _other_key = tenancy.create_account(db, 'Колесо')
    account_id, shop_id, shop_slug = account.id, shop.id, shop.slug

    person = Client(account_id=account_id, phone='79099018931', name='Андрей',
                    phone_verified_at=shop_now())
    person.pin_hash = hash_secret('79099018931', '4831')
    db.add(person)
    db.commit()
    person_id = person.id
    token = create_token(person_id)
    headers = {'Authorization': f'Bearer {token}', 'X-Shop': shop_slug}

    print('=== Пока бот не подключён, предлагать нечего ===')
    answer = client.get('/me/telegram', headers=headers).json()
    check('напоминания недоступны', answer['available'] is False, str(answer))

    print('\n=== Заказчик подключает своего бота ===')
    telegram.connect_bot(db, account, 'токен-от-ботфазера')
    check('имя бота сохранено', account.telegram_bot_username == 'rif_shiny_bot',
          str(account.telegram_bot_username))
    check('секрет для приёма сообщений появился',
          bool(account.telegram_secret))

    secret = account.telegram_secret
    telegram.set_webhook(account, 'https://rif.ru')
    check('телеграму сказали, куда слать',
          any(kind == 'webhook' and secret in url for kind, url in sent),
          str(sent[-1:]))

    print('\n=== Кабинет отдаёт ссылку с одноразовым кодом ===')
    answer = client.get('/me/telegram', headers=headers).json()
    check('теперь доступно', answer['available'] is True, str(answer))
    check('пока не подключён', answer['connected'] is False)
    check('ссылка ведёт на бота', 'rif_shiny_bot' in answer['url'],
          answer['url'])

    code = answer['url'].split('start=')[1]
    check('код одноразовый и непустой', len(code) > 6, code)

    print('\n=== Чужой бот по этому коду человека не найдёт ===')
    stranger = client.post(f'/telegram/{other.telegram_secret or "нет"}',
                           json={'message': {'chat': {'id': 777},
                                             'text': f'/start {code}'}})
    check('чужой секрет не подходит', stranger.status_code == 404,
          str(stranger.status_code))

    print('\n=== Человек нажал «Старт» в правильном боте ===')
    answer = client.post(f'/telegram/{secret}', json={
        'message': {'chat': {'id': 555001}, 'text': f'/start {code}'}})
    check('телеграму ответили «принято»', answer.status_code == 200)

    db.expire_all()
    person = db.query(Client).get(person_id)
    check('переписка привязана к человеку',
          person.telegram_chat_id == '555001', str(person.telegram_chat_id))
    check('код стёрт после привязки', person.telegram_code is None)
    check('человеку подтвердили',
          any(chat == '555001' and 'Готово' in text for chat, text in sent),
          str(sent[-1:]))

    print('\n=== Тот же код второй раз не сработает ===')
    before = person.telegram_chat_id
    client.post(f'/telegram/{secret}', json={
        'message': {'chat': {'id': 999999}, 'text': f'/start {code}'}})
    db.expire_all()
    person = db.query(Client).get(person_id)
    check('привязка не перехвачена', person.telegram_chat_id == before,
          str(person.telegram_chat_id))

    print('\n=== Кабинет показывает, что подключено ===')
    answer = client.get('/me/telegram', headers=headers).json()
    check('связь видна', answer['connected'] is True, str(answer))

    print('\n=== Записали — подтверждение сейчас, напоминание накануне ===')
    appointment = Appointment(shop_id=shop_id, client_id=person_id,
                              scheduled_at=shop_now() + timedelta(days=2),
                              duration_minutes=60,
                              license_plate='А123ВВ777', status='scheduled')
    db.add(appointment)
    db.commit()

    made = notices.plan_for_appointment(db, person, 'Шиномонтаж «РИФ»',
                                         appointment)
    check('сделано два уведомления', len(made) == 2, str(len(made)))

    kinds = {notice.kind: notice for notice in made}
    check('подтверждение уходит сразу',
          kinds[KIND_BOOKED].send_at <= shop_now())
    check('напоминание отложено на канун',
          kinds[KIND_REMINDER].send_at > shop_now(),
          str(kinds[KIND_REMINDER].send_at))
    check('в тексте есть время приезда',
          appointment.scheduled_at.strftime('%H:%M') in kinds[KIND_BOOKED].text,
          kinds[KIND_BOOKED].text)

    print('\n=== Отправляем созревшее ===')
    result = notices.send_due(db)
    check('ушло одно', result['sent'] == 1, str(result))
    check('напоминание осталось ждать',
          db.query(Notice).filter(Notice.state == WAITING).count() == 1)

    print('\n=== Повторный запуск не шлёт то же самое дважды ===')
    before_count = len(sent)
    notices.send_due(db)
    check('ничего не отправлено', len(sent) == before_count,
          f'{len(sent)} против {before_count}')

    print('\n=== Записался человек без телеграма — напоминать нечем ===')
    silent = Client(account_id=account_id, phone='79161234567', name='Пётр')
    db.add(silent)
    db.commit()

    notice = notices.add(db, silent, KIND_BOOKED, 'Записали вас на завтра')
    check('уведомление помечено пропущенным', notice.state == SKIPPED,
          notice.state)
    check('и в отправку не попадёт',
          notice not in notices.due(db))

    print('\n=== Запись отменили — напоминание не уйдёт ===')
    cancelled = notices.cancel_about(db, 'appointment', appointment.id,
                                      kinds=[KIND_REMINDER])
    check('снято одно', cancelled == 1, str(cancelled))
    check('в очереди пусто',
          db.query(Notice).filter(Notice.state == WAITING).count() == 0)

    print('\n=== Цех перенёс запись — человек узнаёт ===')
    person.telegram_chat_id = '555001'
    db.commit()

    moved = Appointment(shop_id=shop_id, client_id=person_id,
                        scheduled_at=shop_now() + timedelta(days=3),
                        duration_minutes=60, license_plate='А123ВВ777',
                        status='scheduled')
    db.add(moved)
    db.commit()
    notices.plan_for_appointment(db, person, 'Шиномонтаж «РИФ»', moved)
    notices.send_due(db)

    from app.api.sync import _tell_client

    was_time = moved.scheduled_at
    moved.scheduled_at = was_time + timedelta(hours=3)
    db.commit()
    _tell_client(db, moved, was_time, 'scheduled')

    waiting = db.query(Notice).filter(
        Notice.about_id == moved.id, Notice.state == WAITING).all()
    kinds = {notice.kind for notice in waiting}
    check('сказали о переносе', 'moved' in kinds, str(kinds))
    check('напоминание переставлено на новое время',
          any(notice.kind == KIND_REMINDER
              and moved.scheduled_at.strftime('%H:%M') in notice.text
              for notice in waiting), str([row.text[:40] for row in waiting]))
    check('старое напоминание снято',
          sum(1 for notice in waiting if notice.kind == KIND_REMINDER) == 1,
          str(len(waiting)))

    print('\n=== Цех отменил запись ===')
    notices.send_due(db)
    moved.status = 'cancelled'
    db.commit()
    _tell_client(db, moved, moved.scheduled_at, 'scheduled')

    left = db.query(Notice).filter(
        Notice.about_id == moved.id, Notice.state == WAITING).all()
    check('осталось только сообщение об отмене',
          [notice.kind for notice in left] == ['cancelled'],
          str([notice.kind for notice in left]))

    notices.send_due(db)
    check('оно ушло человеку',
          any('отменена' in text for chat, text in sent[-2:]),
          str(sent[-1:]))

    print('\n=== Человек заблокировал бота ===')
    blocked = notices.add(db, person, KIND_BOOKED, 'Проверка')
    fail_next['count'] = 5

    for _ in range(3):
        notices.send_due(db)

    db.expire_all()
    blocked = db.query(Notice).get(blocked.id)
    check('после трёх попыток сдаёмся', blocked.state == FAILED, blocked.state)
    check('причина записана', 'blocked' in (blocked.last_error or ''),
          str(blocked.last_error))
    fail_next['count'] = 0

    print('\n=== Отключение по /stop ===')
    client.post(f'/telegram/{secret}', json={
        'message': {'chat': {'id': 555001}, 'text': '/stop'}})

    db.expire_all()
    person = db.query(Client).get(person_id)
    check('связь разорвана', person.telegram_chat_id is None)
    check('человеку сказали',
          any('отключены' in text for chat, text in sent[-2:]),
          str(sent[-1:]))

    print('\n=== И через кабинет тоже ===')
    person.telegram_chat_id = '555001'
    db.commit()

    answer = client.delete('/me/telegram', headers=headers).json()
    check('отключено', answer['connected'] is False, str(answer))

    db.expire_all()
    check('в базе тоже',
          db.query(Client).get(person_id).telegram_chat_id is None)

    db.close()

finish()
