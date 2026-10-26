"""
Наряд по фото машины (docs/order_photo.md).

  · номер: латиница → кириллица, проверка по форматам, поправки по местам
    букв и цифр, сборка из основной части и региона;
  · без библиотеки или на мусоре распознавание отвечает (None, 0);
  · телефон: снимок → номер, «есть в базе», «записан на …», мойка — только
    когда включена; не прочитался — пусто, а снимок всё равно сохранён;
  · номер без региона дополняется по базе, если машина одна;
  · «Создать наряд» — машина ждёт цех; номер приводится к виду, мусор и
    чужой снимок не принимаются;
  · цех: видит только свои ждущие и не старше двух часов, снимок —
    только свой, «done» с нарядом делает снимок обложкой, без наряда —
    снимает машину;
  · обложка не уходит клиенту и не видна в его кабинете и в списке
    снимков мастеров; в дашборде у наряда cover_url, ссылка подписана;
  · удаление точки забирает её машины с телефона.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_arrivals_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)
_photo_dir = os.path.join(tempfile.gettempdir(), 'tire_arrivals_files')
_model_dir = os.path.join(tempfile.gettempdir(), 'tire_arrivals_models')

OWNER_PHONE = '+7 909 901-89-61'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-arrivals-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-arrivals'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'
os.environ['SERVER_PHOTO_DIR'] = _photo_dir
os.environ['SERVER_PLATE_MODEL_DIR'] = _model_dir

import logging
import shutil
from datetime import datetime, timedelta

if os.path.exists(_photo_dir):
    shutil.rmtree(_photo_dir)

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Account, Appointment, Arrival, Car, Client, OrderPhoto,
                        Shop)
from app.security import create_token
from app.services import photos, plates, shop_settings, telegram, tenancy
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

to_telegram = []


def fake_photo(account, chat_id, data, caption=None):
    to_telegram.append((chat_id, len(data), caption))


telegram.send_photo = fake_photo
photos.telegram.send_photo = fake_photo

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
JPEG = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffd9')


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify',
                      json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


print('=== Номер: вид и формат ===')
check('латиница → кириллица, мусор убран',
      plates.normalize('a123bc 77') == 'А123ВС77', plates.normalize('a123bc 77'))
check('кириллица остаётся', plates.normalize('к555кк-777') == 'К555КК777')
for plate in ('А123ВВ77', 'А123ВВ777', 'a123bb777', 'Х001ХХ199'):
    check(f'обычный номер {plate} годится',
          plates.plate_format(plate) == 'standard')
check('такси', plates.plate_format('АВ12377') == 'taxi')
check('прицеп', plates.plate_format('АВ123477') == 'trailer')
for plate in ('А000ВВ77', 'Б123ВВ77', 'А123ВВ7', 'А123ВВ00', 'ABCDEF', '',
              'А123ВВ7777', 'Z123BB77'):
    check(f'{plate!r} — не номер', not plates.is_valid(plate))
check('основная часть без региона', plates.is_main_part('a123bb')
      and not plates.is_main_part('А123ВВ77'))

print()
print('=== Номер из прочитанного моделью ===')
check('цифра на месте буквы — буква',
      plates.pick('4123BC77', 0.9) == ('А123ВС77', 0.9),
      str(plates.pick('4123BC77', 0.9)))
check('буква на месте цифры — цифра',
      plates.pick('M0O7OP199', 0.8)[0] == 'М007ОР199',
      str(plates.pick('M0O7OP199', 0.8)))
check('хвост RUS отброшен', plates.pick('K555KK777RUS', 0.9)[0] == 'К555КК777',
      str(plates.pick('K555KK777RUS', 0.9)))
check('целиком не прочитался — собран из частей',
      plates.pick('A123BC_7', 0.9, 'A123BC', 0.95, '77', 0.8)
      == ('А123ВС77', 0.8), str(plates.pick('A123BC_7', 0.9, 'A123BC', 0.95, '77', 0.8)))
check('регион не прочитался — основная часть, уверенность вдвое ниже',
      plates.pick('A123BC', 0.9, 'A123BC', 0.9, 'RUS', 0.5)
      == ('А123ВС', 0.45), str(plates.pick('A123BC', 0.9, 'A123BC', 0.9, 'RUS', 0.5)))
check('мусор — ничего', plates.pick('HELLO', 0.99) == (None, 0.0))
check('ничего не прочитано — ничего', plates.pick('', 0.0) == (None, 0.0))
check('регион подтверждён двумя прочтениями', plates.confirmed_region('А123ВВ777', ['777', '777', '']))
check('одно прочтение — не подтверждён', not plates.confirmed_region('А123ВВ777', ['777', '77', '710']))
check('целиком «77», регион отдельно «977» — берём 977',
      plates.pick('H578OB77', 0.94, 'H578OB', 0.95, '977', 0.9)[0] == 'Н578ОВ977',
      str(plates.pick('H578OB77', 0.94, 'H578OB', 0.95, '977', 0.9)))
check('целиком «77», отдельно тоже «77» — так и остаётся',
      plates.pick('H578OB77', 0.94, 'H578OB', 0.95, '77', 0.9)[0] == 'Н578ОВ77')
check('белорусский 1234 AB-7 — как есть',
      plates.pick('1234AB7', 0.9, '1234AB', 0.9, '7', 0.8) == ('1234АВ7', 0.9),
      str(plates.pick('1234AB7', 0.9, '1234AB', 0.9, '7', 0.8)))
check('страна — Беларусь', plates.foreign_country('1234АВ7') == 'BY')
check('казахский с кодом страны — без кода',
      plates.pick('KZ123ABC01', 0.88)[0] == '123АВС01', str(plates.pick('KZ123ABC01', 0.88)))
check('российский — не иностранный', plates.foreign_country('А123ВВ777') is None)
check('непонятное и неуверенное — ничего', plates.pick('12QW', 0.5) == (None, 0.0))
check('отдельно «199», целиком «99» — 199',
      plates.pick('A123BC99', 0.9, 'A123BC', 0.9, '199', 0.8)[0] == 'А123ВС199')
check('без библиотеки или на мусоре — (None, 0)',
      plates.recognize(b'not an image') == (None, 0.0))
check('пустой снимок — (None, 0)', plates.recognize(b'') == (None, 0.0))

# Дальше распознавание подменяем: модели в тестах не нужны
answers = []


def fake_recognize(data):
    return answers.pop(0) if answers else (None, 0.0)


plates.recognize = fake_recognize

with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4832')

    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_id, account_id = shop.id, shop.account_id
    account = db.query(Account).filter(Account.id == account_id).first()
    account.telegram_bot_token = 'test-token'
    client = Client(account_id=account_id, phone='79160000061', name='Иван Петров',
                    telegram_chat_id='777')
    db.add(client)
    db.commit()
    client_id = client.id
    db.add(Car(account_id=account_id, license_plate='А123ВВ777',
               client_id=client_id, vehicle_type='car', wheel_diameter='17'))
    db.add(Appointment(shop_id=shop_id, license_plate='А123ВВ777',
                       scheduled_at=shop_now().replace(hour=14, minute=30,
                                                       second=0, microsecond=0),
                       status='scheduled', direction='tire', source='shop'))
    db.commit()
    other, other_key = tenancy.add_shop(db, shop.account, 'РИФ на Южной')
    other_id = other.id
    db.close()
    OTHER = {'X-Sync-Key': other_key}

    # Прошлый визит машины — чтобы телефон сказал «был 12.04»
    http.post('/sync/push', headers=KEY, json={
        'visits': [{'local_id': 900, 'license_plate': 'А123ВВ777',
                    'visited_at': '2026-04-12T11:00:00', 'total_amount': 4500}]})

    # Телефоны: свой и другой точки. Каждый — отдельный клиент со своими
    # куками, как настоящий телефон: пропуск живёт в куке
    class Phone:
        def __init__(self, shop_key, name):
            self.http = TestClient(app)
            link = http.post('/sync/master-link', headers=shop_key).json()['link']
            self.http.post('/m/connect', json={'link': link, 'name': name})

        def post(self, path, **kwargs):
            return self.http.post(path, **kwargs)

    master = Phone(KEY, 'Андрей')
    stranger = Phone(OTHER, 'Чужой')

    def recognize(phone=master, data=JPEG, kind='image/jpeg'):
        return phone.post('/m/arrival/recognize',
                          files={'photo': ('car.jpg', data, kind)})

    print()
    print('=== Включение: по направлениям, из настроек цеха ===')
    cars = master.http.get('/m/cars').json()
    check('по умолчанию выключено — «Новой машины» нет',
          cars['arrival_directions'] == [], str(cars.get('arrival_directions')))
    answer = recognize()
    check('выключено — снимок не принимается', answer.status_code == 400
          and 'выключен' in answer.json()['detail'], answer.text)
    # Цех включает шиномонтаж; мойку включает, но мойки на точке нет
    http.post('/sync/push', headers=KEY, json={'settings': {
        'arrival_photo_tire': '1', 'arrival_photo_wash': '1'}})
    cars = master.http.get('/m/cars').json()
    check('мойка точкой не ведётся — только шиномонтаж',
          cars['arrival_directions'] == ['tire'], str(cars['arrival_directions']))

    print()
    print('=== Телефон: снимок → номер ===')
    answer = http.post('/m/arrival/recognize',
                       files={'photo': ('car.jpg', JPEG, 'image/jpeg')})
    check('без пропуска — 401', answer.status_code == 401, str(answer.status_code))

    answers.append(('А123ВВ777', 0.93))
    answer = recognize()
    check('снимок принят', answer.status_code == 200, answer.text[:300])
    data = answer.json()
    check('номер распознан', data['plate'] == 'А123ВВ777'
          and data['plate_complete'] is True, str(data))
    check('есть в базе: кто, какая, когда',
          data['known'] == {'client_name': 'Иван Петров', 'car': 'легковой · R17',
                            'last_visit': '2026-04-12'}, str(data['known']))
    check('записан на сегодня', data['appointment'] == {'time': '14:30',
                                                       'direction': 'tire'},
          str(data['appointment']))
    check('мойки нет — выбора нет', data['wash_enabled'] is False
          and data['directions_allowed'] == ['tire'], str(data))
    first_photo = data['photo_id']
    db = SessionLocal()
    photo = db.get(OrderPhoto, first_photo)
    check('снимок — обложка без наряда',
          photo.kind == 'cover' and photo.order_local_id is None
          and photo.license_plate == 'А123ВВ777' and photo.author == 'Андрей',
          f'{photo.kind} {photo.order_local_id} {photo.license_plate}')
    check('файл на диске', os.path.exists(photos.full_path(photo)))
    db.close()
    check('клиенту ничего не ушло', to_telegram == [], str(to_telegram))

    answer = recognize(data=b'%PDF', kind='application/pdf')
    check('не фото — 400', answer.status_code == 400, str(answer.status_code))

    answers.append((None, 0.0))
    data = recognize().json()
    check('не прочитался — пусто, а снимок сохранён',
          data['plate'] is None and data['photo_id'] and data['known'] is None
          and data['appointment'] is None, str(data))
    unread_photo = data['photo_id']

    answers.append(('А123ВВ', 0.4))
    data = recognize().json()
    check('без региона — дополнен по базе', data['plate'] == 'А123ВВ777'
          and data['plate_complete'] is True, str(data))

    answers.append(('Е901ТХ', 0.4))
    data = recognize().json()
    check('без региона и нет в базе — как есть, просим дописать',
          data['plate'] == 'Е901ТХ' and data['plate_complete'] is False, str(data))

    db = SessionLocal()
    shop_settings.set_value(db, 'direction_wash', '1', shop=shop_id)
    db.close()
    answers.append(('К555КК77', 0.9))
    data = recognize().json()
    check('мойка включена — выбор есть', data['wash_enabled'] is True
          and data['directions_allowed'] == ['tire', 'wash'], str(data))
    check('новой машины в базе нет', data['known'] is None)
    wash_photo = data['photo_id']

    hints = master.post('/m/arrival/hints', json={'plate': 'a123bb777'}).json()
    check('подсказки для вписанного руками номера',
          hints['known']['client_name'] == 'Иван Петров'
          and hints['appointment']['time'] == '14:30', str(hints))

    print()
    print('=== «Создать наряд» ===')
    answer = master.post('/m/arrival', json={'photo_id': wash_photo, 'plate': ' ',
                             'directions': ['tire']})
    check('без номера — 400', answer.status_code == 400
          and 'номер' in answer.json()['detail'], answer.text)
    answer = stranger.post('/m/arrival', json={'photo_id': wash_photo, 'plate': 'К555КК77'})
    check('чужой снимок — 400', answer.status_code == 400, answer.text)
    answer = master.post('/m/arrival', json={'photo_id': wash_photo, 'plate': 'k555kk 77',
                             'directions': ['wash', 'tire']})
    check('принято', answer.status_code == 200 and answer.json()['ok'] is True,
          answer.text)
    wash_arrival = answer.json()['arrival_id']
    answer = master.post('/m/arrival', json={'photo_id': wash_photo, 'plate': 'К555КК77'})
    check('тот же снимок второй раз — 400', answer.status_code == 400)

    db = SessionLocal()
    row = db.get(Arrival, wash_arrival)
    check('номер приведён к виду, направления по порядку',
          row.plate == 'К555КК77' and row.directions == 'tire,wash',
          f'{row.plate} {row.directions}')
    check('снимок знает поправленный номер',
          db.get(OrderPhoto, wash_photo).license_plate == 'К555КК77')
    shop_settings.set_value(db, 'direction_wash', '0', shop=shop_id)
    db.close()

    answer = master.post('/m/arrival', json={'photo_id': first_photo, 'plate': 'А123ВВ777',
                             'directions': ['wash']})
    check('мойка выключена — мойку не принимаем', answer.status_code == 400
          and 'мойка' in answer.json()['detail'], answer.text)
    answer = master.post('/m/arrival', json={'photo_id': first_photo, 'plate': 'А123ВВ777'})
    check('направление не прислали — включённое', answer.status_code == 200,
          answer.text)
    tire_arrival = answer.json()['arrival_id']
    db = SessionLocal()
    check('направление — шиномонтаж',
          db.get(Arrival, tire_arrival).directions == 'tire')
    db.close()

    answer = master.post('/m/arrival', json={'photo_id': unread_photo, 'plate': 'Е901ТХ50'})
    unread_arrival = answer.json()['arrival_id']

    print()
    print('=== Цех ===')
    answer = http.get('/sync/arrivals')
    check('без ключа — 401', answer.status_code == 401)
    listed = http.get('/sync/arrivals', headers=KEY).json()['arrivals']
    check('ждут три машины', [row['id'] for row in listed]
          == [wash_arrival, tire_arrival, unread_arrival], str(listed))
    row = next(item for item in listed if item['id'] == wash_arrival)
    check('поля как в docs/order_photo.md',
          row['plate'] == 'К555КК77' and row['directions'] == ['tire', 'wash']
          and row['photo_id'] == wash_photo and row['created_at'], str(row))
    check('чужая точка своих машин не видит',
          http.get('/sync/arrivals', headers=OTHER).json()['arrivals'] == [])
    answer = http.get(f'/sync/arrivals/{tire_arrival}/photo', headers=OTHER)
    check('и снимок чужой машины — 404', answer.status_code == 404)
    answer = http.post(f'/sync/arrivals/{tire_arrival}/done', headers=OTHER,
                       json={'order_local_id': 5})
    check('и снять чужую машину нельзя', answer.status_code == 404)
    answer = http.get(f'/sync/arrivals/{tire_arrival}/photo', headers=KEY)
    check('свой снимок — JPEG', answer.status_code == 200
          and answer.content == JPEG
          and answer.headers['content-type'].startswith('image/jpeg'))

    answer = http.post(f'/sync/arrivals/{tire_arrival}/done', headers=KEY,
                       json={'order_local_id': 1243})
    check('наряд создан', answer.status_code == 200 and answer.json()['ok'])
    answer = http.post(f'/sync/arrivals/{wash_arrival}/done', headers=KEY,
                       json={'order_local_id': None})
    check('окно закрыто', answer.status_code == 200)
    listed = http.get('/sync/arrivals', headers=KEY).json()['arrivals']
    check('разобранные больше не всплывают',
          [row['id'] for row in listed] == [unread_arrival], str(listed))

    db = SessionLocal()
    photo = db.get(OrderPhoto, first_photo)
    check('снимок стал обложкой наряда',
          photo.order_local_id == 1243 and photo.kind == 'cover'
          and photo.client_id == client_id, f'{photo.order_local_id} {photo.kind}')
    check('у закрытого окна снимок без наряда',
          db.get(OrderPhoto, wash_photo).order_local_id is None)
    arrival = db.get(Arrival, tire_arrival)
    check('у машины записан наряд', arrival.order_local_id == 1243
          and arrival.done_at is not None)
    # Машина ждёт дольше двух часов — уже не всплывает
    db.get(Arrival, unread_arrival).created_at = shop_now() - timedelta(hours=3)
    db.commit()
    db.close()
    check('старше двух часов — не всплывает',
          http.get('/sync/arrivals', headers=KEY).json()['arrivals'] == [])

    print()
    print('=== Обложка — не «фото от мастера» ===')
    db = SessionLocal()
    sent = photos.tell_client(db, db.query(Shop).get(shop_id),
                              db.get(OrderPhoto, first_photo))
    db.close()
    check('клиенту обложка не уходит', sent is None and to_telegram == [],
          str(to_telegram))
    # Снимок мастера по тому же наряду — для сравнения
    master.post('/m/photo', files={'file': ('p.jpg', JPEG, 'image/jpeg')},
              data={'order_local_id': '1243', 'license_plate': 'А123ВВ777',
                    'comment': 'Грыжа'})
    check('снимок мастера клиенту ушёл', len(to_telegram) == 1, str(to_telegram))
    listed = http.get('/sync/photos?order_local_id=1243', headers=KEY).json()
    check('в снимках мастеров по наряду обложки нет',
          len(listed) == 1 and listed[0]['comment'] == 'Грыжа', str(listed))
    me = {'Authorization': f'Bearer {create_token(client_id)}'}
    mine = http.get('/history/photos', headers=me)
    check('в кабинете клиента обложки нет', mine.status_code == 200
          and [row['comment'] for row in mine.json()] == ['Грыжа'], mine.text[:200])
    db = SessionLocal()
    cover = db.get(OrderPhoto, first_photo)
    cover.sent_at = shop_now()      # даже если бы её кто-то пометил отправленной
    db.commit()
    db.close()
    mine = http.get('/history/photos', headers=me).json()
    check('и помеченная отправленной — тоже нет', len(mine) == 1, str(mine))
    from app.security import photo_key
    answer = http.get(f'/history/photo/{first_photo}?key={photo_key(first_photo, client_id)}')
    check('файл обложки по клиентской ссылке не открывается',
          answer.status_code == 404, str(answer.status_code))

    print()
    print('=== Дашборд: обложка у наряда ===')
    http.post('/sync/push', headers=KEY, json={
        'visits': [{'local_id': 1243, 'license_plate': 'А123ВВ777',
                    'visited_at': '2026-10-26T14:52:00', 'total_amount': 4800,
                    'payment_method': 'cash'},
                   {'local_id': 1244, 'license_plate': 'К555КК77',
                    'visited_at': '2026-10-26T15:10:00', 'total_amount': 2900,
                    'payment_method': 'card'}]})
    rows = http.get('/dashboard/orders?from=2026-10-26&to=2026-10-26',
                    headers=owner).json()
    by_id = {row['local_id']: row for row in rows}
    check('у наряда с обложкой — cover_url', by_id[1243]['cover_url']
          and by_id[1244]['cover_url'] is None, str(rows)[:300])
    card = http.get('/dashboard/orders/1243', headers=owner).json()
    check('и в карточке', card['cover_url'] == by_id[1243]['cover_url'],
          str(card.get('cover_url')))
    answer = http.get(card['cover_url'])
    check('по ссылке — снимок', answer.status_code == 200 and answer.content == JPEG,
          str(answer.status_code))
    answer = http.get(card['cover_url'].replace('key=', 'key=0'))
    check('подделанная ссылка — 403', answer.status_code == 403)
    answer = http.get(f'/dashboard/photo/{first_photo}?until=1&key=abc')
    check('просроченная — 403', answer.status_code == 403)
    other_url = card['cover_url'].replace(f'/photo/{first_photo}?',
                                          f'/photo/{wash_photo}?')
    answer = http.get(other_url)
    check('чужой номер снимка с той же подписью — 403', answer.status_code == 403)

    print()
    print('=== Удаление точки забирает её машины ===')
    # У второй точки наряд по фото включён только для мойки
    http.post('/sync/push', headers=OTHER, json={'settings': {
        'direction_wash': '1', 'arrival_photo_tire': '0',
        'arrival_photo_wash': '1'}})
    check('только мойка — у телефона только мойка',
          stranger.http.get('/m/cars').json()['arrival_directions'] == ['wash'])
    answer = stranger.post('/m/arrival', json={'photo_id': None, 'plate': 'О777ОО77',
                                               'directions': ['tire']})
    check('шиномонтаж выключен — отказ', answer.status_code == 400
          and 'шиномонтаж' in answer.json()['detail'], answer.text)
    answer = stranger.post('/m/arrival', json={'photo_id': None, 'plate': 'О777ОО77'})
    check('телефон другой точки подаёт машину без снимка',
          answer.status_code == 200, answer.text)
    db = SessionLocal()
    check('единственное включённое — мойка',
          db.get(Arrival, answer.json()['arrival_id']).directions == 'wash')
    db.close()
    db = SessionLocal()
    tenancy.drop_shop(db, db.get(Shop, other_id))
    left = db.query(Arrival).filter(Arrival.shop_id == other_id).count()
    mine = db.query(Arrival).filter(Arrival.shop_id == shop_id).count()
    db.close()
    check('машин удалённой точки нет', left == 0)
    check('свои на месте', mine == 3, str(mine))

    print()
    print('=== Уборка старых снимков не спотыкается о машины ===')
    db = SessionLocal()
    for row in db.query(OrderPhoto).all():
        row.created_at = datetime(2024, 1, 1)
    db.commit()
    gone = photos.drop_old(db, months=12)
    left = db.query(Arrival).count()
    db.close()
    check('старые снимки убраны вместе с машинами', gone >= 5 and left == 0,
          f'{gone} {left}')

    print()
    print('=== Проверка номеров с телефона владельца ===')
    check('страница открывается', http.get('/d/plates').status_code == 200)
    jpeg = b'\xff\xd8\xff\xe0' + b'0' * 64
    answer = http.post('/dashboard/plates/check', files={'photo': ('a.jpg', jpeg, 'image/jpeg')})
    check('без входа — нельзя', answer.status_code == 401, answer.text)
    db = SessionLocal()
    photos_before = db.query(OrderPhoto).count()
    db.close()
    answers.append(('А123ВВ777', 0.93))
    answer = http.post('/dashboard/plates/check', headers=owner,
                       files={'photo': ('a.jpg', jpeg, 'image/jpeg')})
    data = answer.json()
    check('номер прочитан, время посчитано', answer.status_code == 200
          and data['plate'] == 'А123ВВ777' and data['plate_complete'] and 'ms' in data, answer.text)
    answer = http.post('/dashboard/plates/check', headers=owner,
                       files={'photo': ('a.txt', b'text', 'text/plain')})
    check('не фото — отказ', answer.status_code == 400, answer.text)
    db = SessionLocal()
    check('снимок проверки не сохраняется', db.query(OrderPhoto).count() == photos_before)
    db.close()

finish()
