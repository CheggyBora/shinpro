"""
Запуск новой точки по коду: «Заказчики», код, скачивание, подключение.

Решение владельца 27.10.2026: точку ставит человек, который плохо
разбирается в компьютере. Поэтому:

    «Заказчики» (только владелец сервера) -> код из 8 цифр
    setup.ДОМЕН -> программа скачивается только по коду
    программа цеха -> тот же код -> ключ обмена, который не видит никто
    дашборд организации -> владелец входит по своему номеру
"""
import os
import shutil
import sys
import tempfile
from datetime import timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_onboarding_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)
_downloads = os.path.join(tempfile.gettempdir(), 'tire_onboarding_downloads')
shutil.rmtree(_downloads, ignore_errors=True)

OWNER = '+7 909 901-89-31'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-onboarding'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = OWNER
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_CORS_ORIGINS'] = 'https://lk.rif-test.ru,https://admin.rif-test.ru'
os.environ['SERVER_DOWNLOAD_DIR'] = _downloads
os.environ.pop('SERVER_PLATFORM_DOMAIN', None)
os.environ.pop('SERVER_HOME_HOSTS', None)

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Account, Shop, ConnectCode, ConnectAttempt, StaffUser
from app.models.account import DOMAIN_ACTIVE
from app.services import onboarding, tenancy
from app.services.staff_service import StaffService
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


def host(name):
    return {'Host': name}


ADMIN = host('admin.rif-test.ru')
EXE = b'MZ' + b'\x90' * (9 * 1024 * 1024)      # 9 МБ — три куска по 4


