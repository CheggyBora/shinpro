"""
Сервер приложения: вход, запись, хранение, история, очередь.

Проверяем через настоящие запросы к серверу — так же, как в него
будет ходить приложение. Отдельная временная база на прогон.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

# Базу и ключи выставляем ДО импорта приложения: настройки читаются
# в момент импорта
_db_path = os.path.join(tempfile.gettempdir(), 'tire_server_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
# Ключи только латиницей: они уходят в заголовки HTTP, а туда
# кириллица не проходит — как и в бою
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-checks'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-key'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

import logging
from datetime import datetime, timedelta, date

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.utils import now as shop_now
from app.models import (BookingDay, StoredSet, Visit, QueueSnapshot, Client,
                        Shop, TAKEN)


def the_shop(db):
    """Точка, заведённая при запуске сервера: данные принадлежат ей."""
    return db.query(Shop).first()

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

PHONE = '+7 909 901-89-31'
NORMALIZED = '79099018931'
PIN = '4831'          # четыре цифры, не подряд и не одинаковые

with TestClient(app) as client:
    print('=== Сервер отвечает ===')
    health = client.get('/health').json()
    check('здоровье в порядке', health['ok'] is True, str(health))

    print('\n=== Без входа ничего не отдаёт ===')
    check('запись закрыта', client.get('/booking/my').status_code == 401)
    check('хранение закрыто', client.get('/storage').status_code == 401)
    check('история закрыта', client.get('/history').status_code == 401)

    print('\n=== Кривой номер отвергается ===')
    for bad in ('12345', 'абвгд', '+1 555 0100'):
        answer = client.post('/auth/start', json={'phone': bad})
        check('«' + bad + '» не принят', answer.status_code == 400,
              str(answer.status_code))

    print('\n=== Новому человеку нужен код ===')
    first = client.post('/auth/start', json={'phone': PHONE}).json()
    check('сказано подтвердить номер', first['step'] == 'verify', str(first))
    check('видно, что он незнакомый', first['is_known'] is False)
    check('канал назван', first['channel'] in ('sms', 'email'), first['channel'])

    print('\n=== Код приходит ===')
    sent = client.post('/auth/code', json={'phone': PHONE})
    check('код выслан', sent.status_code == 200, str(sent.json()))
    check('сказано, сколько он живёт', sent.json()['expires_in_seconds'] > 0)
    check('код перехвачен', catcher.code is not None, str(catcher.code))

    wrong = client.post('/auth/verify', json={'phone': PHONE, 'code': '0000'})
    check('неверный код не пускает', wrong.status_code == 400)
    check('сказано, сколько попыток осталось',
          'осталось' in wrong.json()['detail'].lower(), wrong.json()['detail'])

    got = client.post('/auth/verify',
                      json={'phone': PHONE, 'code': catcher.code,
                            'device_id': 'device-1'})
    check('верный код пускает', got.status_code == 200, str(got.json()))
    token = got.json()['token']
    client_id = got.json()['client_id']
    check('телефон показан по-человечески',
          got.json()['phone'] == '+7 (909) 901-89-31', got.json()['phone'])
    check('ПИН пока не задан', got.json()['pin_is_set'] is False)

    headers = {'Authorization': 'Bearer ' + token}

    print('\n=== Тот же код второй раз не работает ===')
    again = client.post('/auth/verify',
                        json={'phone': PHONE, 'code': catcher.code})
    check('повторный вход по тому же коду отклонён', again.status_code == 400,
          str(again.json()))

    print('\n=== ПИН-код ===')
    for weak in ('1111', '1234', '4321', '12', 'абвг', '12а4'):
        answer = client.post('/auth/pin', headers=headers, json={'pin': weak})
        check('слабый ПИН «' + weak + '» отклонён', answer.status_code == 400,
              str(answer.status_code))

    saved = client.post('/auth/pin', headers=headers, json={'pin': PIN})
    check('нормальный ПИН принят', saved.status_code == 200, str(saved.json()))
    check('в профиле видно, что ПИН задан', saved.json()['pin_is_set'] is True)

    print('\n=== Дальше вход только по телефону и ПИНу ===')
    known = client.post('/auth/start', json={'phone': PHONE}).json()
    check('спрашивается ПИН, а не код', known['step'] == 'pin', str(known))
    check('человек уже известен', known['is_known'] is True)

    fast = client.post('/auth/login', json={'phone': PHONE, 'pin': PIN})
    check('по ПИНу пускает', fast.status_code == 200, str(fast.json()))
    check('это тот же клиент', fast.json()['client_id'] == client_id)

    print('\n=== Чужой ПИН не подходит ===')
    stranger = client.post('/auth/login', json={'phone': PHONE, 'pin': '9876'})
    check('неверный ПИН отклонён', stranger.status_code == 401,
          str(stranger.json()))

    print('\n=== ПИН блокируется после промахов ===')
    for _ in range(5):
        miss = client.post('/auth/login', json={'phone': PHONE, 'pin': '9876'})
    check('после промахов ПИН заблокирован',
          'закончились' in miss.json()['detail'].lower()
          or 'заблокирован' in miss.json()['detail'].lower(),
          miss.json()['detail'])

    blocked = client.post('/auth/login', json={'phone': PHONE, 'pin': PIN})
    check('верный ПИН тоже больше не пускает', blocked.status_code == 401,
          str(blocked.json()))

    state = client.post('/auth/start', json={'phone': PHONE}).json()
    check('человека отправляют подтверждать номер', state['step'] == 'verify',
          str(state))
    check('и сказано, что ПИН заблокирован', state['pin_is_blocked'] is True)

    print('\n=== Код снимает блокировку ===')
    client.post('/auth/code', json={'phone': PHONE})
    client.post('/auth/verify', json={'phone': PHONE, 'code': catcher.code})
    unlocked = client.post('/auth/login', json={'phone': PHONE, 'pin': PIN})
    check('ПИН снова работает', unlocked.status_code == 200,
          str(unlocked.json()))

    print('\n=== Профиль ===')
    me = client.get('/auth/me', headers=headers).json()
    check('это тот же клиент', me['id'] == client_id)
    check('машин пока нет', me['cars'] == [])

    named = client.patch('/auth/me', headers=headers, json={'name': 'Андрей'})
    check('имя сохранилось', named.json()['name'] == 'Андрей', str(named.json()))

    print('\n=== Испорченный токен не пускает ===')
    check('чужой токен отвергнут',
          client.get('/auth/me', headers={'Authorization': 'Bearer nonsense'}
                     ).status_code == 401)


    # --- Готовим день в цеху -------------------------------------------
    db = SessionLocal()
    TOMORROW = (shop_now() + timedelta(days=1)).date()
    shop = the_shop(db)
    db.add(BookingDay(shop_id=shop.id, day=TOMORROW, posts=2,
                      opens_at='09:00', closes_at='18:00'))
    db.add(BookingDay(shop_id=shop.id, day=TOMORROW + timedelta(days=1), posts=1,
                      is_closed=True))
    db.commit()
    db.close()

    print('\n=== Свободные окна ===')
    days = client.get('/booking/days', headers=headers).json()
    check('календарь построен', len(days) > 0, str(len(days)))

    tomorrow = [d for d in days if d['day'] == TOMORROW.isoformat()][0]
    check('на завтра два поста', tomorrow['posts'] == 2, str(tomorrow['posts']))
    check('окна есть', len(tomorrow['slots']) > 0, str(len(tomorrow['slots'])))
    check('первое окно не раньше открытия',
          tomorrow['slots'][0]['at'].endswith('09:00:00'),
          tomorrow['slots'][0]['at'])

    closed = [d for d in days if d['day'] == (TOMORROW + timedelta(days=1)).isoformat()][0]
    check('в выходной окон нет', closed['slots'] == [] and closed['is_closed'])

    print('\n=== Время работ зависит от колёс ===')
    assembled = client.get('/booking/days?wheels_assembled=true',
                           headers=headers).json()
    tires = client.get('/booking/days?wheels_assembled=false',
                       headers=headers).json()
    a_slots = [d for d in assembled if d['day'] == TOMORROW.isoformat()][0]['slots']
    t_slots = [d for d in tires if d['day'] == TOMORROW.isoformat()][0]['slots']
    # Окна идут по часу, и обе длительности в час укладываются — значит,
    # окон одинаково. Разница появится, если норматив перевалит за шаг сетки
    check('под россыпь окон не больше, чем под перекидку',
          len(a_slots) >= len(t_slots),
          f'{len(a_slots)} против {len(t_slots)}')

    print('\n=== Запись ===')
    slot = tomorrow['slots'][2]['at']
    booked = client.post('/booking', headers=headers,
                         json={'at': slot, 'license_plate': 'а123вв777',
                               'wheels_assembled': True})
    check('записались', booked.status_code == 200, str(booked.json()))
    appointment = booked.json()
    check('номер нормализован', appointment['license_plate'] == 'А123ВВ777',
          appointment['license_plate'])
    check('пока не подтверждено цехом', appointment['is_confirmed'] is False)
    check('время работ по колёсам в сборе',
          appointment['duration_minutes'] == 30,
          str(appointment['duration_minutes']))

    print('\n=== Машина завелась и попала в профиль ===')
    me = client.get('/auth/me', headers=headers).json()
    check('машина видна в профиле', len(me['cars']) == 1, str(me['cars']))
    check('колёса запомнились', me['cars'][0]['wheels_assembled'] is True)

    print('\n=== Дважды на одно время не записаться ===')
    twice = client.post('/booking', headers=headers,
                        json={'at': slot, 'license_plate': 'А123ВВ777'})
    check('вторая запись отклонена', twice.status_code == 400, str(twice.json()))

    print('\n=== В прошлое не записаться ===')
    past = client.post('/booking', headers=headers,
                       json={'at': (shop_now() - timedelta(hours=2)).isoformat(),
                             'license_plate': 'К900ОР99'})
    check('прошедшее время отклонено', past.status_code == 400,
          str(past.json()))

    print('\n=== Далеко вперёд не записаться ===')
    far = client.post('/booking', headers=headers,
                      json={'at': (shop_now() + timedelta(days=60)).isoformat(),
                            'license_plate': 'К900ОР99'})
    check('слишком далёкая дата отклонена', far.status_code == 400,
          str(far.json()))

    print('\n=== Свои записи ===')
    mine = client.get('/booking/my', headers=headers).json()
    check('запись в списке', len(mine) == 1, str(len(mine)))

    print('\n=== Отмена записи ===')
    dropped = client.delete(f"/booking/{appointment['id']}", headers=headers)
    check('запись отменена', dropped.status_code == 200, str(dropped.json()))
    check('состояние сменилось', dropped.json()['status'] == 'cancelled')
    check('в активных её больше нет',
          len(client.get('/booking/my', headers=headers).json()) == 0)

    print('\n=== Незадолго до записи отменять нельзя ===')
    soon = (shop_now() + timedelta(minutes=30))
    db = SessionLocal()
    from app.models import Appointment
    close_one = Appointment(client_id=client_id, scheduled_at=soon,
                            duration_minutes=40, license_plate='А123ВВ777',
                            status='scheduled', source='app')
    db.add(close_one)
    db.commit()
    close_id = close_one.id
    db.close()

    late = client.delete(f'/booking/{close_id}', headers=headers)
    check('поздняя отмена отклонена', late.status_code == 400, str(late.json()))
    check('предложено позвонить', 'позвоните' in late.json()['detail'].lower(),
          late.json()['detail'])

    # --- Хранение --------------------------------------------------------
    print('\n=== Шины на хранении ===')
    db = SessionLocal()
    stored = StoredSet(shop_id=the_shop(db).id, client_id=client_id,
                       license_plate='А123ВВ777',
                       storage_type='Шины с дисками', diameter='R17',
                       brand='Nokian Hakkapeliitta', wheel_type='Литые',
                       accepted_at=shop_now() - timedelta(days=30),
                       expires_at=shop_now() + timedelta(days=150),
                       status='stored')
    db.add(stored)
    db.commit()
    stored_id = stored.id
    db.close()

    sets = client.get('/storage', headers=headers).json()
    check('комплект виден', len(sets) == 1, str(len(sets)))
    check('посчитано, сколько дней осталось', sets[0]['days_left'] > 100,
          str(sets[0]['days_left']))
    check('марка на месте', 'Nokian' in sets[0]['brand'])

    print('\n=== Заявка привезти комплект ===')
    early = client.post(f'/storage/{stored_id}/request', headers=headers,
                        json={'at': (shop_now() + timedelta(hours=2)).isoformat()})
    check('слишком срочная заявка отклонена', early.status_code == 400,
          str(early.json()))

    ordered = client.post(f'/storage/{stored_id}/request', headers=headers,
                          json={'at': (shop_now() + timedelta(days=2)).isoformat()})
    check('заявка принята', ordered.status_code == 200, str(ordered.json()))
    check('видно, что ждём цеха',
          ordered.json()['request_state'] == 'pending',
          str(ordered.json()['request_state']))

    print()
    print('=== Запись с выдачей со склада: ближайшие дни закрыты ===')
    plain = client.get('/booking/days', headers=headers).json()
    with_set = client.get('/booking/days?with_storage=true',
                          headers=headers).json()

    check('дней столько же', len(plain) == len(with_set),
          f'{len(plain)} против {len(with_set)}')
    check('без комплекта ближайший день открыт',
          plain[0]['storage_too_soon'] is False, str(plain[0]))
    check('с комплектом — закрыт', with_set[0]['storage_too_soon'] is True,
          str(with_set[0]))
    check('и окон в нём нет', with_set[0]['slots'] == [],
          str(len(with_set[0]['slots'])))
    check('сказано, что день закрыт', with_set[0]['is_closed'] is True)

    closed = [day for day in with_set if day['storage_too_soon']]
    check('закрыто ровно два дня', len(closed) == 2, str(len(closed)))
    check('третий уже открыт', with_set[2]['storage_too_soon'] is False,
          str(with_set[2]['day']))

    print()
    print('=== Через голову приложения записаться тоже нельзя ===')
    soon = client.post('/booking', headers=headers, json={
        'at': (shop_now() + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0).isoformat(),
        'license_plate': 'А123ВВ777',
        'storage_ids': [stored_id]})
    check('запись отклонена', soon.status_code == 400, str(soon.json()))
    check('объяснено про склад',
          'склад' in soon.json()['detail'].lower(), soon.json()['detail'])

    print()
    print('=== Без комплекта в тот же день записаться можно ===')
    same = client.post('/booking', headers=headers, json={
        'at': (shop_now() + timedelta(days=1)).replace(
            hour=13, minute=0, second=0, microsecond=0).isoformat(),
        'license_plate': 'А123ВВ777'})
    check('запись прошла', same.status_code == 200, str(same.json()))

    print('\n=== Чужой комплект не отдаётся ===')
    db = SessionLocal()
    stranger = Client(phone='79990001122')
    db.add(stranger)
    db.commit()
    alien = StoredSet(shop_id=the_shop(db).id, client_id=stranger.id,
                      license_plate='М777ММ199',
                      status='stored')
    db.add(alien)
    db.commit()
    alien_id = alien.id
    db.close()

    check('в своём списке чужого нет',
          len(client.get('/storage', headers=headers).json()) == 1)
    check('заявку на чужой комплект не принять',
          client.post(f'/storage/{alien_id}/request', headers=headers,
                      json={'at': (shop_now() + timedelta(days=2)).isoformat()}
                      ).status_code == 404)

    # --- История ----------------------------------------------------------
    print('\n=== История визитов ===')
    db = SessionLocal()
    db.add(Visit(shop_id=the_shop(db).id, client_id=client_id,
                 license_plate='А123ВВ777',
                 visited_at=shop_now() - timedelta(days=200),
                 total_amount=3200.0,
                 services='Шиномонтаж\nБалансировка',
                 recommendations='Через 5000 км заменить передние колодки'))
    db.add(Visit(shop_id=the_shop(db).id, client_id=client_id,
                 license_plate='А123ВВ777',
                 visited_at=shop_now() - timedelta(days=30),
                 total_amount=1800.0, services='Ремонт грибком'))
    db.commit()
    db.close()

    visits = client.get('/history', headers=headers).json()
    check('оба визита видны', len(visits) == 2, str(len(visits)))
    check('свежий первым', visits[0]['total_amount'] == 1800.0,
          str(visits[0]['total_amount']))
    check('услуги разобраны в список',
          visits[1]['services'] == ['Шиномонтаж', 'Балансировка'],
          str(visits[1]['services']))

    advice = client.get('/history/recommendations', headers=headers).json()
    check('визит с рекомендацией один', len(advice) == 1, str(len(advice)))
    check('текст рекомендации на месте',
          'колодки' in advice[0]['recommendations'])

    # --- Очередь ------------------------------------------------------------
    print('\n=== Очередь без данных ===')
    empty = client.get('/queue', headers=headers).json()
    check('честно сказано, что данных нет', empty['is_stale'] is True,
          str(empty))
    check('предложено позвонить', 'позвоните' in empty['note'].lower(),
          empty['note'])

    print('\n=== Свежая очередь ===')
    db = SessionLocal()
    db.add(QueueSnapshot(shop_id=the_shop(db).id, taken_at=shop_now(), cars_in_work=2,
                         cars_waiting=1, open_posts=2, free_in_minutes=25,
                         shift_is_open=True))
    db.commit()
    db.close()

    now_queue = client.get('/queue', headers=headers).json()
    check('данные свежие', now_queue['is_stale'] is False, str(now_queue))
    check('машин в работе двое', now_queue['cars_in_work'] == 2)
    check('сказано, когда освободится', '25' in now_queue['note'],
          now_queue['note'])

    print('\n=== Устаревшая очередь не выдаётся за свежую ===')
    # Устаревшая — это когда САМЫЙ СВЕЖИЙ слепок старый: цех давно
    # не выходил на связь. Поэтому убираем прежние, а не добавляем к ним
    db = SessionLocal()
    db.query(QueueSnapshot).delete()
    db.add(QueueSnapshot(shop_id=the_shop(db).id, taken_at=shop_now() - timedelta(hours=3),
                         cars_in_work=5, cars_waiting=4, open_posts=2,
                         free_in_minutes=10, shift_is_open=True))
    db.commit()
    db.close()

    old = client.get('/queue', headers=headers).json()
    check('помечено как устаревшее', old['is_stale'] is True, str(old))
    check('прогноз времени не показываем', old['free_in_minutes'] is None)
    check('сказано звонить', 'позвонить' in old['note'].lower(), old['note'])

finish()
