"""
Кабинет мастера (решение владельца 27.10.2026).

Мастер входит своим именем и ПИН, видит свои машины сверху, шлёт клиенту
фото и видео из наряда, жмёт «Начал» / «Готово», предлагает работу на
согласование и видит свой заработок, если владелец включил.

Проверяем то, что ломается молча:

  · чужой ПИН не пускает, перебор ПИН останавливается;
  · «мои» машины — по мастерам наряда, а не по догадке;
  · видео доходит кусками и целиком, чужая загрузка не продолжается;
  · «Готово» говорит клиенту сразу, цех узнаёт событием;
  · согласие клиента доходит до цеха, молчание — напоминанием;
  · заработок закрыт выключателем и виден только свой;
  · видео живёт две недели, предложение остаётся без снимка.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_master_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)
_photo_dir = os.path.join(tempfile.gettempdir(), 'tire_master_files')
shutil.rmtree(_photo_dir, ignore_errors=True)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-master-cabinet-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-master'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_PHOTO_DIR'] = _photo_dir
os.environ['SERVER_CORS_ORIGINS'] = 'https://lk.rif-test.ru,https://admin.rif-test.ru'
os.environ.pop('SERVER_PLATFORM_DOMAIN', None)
os.environ.pop('SERVER_HOME_HOSTS', None)

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Account, Car, Client, MasterEvent, OrderPhoto, SalaryAccrual,
                        SalaryPayout, Shop, Visit, WorkOffer)
from app.services import master, notices, photos, telegram
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
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


# Наружу ничего не уходит: телеграм подменён
sent = []


def fake_photo(account, chat_id, data, caption=None):
    sent.append(('photo', chat_id, len(data), caption))


def fake_video(account, chat_id, data, caption=None):
    sent.append(('video', chat_id, len(data), caption))


def fake_message(account, chat_id, text, buttons=None):
    sent.append(('message', chat_id, text, buttons))


telegram.send_photo = fake_photo
telegram.send_video = fake_video
telegram.send_message = fake_message

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
JPEG = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffd9')


def pin_hash(pin):
    # Так же считает программа цеха (services/employee_service.py)
    return hashlib.sha256(f'tire-master-pin:{pin}'.encode('utf-8')).hexdigest()


with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_id, account_id = shop.id, shop.account_id
    account = db.get(Account, account_id)
    account.telegram_bot_token = 'test-token'
    owner = Client(account_id=account_id, phone='79160000001', name='Иван',
                   telegram_chat_id='555')
    db.add(owner)
    db.commit()
    db.add(Car(account_id=account_id, license_plate='А123ВВ777', client_id=owner.id))
    db.add(Car(account_id=account_id, license_plate='К900ОР99'))
    db.commit()
    owner_id = owner.id
    db.close()

    print('=== Цех прислал сотрудников с ПИН, машины и прайс ===')
    pushed = http.post('/sync/push', headers=KEY, json={
        'employees': [
            {'local_id': 1, 'name': 'Сергей', 'pin_hash': pin_hash('4827')},
            {'local_id': 2, 'name': 'Алексей', 'pin_hash': pin_hash('9153')},
            {'local_id': 3, 'name': 'Рустам'},
        ],
        'services': [
            {'local_id': 11, 'name': 'Замена шины', 'prices': {'R16': 650, 'R17': 700}},
            {'local_id': 12, 'name': 'Замена вентиля', 'prices': {'R16': 200}},
            {'local_id': 13, 'name': 'Мойка кузова', 'direction': 'wash',
             'prices': {'sedan': 500}},
            {'local_id': 14, 'name': 'Правка диска', 'prices': {}},
        ],
        'queue': {'cars_in_work': 1, 'cars_waiting': 1, 'open_posts': 2, 'shift_is_open': True,
                  'cars': [
                      {'local_id': 101, 'license_plate': 'А123ВВ777', 'state': 'work',
                       'masters': '1', 'car': 'Kia Rio', 'client_name': 'Иван',
                       'wheel_diameter': 'R16', 'services': 'Шиномонтаж R16\nБалансировка',
                       'post': 2},
                      {'local_id': 102, 'license_plate': 'К900ОР99', 'state': 'waiting',
                       'masters': '2', 'wheel_diameter': '17'},
                  ]}})
    check('обмен принят', pushed.status_code == 200, pushed.text[:200])

    pushed = http.post('/sync/push', headers=KEY, json={
        'employees': [{'local_id': 1, 'name': 'Сергей'}]})
    db = SessionLocal()
    from app.models import ShopEmployee
    sergey = db.query(ShopEmployee).filter(ShopEmployee.local_id == 1).first()
    check('старая программа без pin_hash ПИН не стирает', sergey.pin_hash == pin_hash('4827'))
    db.close()

    link = http.post('/sync/master-link', headers=KEY).json()['link']
    phone = TestClient(app)
    connected = phone.post('/m/connect', json={'link': link})
    check('телефон подключён', connected.status_code == 200, connected.text)

    print('\n=== Кто вы ===')
    me = phone.get('/m/me').json()
    check('видит сотрудников точки, и у кого есть ПИН',
          {(p['name'], p['has_pin']) for p in me['employees']}
          == {('Сергей', True), ('Алексей', True), ('Рустам', False)}, str(me['employees']))
    check('пока не вошёл', me['employee'] is None)
    check('заработок выключен, пока владелец не включил', me['salary_visible'] is False)

    cars = phone.get('/m/cars').json()['cars']
    check('без входа «моих» нет, но машины видны и фото слать можно',
          len(cars) == 2 and not any(car['mine'] for car in cars), str(cars)[:200])
    refused = phone.post('/m/order/101/start')
    check('без входа «Начал» не нажать', refused.status_code == 400, refused.text)

    bad = phone.post('/m/login', json={'employee_local_id': 1, 'pin': '1111'})
    check('чужой ПИН не пускает', bad.status_code == 400 and 'Неверный' in bad.text, bad.text)
    nopin = phone.post('/m/login', json={'employee_local_id': 3, 'pin': '1234'})
    check('без ПИН — подсказка, где его поставить',
          nopin.status_code == 400 and 'ПИН для телефона' in nopin.text, nopin.text)

    for _ in range(4):
        phone.post('/m/login', json={'employee_local_id': 1, 'pin': '0000'})
    locked = phone.post('/m/login', json={'employee_local_id': 1, 'pin': '4827'})
    check('после 5 неверных даже верный ПИН ждёт 15 минут',
          locked.status_code == 400 and 'Попробуйте через' in locked.text, locked.text)
    db = SessionLocal()
    from app.models import MasterDevice
    device = db.query(MasterDevice).first()
    device.locked_until = None
    db.commit()
    db.close()

    ok = phone.post('/m/login', json={'employee_local_id': 1, 'pin': '4827'})
    check('свой ПИН пускает', ok.status_code == 200 and ok.json()['employee']['name'] == 'Сергей',
          ok.text[:200])

    print('\n=== Мои машины ===')
    cars = phone.get('/m/cars').json()
    check('имя мастера в шапке', cars['name'] == 'Сергей')
    first = cars['cars'][0]
    check('своя машина сверху и отмечена',
          first['order_local_id'] == 101 and first['mine'] and not cars['cars'][1]['mine'],
          str(cars['cars'])[:200])
    check('с составом наряда и постом',
          first['car'] == 'Kia Rio' and first['services'] == ['Шиномонтаж R16', 'Балансировка']
          and first['post'] == 2, str(first))
    check('у чужой машины видно, чья она', cars['cars'][1]['masters'] == ['Алексей'])

    order = phone.get('/m/order/101').json()
    check('в наряде — клиент и куда уйдёт',
          order['client']['name'] == 'Иван' and order['client']['channel'] == 'telegram', str(order['client']))
    offerable = {item['name']: item['price'] for item in order['services_offer']}
    check('прайс по радиусу наряда: R16 и без мойки и без цены',
          offerable == {'Замена шины': 650, 'Замена вентиля': 200}, str(offerable))
    check('уехавшая машина — понятный отказ', phone.get('/m/order/999').status_code == 404)

    print('\n=== Фото с подписью ===')
    answer = phone.post('/m/photo', files={'file': ('a.jpg', JPEG, 'image/jpeg')},
                        data={'order_local_id': '101', 'license_plate': 'А123ВВ777',
                              'comment': 'Грыжа на боковине · заднее левое'})
    check('фото ушло в телеграм', answer.json().get('sent') is True, answer.text)
    check('в подписи — кто прислал',
          sent and 'Мастер Сергей прислал фото' in sent[-1][3], str(sent[-1:]))
    db = SessionLocal()
    photo = db.query(OrderPhoto).order_by(OrderPhoto.id.desc()).first()
    check('фото записано за мастером', photo.employee_local_id == 1 and photo.author == 'Сергей')
    photo_id = photo.id
    db.close()

    print('\n=== Видео кусками ===')
    video = b'\x00\x00\x00\x18ftypmp42' + os.urandom(9 * 1024 * 1024)
    start = phone.post('/m/video/start', json={'order_local_id': 101, 'license_plate': 'А123ВВ777',
                                               'comment': 'Порез', 'content_type': 'video/mp4;codecs=avc1',
                                               'size': len(video)}).json()
    check('загрузка начата', bool(start.get('upload')), str(start))
    stranger = TestClient(app)
    link2 = http.post('/sync/master-link', headers=KEY).json()['link']
    stranger.post('/m/connect', json={'link': link2})
    foreign = stranger.post(f"/m/video/part?upload={start['upload']}&offset=0", content=b'x')
    check('чужой телефон чужую загрузку не продолжит', foreign.status_code in (400, 401), foreign.text)

    offset, step = 0, start['part_bytes']
    while offset < len(video):
        part = phone.post(f"/m/video/part?upload={start['upload']}&offset={offset}",
                          content=video[offset:offset + step])
        if part.status_code != 200:
            break
        offset = part.json()['size']
    check('все куски приняты', offset == len(video), str(offset))
    done = phone.post(f"/m/video/finish?upload={start['upload']}").json()
    check('видео ушло клиенту файлом', done.get('sent') is True and sent[-1][0] == 'video'
          and sent[-1][2] == len(video), str(done))
    video_id = done['id']

    huge = phone.post('/m/video/start', json={'content_type': 'video/mp4', 'size': 500 * 1024 * 1024})
    check('полгигабайта не принимаем — снимите короче', huge.status_code == 400, huge.text)
    not_video = phone.post('/m/video/start', json={'content_type': 'image/jpeg', 'size': 10})
    check('не видео — отказ', not_video.status_code == 400, not_video.text)

    db = SessionLocal()
    row = db.get(OrderPhoto, video_id)
    row.size = 60 * 1024 * 1024
    row.content_type = 'video/webm'
    client_row = db.get(Client, owner_id)
    db.commit()
    count = len(sent)
    photos.tell_client(db, db.get(Shop, shop_id), row)
    check('webm или больше 50 МБ — ссылкой «Смотреть видео»',
          len(sent) == count + 1 and sent[-1][0] == 'message'
          and sent[-1][3][0][0] == 'Смотреть видео' and '/history/photo/' in sent[-1][3][0][1],
          str(sent[-1:])[:300])
    db.close()

    print('\n=== Клиент смотрит в кабинете ===')
    from app.security import create_token
    client_auth = {'Authorization': f'Bearer {create_token(owner_id)}'}
    media = http.get('/history/photos', headers=client_auth).json()
    check('в кабинете фото и видео',
          {item['media'] for item in media} == {'photo', 'video'}, str(media)[:200])
    video_item = [item for item in media if item['media'] == 'video'][0]
    file = http.get(video_item['url'])
    check('видео отдаётся видео, а не картинкой',
          file.status_code == 200 and file.headers['content-type'].startswith('video/'),
          file.headers.get('content-type'))
    check('и кусками — на айфоне плеер иначе не играет',
          http.get(video_item['url'], headers={'Range': 'bytes=0-99'}).status_code == 206)
    order = phone.get('/m/order/101').json()
    check('мастер видит «посмотрел»',
          any(item['id'] == video_id and item['viewed'] for item in order['media']),
          str(order['media'])[:200])

    print('\n=== Предложить работу ===')
    empty = phone.post('/m/offer', json={'order_local_id': 101, 'services': []})
    check('без услуги — отказ', empty.status_code == 400, empty.text)
    foreign = phone.post('/m/offer', json={'order_local_id': 101, 'services': [13, 14]})
    check('мойку без класса и услугу без цены не предложить', foreign.status_code == 400, foreign.text)
    nobody = phone.post('/m/offer', json={'order_local_id': 102, 'services': [11]})
    check('машина ни за кем — предложить некому', nobody.status_code == 400
          and 'некому' in nobody.text, nobody.text)

    count = len(sent)
    offer = phone.post('/m/offer', json={'order_local_id': 101, 'services': [11, 12],
                                         'comment': 'Ездить опасно', 'photo_id': photo_id})
    check('предложение отправлено', offer.status_code == 200 and offer.json()['sent'], offer.text[:200])
    offer = offer.json()
    check('сумма — по прайсу', offer['total'] == 850 and len(offer['items']) == 2, str(offer))
    message = sent[-1] if len(sent) > count else None
    check('в телеграме — кнопка «Посмотреть и ответить» на кабинет',
          message and message[0] == 'message' and message[3][0][0] == 'Посмотреть и ответить'
          and message[3][0][1].startswith('https://lk.rif-test.ru/o/'), str(message)[:300])
    token = message[3][0][1].rsplit('/', 1)[-1] if message else ''

    page = http.get(f'/o/{token}')
    check('страница ответа открывается', page.status_code == 200 and 'Согласен' in page.text)
    data = http.get(f'/public/offer/{token}').json()
    check('видно, что и почём, и снимок',
          data['total'] == 850 and data['author'] == 'Сергей' and data['media']['media'] == 'photo',
          str(data)[:200])
    check('чужая ссылка — 404', http.get('/public/offer/nope').status_code == 404)
    check('ждёт ответа — карточкой в кабинете',
          len(http.get('/history/offers', headers=client_auth).json()) == 1)

    check('пока клиент молчит — цеху говорить нечего',
          http.get('/sync/offers', headers=KEY).json()['offers'] == [])
    yes = http.post(f'/public/offer/{token}', json={'answer': 'yes'}).json()
    check('клиент согласился', yes['state'] == 'yes' and yes['changed'])
    again = http.post(f'/public/offer/{token}', json={'answer': 'no'}).json()
    check('передумать по той же ссылке нельзя — ответ уже у приёмщика',
          again['state'] == 'yes' and not again['changed'])

    pending = http.get('/sync/offers', headers=KEY).json()['offers']
    check('цех получает согласие с услугами для наряда',
          len(pending) == 1 and pending[0]['kind'] == 'answer' and pending[0]['state'] == 'yes'
          and [item['local_id'] for item in pending[0]['items']] == [11, 12]
          and pending[0]['client_phone'] == '79160000001', str(pending)[:300])
    http.post(f"/sync/offers/{pending[0]['id']}/taken", headers=KEY)
    check('разобранное второй раз не приходит', http.get('/sync/offers', headers=KEY).json()['offers'] == [])

    silent = phone.post('/m/offer', json={'order_local_id': 101, 'services': [12]}).json()
    db = SessionLocal()
    row = db.get(WorkOffer, silent['id'])
    row.created_at = shop_now() - timedelta(minutes=11)
    db.commit()
    db.close()
    pending = http.get('/sync/offers', headers=KEY).json()['offers']
    check('молчит 10 минут — приёмщику напоминание',
          len(pending) == 1 and pending[0]['kind'] == 'silent', str(pending)[:200])
    http.post(f"/sync/offers/{pending[0]['id']}/taken", headers=KEY)
    check('напоминание — один раз', http.get('/sync/offers', headers=KEY).json()['offers'] == [])
    order = phone.get('/m/order/101').json()
    check('мастер видит ответы в наряде',
          sorted(item['state'] for item in order['offers']) == ['pending', 'yes'], str(order['offers'])[:200])

    print('\n=== Начал / Готово ===')
    started = phone.post('/m/order/102/start')
    check('«Начал» принят', started.status_code == 200, started.text)
    cars = {car['order_local_id']: car for car in phone.get('/m/cars').json()['cars']}
    check('машина сразу «в работе», не дожидаясь цеха', cars[102]['state'] == 'work')
    phone.post('/m/order/102/start')
    events = http.get('/sync/master-events', headers=KEY).json()['events']
    check('повторное «Начал» не плодит событий',
          [(e['order_local_id'], e['kind'], e['author']) for e in events] == [(102, 'start', 'Сергей')],
          str(events))

    count = len(sent)
    ready = phone.post('/m/order/101/done').json()
    check('«Готово» — клиенту сразу', ready['told'] == 'telegram' and len(sent) == count + 1
          and 'готова' in sent[-1][2], str(ready))
    events = http.get('/sync/master-events', headers=KEY).json()['events']
    done_event = [e for e in events if e['kind'] == 'done'][0]
    check('цех узнаёт, что клиенту уже сказали', done_event['told'] is True)
    for event in events:
        http.post(f"/sync/master-events/{event['id']}/done", headers=KEY)
    check('забранные события второй раз не приходят',
          http.get('/sync/master-events', headers=KEY).json()['events'] == [])

    print('\n=== Заработок ===')
    closed = phone.get('/m/earnings')
    check('выключено — заработка не видно', closed.status_code == 403, closed.text)
    http.post('/sync/push', headers=KEY, json={'settings': {'master_salary_visible': '1'}})
    db = SessionLocal()
    now = shop_now()
    visit = Visit(local_id=500, shop_id=shop_id, license_plate='А123ВВ777', visited_at=now,
                  total_amount=3000, services='Шиномонтаж R16\nБалансировка')
    db.add(visit)
    db.flush()
    db.add(SalaryAccrual(visit_id=visit.id, employee_local_id=1, amount=1200, accrued_at=now))
    db.add(SalaryAccrual(visit_id=visit.id, employee_local_id=2, amount=900, accrued_at=now))
    old = Visit(local_id=400, shop_id=shop_id, license_plate='Т777ОО77',
                visited_at=now - timedelta(days=20), total_amount=5000)
    db.add(old)
    db.flush()
    db.add(SalaryAccrual(visit_id=old.id, employee_local_id=1, amount=2000, accrued_at=old.visited_at))
    db.add(SalaryPayout(shop_id=shop_id, employee_local_id=1, amount=1500, paid_at=now - timedelta(days=3)))
    db.commit()
    db.close()
    earn = phone.get('/m/earnings').json()
    check('сегодня — только своё', earn['today'] == 1200 and earn['today_orders'] == 1, str(earn)[:200])
    check('к выплате: всё начисленное минус выданное', earn['balance'] == 1700, str(earn['balance']))
    check('неделя по дням, сегодня последним',
          len(earn['week']) == 7 and earn['week'][-1]['amount'] == 1200)
    check('выплаты видны', earn['payouts'][0]['amount'] == 1500)

    print('\n=== Уволили — телефон выходит сам ===')
    http.post('/sync/push', headers=KEY, json={
        'employees': [{'local_id': 1, 'name': 'Сергей', 'is_active': False}]})
    check('уволенный не в кабинете', phone.get('/m/me').json()['employee'] is None)
    check('и его заработка не видно', phone.get('/m/earnings').status_code in (400, 403))

    print('\n=== Видео живёт две недели ===')
    db = SessionLocal()
    row = db.get(OrderPhoto, video_id)
    row.created_at = shop_now() - timedelta(days=15)
    path = photos.full_path(row)
    db.commit()
    gone = photos.drop_old_videos(db)
    check('старое видео убрано вместе с файлом', gone == 1 and not os.path.exists(path))
    check('фото не тронуто', db.get(OrderPhoto, photo_id) is not None)
    db.query(OrderPhoto).filter(OrderPhoto.id == photo_id).update(
        {OrderPhoto.created_at: shop_now() - timedelta(days=400)})
    db.commit()
    photos.drop_old(db)
    first_offer = db.query(WorkOffer).order_by(WorkOffer.id).first()
    check('фото старше года убрано, а предложение осталось — без снимка',
          db.get(OrderPhoto, photo_id) is None and first_offer is not None
          and first_offer.photo_id is None)
    db.close()

finish()