with TestClient(app) as client:
    db = SessionLocal()
    rif, rif_shop, _ = tenancy.create_account(db, 'Шиномонтаж «РИФ»', 'РИФ')
    rif_shop.last_sync_at = shop_now()
    db.commit()
    me = StaffService(db, rif.id).ensure_owner(OWNER, 'Владелец')
    StaffService(db, rif.id).set_pin(me, '2580')
    # Второй человек — админ. Не через ensure_owner: тот не заводит
    # второго владельца, когда первый уже есть
    from app.models import StaffUser
    from app.utils import normalize_phone
    helper = StaffUser(phone=normalize_phone('+7 900 111-22-33'), account_id=rif.id, role='admin')
    db.add(helper)
    db.commit()
    StaffService(db, rif.id).set_pin(helper, '3691')

    token = client.post('/staff/login', json={'phone': OWNER, 'pin': '2580'},
                        headers=ADMIN).json()['token']
    auth = {**ADMIN, 'Authorization': f'Bearer {token}'}
    other = client.post('/staff/login', json={'phone': '+7 900 111-22-33', 'pin': '3691'},
                        headers=ADMIN).json()['token']
    other_auth = {**ADMIN, 'Authorization': f'Bearer {other}'}

    print('=== «Заказчики» видит только владелец сервера ===')
    check('владелец сервера — видит', client.get('/platform/me', headers=auth).status_code == 200)
    answer = client.get('/platform/accounts', headers=other_auth)
    check('другой сотрудник того же «РИФа» — раздела нет', answer.status_code == 404, answer.text)
    check('без входа — нет', client.get('/platform/accounts', headers=ADMIN).status_code == 401)

    print('\n=== Новый заказчик ===')
    bad = client.post('/platform/accounts', headers=auth,
                      json={'name': 'Колесо', 'owner_phone': '123'})
    check('неправильный телефон — отказ, ничего не заведено',
          bad.status_code == 400 and db.query(Account).count() == 1, bad.text)
    bad = client.post('/platform/accounts', headers=auth,
                      json={'name': 'Колесо', 'owner_phone': '+7 916 000-00-12', 'slug': 'admin'})
    check('служебное имя адреса — отказ', bad.status_code == 400, bad.text)

    answer = client.post('/platform/accounts', headers=auth, json={
        'name': 'Сеть «Колесо»', 'owner_phone': '+7 916 000-00-12', 'slug': 'koleso',
        'shop_name': 'Колесо на Ленина', 'paid_until': '2026-11-30'})
    check('заведён', answer.status_code == 200, answer.text[:300])
    body = answer.json()
    code = body['code']
    digits = code['code'].replace(' ', '')
    check('код — 8 цифр, не с нуля', len(digits) == 8 and digits.isdigit() and digits[0] != '0',
          code['code'])
    check('в сообщении ссылка и код',
          code['code'] in code['text'] and '/setup' in code['text'], code['text'])
    account = body['account']
    check('адреса koleso. и koleso-admin.',
          account['lk_url'] == 'https://koleso.rif-test.ru'
          and account['admin_url'] == 'https://koleso-admin.rif-test.ru', str(account))
    check('оплачено до 30.11', account['billing']['paid_until'].startswith('2026-11-30'),
          str(account['billing']))
    db.expire_all()
    koleso = db.query(Account).filter(Account.slug == 'koleso').first()
    koleso_shop = koleso.shops[0]
    check('у точки нет ключа, пока не ввели код', koleso_shop.sync_key_hash is None)
    owner = db.query(StaffUser).filter(StaffUser.account_id == koleso.id).first()
    check('владелец «Колеса» заведён в его организации',
          owner is not None and owner.role == 'owner' and owner.phone.endswith('0000012'),
          str(owner and owner.phone))

    print('\n=== Страница скачивания ===')
    page = client.get('/setup', headers=host('lk.rif-test.ru'))
    check('/setup открывается', page.status_code == 200 and 'Код подключения' in page.text)
    page = client.get('/z', headers=host('setup.rif-test.ru'))
    check('setup.ДОМЕН вместо записи показывает скачивание',
          page.status_code == 200 and 'Код подключения' in page.text)
    page = client.get('/z', headers=host('koleso.rif-test.ru'))
    check('на адресе записи — по-прежнему запись', 'Код подключения' not in page.text)
    check('setup — имя, которое организация получить не может',
          not tenancy._slug_fits_address('setup'))

    found = client.post('/connect/check', json={'code': code['code']})
    check('код подходит — «Найдено: Колесо»',
          found.status_code == 200 and found.json()['shop'] == 'Колесо на Ленина'
          and found.json()['program'] is False, found.text)
    answer = client.post('/setup/download', data={'code': digits})
    check('программа не загружена — понятный отказ, а не 500',
          answer.status_code == 400 and 'не загружена' in answer.text, answer.text[:200])

    print('\n=== Загрузка новой версии программы ===')
    start = client.post('/platform/program/start', headers=auth).json()
    step = start['part_bytes']
    offset, broken = 0, None
    while offset < len(EXE):
        part = client.post('/platform/program/part', headers=auth,
                           params={'upload': start['upload'], 'offset': offset},
                           content=EXE[offset:offset + step])
        if part.status_code != 200:
            broken = part.text
            break
        offset = part.json()['size']
    check('кусками по 4 МБ', broken is None and offset == len(EXE), str(broken))
    again = client.post('/platform/program/part', headers=auth,
                        params={'upload': start['upload'], 'offset': 0}, content=b'xx')
    check('кусок не по порядку — отказ', again.status_code == 400, again.text)
    done = client.post('/platform/program/finish', headers=auth,
                       params={'upload': start['upload'], 'size': len(EXE)})
    check('принят целиком', done.status_code == 200 and done.json()['size'] == len(EXE), done.text)

    start = client.post('/platform/program/start', headers=auth).json()
    client.post('/platform/program/part', headers=auth,
                params={'upload': start['upload'], 'offset': 0}, content=b'PK\x03\x04zip')
    done = client.post('/platform/program/finish', headers=auth,
                       params={'upload': start['upload'], 'size': 7})
    check('не .exe — отказ, прежняя версия на месте',
          done.status_code == 400 and onboarding.program_info()['size'] == len(EXE), done.text)
    check('загружать может только владелец сервера',
          client.post('/platform/program/start', headers=other_auth).status_code == 404)
    bad_id = client.post('/platform/program/part', headers=auth,
                         params={'upload': '../../etc', 'offset': 0}, content=b'x')
    check('чужой путь вместо номера загрузки — отказ', bad_id.status_code == 400, bad_id.text)

    answer = client.post('/setup/download', data={'code': code['code']})
    check('по коду скачивается программа',
          answer.status_code == 200 and answer.content[:2] == b'MZ'
          and 'TireShop.exe' in answer.headers.get('content-disposition', ''),
          str(answer.status_code))
    answer = client.post('/setup/download', data={'code': '12345678'})
    check('без верного кода — не скачать', answer.status_code == 400 and answer.content[:2] != b'MZ')

    print('\n=== Программа цеха вводит код ===')
    connected = client.post('/connect', json={'code': code['code']})
    check('подключилась', connected.status_code == 200, connected.text[:200])
    result = connected.json()
    check('получила ключ, адрес дашборда и номер владельца',
          len(result.get('key', '')) > 30
          and result['admin_url'] == 'https://koleso-admin.rif-test.ru'
          and result['owner_phone'] == '+7 (916) ···-··-12',
          str({k: v for k, v in result.items() if k != 'key'}))
    state = client.get('/sync/state', headers={'X-Sync-Key': result['key']})
    check('по этому ключу обмен идёт', state.status_code == 200, state.text[:200])
    db.expire_all()
    check('и это точка «Колеса»',
          tenancy.shop_by_sync_key(db, result['key']).id == koleso_shop.id)
    again = client.post('/connect', json={'code': code['code']})
    check('второй раз тот же код не срабатывает', again.status_code == 400
          and 'не действует' in again.json()['detail'], again.text)

    print('\n=== Переподключить компьютер ===')
    koleso_token = None
    StaffService(db, koleso.id).set_pin(owner, '5828')
    koleso_token = client.post('/staff/login', json={'phone': '+7 916 000-00-12', 'pin': '5828'},
                               headers=host('koleso-admin.rif-test.ru')).json()['token']
    k_auth = {**host('koleso-admin.rif-test.ru'), 'Authorization': f'Bearer {koleso_token}'}
    points = client.get('/dashboard/points', headers=k_auth)
    check('владелец «Колеса» видит свои точки',
          points.status_code == 200 and [p['name'] for p in points.json()['points']]
          == ['Колесо на Ленина'], points.text[:200])
    check('«Заказчиков» у него нет', client.get('/platform/me', headers=k_auth).status_code == 404)
    alien = client.post(f'/dashboard/points/{rif_shop.id}/code', headers=k_auth)
    check('код для точки «РИФа» ему не выдать', alien.status_code == 404, alien.text)

    fresh = client.post(f'/dashboard/points/{koleso_shop.id}/code', headers=k_auth).json()
    state = client.get('/sync/state', headers={'X-Sync-Key': result['key']})
    check('пока новый компьютер не подключился, старый работает', state.status_code == 200)
    second = client.post('/connect', json={'code': fresh['code']}).json()
    state = client.get('/sync/state', headers={'X-Sync-Key': result['key']})
    check('после подключения нового — старый ключ не действует', state.status_code in (401, 403),
          str(state.status_code))
    state = client.get('/sync/state', headers={'X-Sync-Key': second['key']})
    check('а новый — действует', state.status_code == 200)

    newer = client.post(f'/dashboard/points/{koleso_shop.id}/code', headers=k_auth).json()
    newest = client.post(f'/dashboard/points/{koleso_shop.id}/code', headers=k_auth).json()
    stale = client.post('/connect/check', json={'code': newer['code']})
    check('новый код отменяет прежний', stale.status_code == 400, stale.text)
    client.delete(f'/dashboard/points/{koleso_shop.id}/code', headers=k_auth)
    gone = client.post('/connect/check', json={'code': newest['code']})
    check('отменённый код не действует', gone.status_code == 400, gone.text)

    row = onboarding.issue_code(db, koleso_shop)
    row.expires_at = shop_now() - timedelta(minutes=1)
    db.commit()
    expired = client.post('/connect/check', json={'code': row.code})
    check('истёкший код не действует', expired.status_code == 400, expired.text)

    print('\n=== Подобрать код нельзя ===')
    db.query(ConnectAttempt).delete()
    db.commit()
    live = onboarding.issue_code(db, koleso_shop)
    codes = []
    for number in range(onboarding.FAILS_PER_ADDRESS):
        guess = f'{10000000 + number:08d}'
        if guess == live.code:
            guess = '19999999'
        codes.append(client.post('/connect/check', json={'code': guess}).status_code)
    check('неверные коды — отказ', all(code == 400 for code in codes), str(codes))
    blocked = client.post('/connect/check', json={'code': live.code})
    check('после 10 неверных даже верный код с этого адреса ждёт 15 минут',
          blocked.status_code == 429, blocked.text)
    db.query(ConnectAttempt).delete()
    db.commit()
    check('потом — снова подходит',
          client.post('/connect/check', json={'code': live.code}).status_code == 200)

    print('\n=== Оплата, закрытие, ещё точка ===')
    paid = client.post(f'/platform/accounts/{koleso.id}/pay', headers=auth,
                       json={'amount': 3000, 'months': 1})
    check('оплата продлевает от 30.11',
          paid.status_code == 200 and paid.json()['billing']['paid_until'].startswith('2026-12-30'),
          paid.text[:200])
    closed = client.post(f'/platform/accounts/{koleso.id}/block', headers=auth, json={'reason': 'тест'})
    check('закрыт', closed.json()['billing']['state'] == 'blocked')
    login = client.post('/staff/login', json={'phone': '+7 916 000-00-12', 'pin': '5828'},
                        headers=host('koleso-admin.rif-test.ru'))
    check('закрытая организация в дашборд не входит', login.status_code != 200, str(login.status_code))
    client.post(f'/platform/accounts/{koleso.id}/unblock', headers=auth)
    own = client.post(f'/platform/accounts/{rif.id}/block', headers=auth, json={})
    check('свою организацию закрыть нельзя', own.status_code == 400, own.text)

    added = client.post(f'/platform/accounts/{koleso.id}/shops', headers=auth,
                        json={'name': 'Колесо на Мира'})
    check('вторая точка — сразу с кодом',
          added.status_code == 200 and len(added.json()['code']['code']) == 9
          and len(added.json()['account']['shops']) == 2, added.text[:200])

    listing = client.get('/platform/accounts', headers=auth).json()
    check('в списке обе организации и программа',
          [a['name'] for a in listing['accounts']] == ['Шиномонтаж «РИФ»', 'Сеть «Колесо»']
          and listing['program']['exists'], str([a['name'] for a in listing['accounts']]))

    print('\n=== Адрес страницы скачивания ===')
    check('до сертификата — lk. сервера', onboarding.setup_url(db) == 'https://lk.rif-test.ru/setup',
          onboarding.setup_url(db))
    plan = tenancy.domains_plan(db)
    check('setup. в плане для сертификата', ('setup.rif-test.ru', 'lk', False) in plan, str(plan))
    tenancy.ensure_domain_row(db, 'setup.rif-test.ru', 'lk')
    tenancy.set_domain_status(db, 'setup.rif-test.ru', DOMAIN_ACTIVE)
    check('с сертификатом — setup.ДОМЕН', onboarding.setup_url(db) == 'https://setup.rif-test.ru',
          onboarding.setup_url(db))
    brand = client.get('/dashboard/brand', headers=auth).json()
    check('в «Оформлении» «РИФа» setup. не появляется',
          all('setup.' not in item['name'] for item in brand['ours'] + brand['own']), str(brand['ours']))

    print('\n=== Имена и удаление ===')
    same = client.post('/platform/accounts', headers=auth, json={
        'name': 'Шинка', 'owner_phone': '+7 916 000-00-77', 'slug': 'shinka', 'shop_name': 'Шинка'})
    shops = same.json()['account']['shops'] if same.status_code == 200 else []
    check('точка с тем же названием не забирает короткое имя организации',
          same.status_code == 200 and same.json()['account']['slug'] == 'shinka'
          and shops and shops[0]['slug'] != 'shinka', same.text[:200])
    db.expire_all()
    doomed = db.get(Shop, shops[0]['id'])
    tenancy.drop_shop(db, doomed)
    check('точку с выданным кодом можно удалить — код уходит с ней',
          db.query(ConnectCode).filter(ConnectCode.shop_id == shops[0]['id']).count() == 0)

    db.close()

finish()
