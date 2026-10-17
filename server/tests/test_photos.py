"""
Фото из цеха: от телефона мастера до клиента.

Фотография рождается на телефоне мастера. Всякий способ «сначала
перенести на компьютер» означает, что её не отправят никогда: на
потоке лишних шагов не делают. Поэтому путь здесь один и короткий —
снял, нажал, клиент получил.

Проверяем то, что ломается молча:

  · чужой телефон не должен попасть в цех;
  · одноразовый ключ из QR не должен работать дважды;
  · фото не должно уйти не тому клиенту;
  · сбой доставки не должен выглядеть как успех;
  · ссылка на картинку не должна открываться подбором номера.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_photos_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

_photo_dir = os.path.join(tempfile.gettempdir(), 'tire_photos_files')

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-photos'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-photos'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_PHOTO_DIR'] = _photo_dir

import shutil

if os.path.exists(_photo_dir):
    shutil.rmtree(_photo_dir)

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Account, Car, Client, MasterDevice, OrderPhoto, Shop)
from app.services import notices, photos, telegram, webpush

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


# Единственный выход наружу подменяем
to_telegram = []


def fake_photo(account, chat_id, data, caption=None):
    to_telegram.append((chat_id, len(data), caption))


telegram.send_photo = fake_photo
photos.telegram.send_photo = fake_photo

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

# Самый маленький настоящий JPEG: заголовок и конец. Содержимое нам
# неважно, важно что это байты, которые мы кладём и отдаём обратно
JPEG = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffd9')

with TestClient(app) as client:
    db = SessionLocal()
    shop = db.query(Shop).first()
    account_id = shop.account_id
    shop_id = shop.id

    account = db.query(Account).filter(Account.id == account_id).first()
    account.telegram_bot_token = 'test-token'

    owner = Client(account_id=account_id, phone='79160000001',
                   name='Пётр', telegram_chat_id='555')
    db.add(owner)
    db.commit()

    db.add(Car(account_id=account_id, license_plate='А123ВВ777',
               client_id=owner.id))
    # Вторая машина ни за кем не записана
    db.add(Car(account_id=account_id, license_plate='К900ОР99'))
    db.commit()
    owner_id = owner.id
    db.close()

    print('=== Цех прислал, какие машины в работе ===')
    client.post('/sync/push', headers=KEY, json={'queue': {
        'cars_in_work': 1, 'cars_waiting': 1, 'open_posts': 2,
        'shift_is_open': True,
        'cars': [
            {'local_id': 101, 'license_plate': 'а123вв777', 'state': 'work'},
            {'local_id': 102, 'license_plate': 'К900ОР99', 'state': 'waiting'},
        ]}})

    print()
    print('=== Без пропуска телефон ничего не видит ===')
    refused = client.get('/m/cars')
    check('отказано', refused.status_code == 401, str(refused.status_code))
    check('сказано, что делать',
          'QR' in refused.json()['detail'], refused.json()['detail'])

    print()
    print('=== Приёмщик показал код ===')
    link = client.post('/sync/master-link', headers=KEY).json()
    check('ключ выдан', bool(link['link']), str(link))
    check('сказано, сколько живёт', link['minutes'] > 0, str(link))

    print()
    print('=== Телефон подключился ===')
    # Отдельный клиент — как отдельный телефон, со своими куками
    http_master = TestClient(app)
    connected = http_master.post('/m/connect',
                                 json={'link': link['link'], 'name': 'Иван'})
    check('приняли', connected.status_code == 200, str(connected.json()))
    master = {'X-Master-Key': connected.json()['key']}
    check('пропуск выдан', bool(connected.json()['key']))

    print()
    print('=== Тот же код второй раз не работает ===')
    # Код висит на экране в цеху, его видит кто угодно из стоящих рядом
    again = client.post('/m/connect', json={'link': link['link']})
    check('отказано', again.status_code == 410, str(again.status_code))

    print()
    print('=== Выдуманный код тоже ===')
    made_up = client.post('/m/connect', json={'link': 'abcdefghij'})
    check('отказано', made_up.status_code == 410, str(made_up.status_code))

    print()
    print('=== Мастер видит машины ===')
    cars = client.get('/m/cars', headers=master).json()
    plates = [row['license_plate'] for row in cars['cars']]
    check('обе машины на месте', plates == ['А123ВВ777', 'К900ОР99'],
          str(plates))
    check('видно, кто на посту',
          cars['cars'][0]['state'] == 'work', str(cars['cars'][0]))
    check('имя мастера помним', cars['name'] == 'Иван', str(cars['name']))

    print()
    print('=== Снял и отправил ===')
    answer = client.post('/m/photo', headers=master,
                         files={'file': ('photo.jpg', JPEG, 'image/jpeg')},
                         data={'order_local_id': '101',
                               'license_plate': 'А123ВВ777',
                               'comment': 'Грыжа на боковине, заднее левое'})

    check('приняли', answer.status_code == 200, str(answer.json()))
    check('отправлено клиенту', answer.json()['sent'] is True,
          str(answer.json()))
    check('ушло в Телеграм', answer.json()['channel'] == 'telegram',
          str(answer.json()))
    check('в его чат', to_telegram and to_telegram[-1][0] == '555',
          str(to_telegram[-1:]))
    check('картинкой, а не ссылкой', to_telegram[-1][1] == len(JPEG),
          str(to_telegram[-1][1]))
    check('с комментарием мастера',
          'Грыжа' in (to_telegram[-1][2] or ''), str(to_telegram[-1][2]))

    db = SessionLocal()
    photo = db.query(OrderPhoto).first()
    check('фото привязано к наряду', photo.order_local_id == 101,
          str(photo.order_local_id))
    check('и к владельцу машины', photo.client_id == owner_id,
          str(photo.client_id))
    check('кто снял — записано', photo.author == 'Иван', str(photo.author))
    check('файл лёг на диск', os.path.exists(photos.full_path(photo)),
          photos.full_path(photo))
    photo_id = photo.id
    db.close()

    print()
    print('=== Приёмщик видит это в наряде ===')
    listed = client.get('/sync/photos?order_local_id=101', headers=KEY).json()
    check('один снимок', len(listed) == 1, str(len(listed)))
    check('видно, что ушло', listed[0]['sent_at'] is not None, str(listed[0]))
    check('и чем', listed[0]['channel'] == 'telegram', str(listed[0]))
    check('и кто снял', listed[0]['author'] == 'Иван', str(listed[0]))

    print()
    print('=== Машина ничья — фото сохраняем, но честно говорим ===')
    answer = client.post('/m/photo', headers=master,
                         files={'file': ('photo.jpg', JPEG, 'image/jpeg')},
                         data={'order_local_id': '102',
                               'license_plate': 'К900ОР99'})
    check('приняли', answer.status_code == 200, str(answer.json()))
    check('но не отправили', answer.json()['sent'] is False,
          str(answer.json()))
    check('причина названа', 'записана' in answer.json()['reason'],
          answer.json()['reason'])

    db = SessionLocal()
    check('снимок всё равно сохранён',
          db.query(OrderPhoto).count() == 2,
          str(db.query(OrderPhoto).count()))
    db.close()

    print()
    print('=== Не картинку не принимаем ===')
    bad = client.post('/m/photo', headers=master,
                      files={'file': ('note.txt',
                                      'привет'.encode('utf-8'),
                                      'text/plain')},
                      data={'order_local_id': '101'})
    check('отказано', bad.status_code == 400, str(bad.status_code))
    check('сказано, почему', 'фотограф' in bad.json()['detail'].lower(),
          bad.json()['detail'])

    print()
    print('=== Сбой доставки не выдаётся за успех ===')
    def broken(account, chat_id, data, caption=None):
        raise telegram.TelegramError('бот заблокирован')

    photos.telegram.send_photo = broken

    answer = client.post('/m/photo', headers=master,
                         files={'file': ('photo.jpg', JPEG, 'image/jpeg')},
                         data={'order_local_id': '101',
                               'license_plate': 'А123ВВ777'}).json()
    check('ответ честный', answer['sent'] is False, str(answer))
    check('причина названа', 'заблокирован' in answer['reason'],
          answer['reason'])

    photos.telegram.send_photo = fake_photo

    print()
    print('=== Картинку не открыть подбором ===')
    open_try = client.get(f'/m/photo/{photo_id}')
    check('без ключа нельзя', open_try.status_code == 403,
          str(open_try.status_code))

    open_try = client.get(f'/m/photo/{photo_id}?key=подобранный')
    check('с выдуманным тоже', open_try.status_code == 403,
          str(open_try.status_code))

    with_master = client.get(f'/m/photo/{photo_id}',
                             params={'key': connected.json()['key']})
    check('своему телефону отдаём', with_master.status_code == 200,
          str(with_master.status_code))
    check('это тот же файл', with_master.content == JPEG,
          str(len(with_master.content)))

    with_sync = client.get(f'/m/photo/{photo_id}',
                           params={'key': os.environ['SERVER_SYNC_KEY']})
    check('и программе цеха', with_sync.status_code == 200,
          str(with_sync.status_code))

    print()
    print('=== Уехавшая машина пропадает из списка ===')
    client.post('/sync/push', headers=KEY, json={'queue': {
        'cars_in_work': 0, 'cars_waiting': 0, 'open_posts': 2,
        'shift_is_open': True, 'cars': []}})

    cars = client.get('/m/cars', headers=master).json()
    check('список пуст', cars['cars'] == [], str(cars['cars']))

    print()
    print('=== Данные страницы стёрты — телефон всё равно узнаём ===')
    # Safari стирает данные страницы, если её не открывали около недели.
    # Пропуск лежит в куке, которую ставит сервер, — её эта чистка не
    # трогает. Мастер не должен идти к приёмщику за QR после отпуска
    check('при подключении поставлена кука',
          'tire_master' in http_master.cookies, str(dict(http_master.cookies)))

    by_cookie = http_master.get('/m/cars')
    check('без заголовка, по одной куке — пускают',
          by_cookie.status_code == 200, str(by_cookie.status_code))

    stranger = TestClient(app)
    no_cookie = stranger.get('/m/cars')
    check('а без куки и без заголовка — нет',
          no_cookie.status_code == 401, str(no_cookie.status_code))

    print()
    print('=== Пропуск продлевается при каждом заходе ===')
    # Иначе через год он кончился бы у того, кто пользуется каждый день
    renewed = http_master.get('/m/cars')
    cookie_header = renewed.headers.get('set-cookie', '')
    check('кука выставлена заново', 'tire_master=' in cookie_header,
          cookie_header[:80])
    check('на год', 'Max-Age=31536000' in cookie_header, cookie_header[:160])
    check('страница её не читает', 'HttpOnly' in cookie_header, cookie_header)

    print()
    print('=== Снимок отправляется и по куке ===')
    by_cookie_photo = http_master.post(
        '/m/photo',
        files={'file': ('photo.jpg', JPEG, 'image/jpeg')},
        data={'order_local_id': '101', 'license_plate': 'А123ВВ777'})
    check('принят', by_cookie_photo.status_code == 200,
          str(by_cookie_photo.status_code))

    print()
    print('=== Отозвали телефон — больше не пускаем ===')
    db = SessionLocal()
    device = db.query(MasterDevice).first()
    device.is_active = False
    db.commit()
    db.close()

    after = client.get('/m/cars', headers=master)
    check('отказано', after.status_code == 401, str(after.status_code))

finish()
