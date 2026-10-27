"""
Подключение программы цеха по коду из дашборда.

Решение владельца 27.10.2026: вместо адреса и ключа из 43 знаков —
код из 8 цифр. Программа отдаёт его серверу, получает ключ обмена,
сохраняет и включает обмен. Проверяем по-настоящему: сервер на своём
порту, программа ходит в него по сети.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('connect_code')

import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request

_server_db = os.path.join(tempfile.gettempdir(), 'tire_connect_code_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-for-connect-code-0123456789'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

SERVER_DIR = os.path.join(_setup.PROJECT_DIR, 'server')
sys.path.insert(0, SERVER_DIR)

from config import init_db, SessionLocal
from services.settings_service import SettingsService
from services.sync_service import SyncService, SyncError


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


PORT = free_port()
BASE_URL = f'http://127.0.0.1:{PORT}'


def start_server():
    import uvicorn
    from app.main import app as server_app

    server = uvicorn.Server(uvicorn.Config(server_app, host='127.0.0.1', port=PORT,
                                           log_level='error'))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            with urllib.request.urlopen(f'{BASE_URL}/health', timeout=1):
                return server
        except Exception:
            time.sleep(0.1)
    raise RuntimeError('Сервер не поднялся')


init_db()
server = start_server()

from app.database import SessionLocal as ServerSession
from app.services import onboarding, tenancy

server_db = ServerSession()
tenancy.create_account(server_db, 'Шиномонтаж «РИФ»', 'РИФ')
account, shop, code = onboarding.create_customer(
    server_db, 'Сеть «Колесо»', '+7 916 000-00-12', slug='koleso', shop_name='Колесо на Ленина')
pretty = onboarding.pretty_code(code.code)

db = SessionLocal()
sync = SyncService(db)

print('=== Ошибся цифрой ===')
try:
    sync.connect_by_code('1234', BASE_URL)
    check('короткий код — отказ', False)
except SyncError as e:
    check('короткий код — отказ без похода на сервер', '8 цифр' in str(e), str(e))

wrong = '1' + code.code[1:] if code.code[0] != '1' else '2' + code.code[1:]
try:
    sync.connect_by_code(wrong, BASE_URL)
    check('чужой код — отказ', False)
except SyncError as e:
    check('чужой код — понятный отказ', 'не найден' in str(e), str(e))
check('после отказа обмен не включился', not sync.is_enabled())

print('\n=== Верный код ===')
answer = sync.connect_by_code(pretty, BASE_URL)
check('подключилась к «Колесу»',
      answer['account'] == 'Сеть «Колесо»' and answer['shop'] == 'Колесо на Ленина', str(answer))
check('ключ в ответе наружу не отдаётся', 'key' not in answer)
check('адрес, ключ и обмен сохранены',
      sync.get_url() == BASE_URL and len(sync.get_key()) > 30 and sync.is_enabled())
check('ключ точки — тот, что знает сервер',
      tenancy.shop_by_sync_key(server_db, sync.get_key()).id == shop.id)
state = sync.test_connection()
check('обмен по нему идёт', state['shop']['name'] == 'Колесо на Ленина', str(state)[:200])

print('\n=== Тот же код второй раз ===')
other = SyncService(db)
try:
    other.connect_by_code(pretty, BASE_URL)
    check('повторно — отказ', False)
except SyncError as e:
    check('повторно не срабатывает', 'не действует' in str(e), str(e))
check('и уже подключённая точка не сломалась', sync.test_connection()['shop']['name'] == 'Колесо на Ленина')

print('\n=== Без адреса — сервер по умолчанию ===')
from services import sync_service
settings = SettingsService(db)
settings.set('sync_server_url', '')
called = {}
real = urllib.request.urlopen


def fake(request, timeout=None):
    called['url'] = request.full_url
    raise urllib.error.URLError('нет сети в тесте')


urllib.request.urlopen = fake
try:
    sync.connect_by_code(pretty)
except SyncError:
    pass
urllib.request.urlopen = real
check('пустой адрес — идём на admin.rif-service.ru',
      called.get('url') == sync_service.DEFAULT_URL + '/connect', str(called))

server_db.close()
db.close()
server.should_exit = True
finish()
