"""
Онлайн-очередь со стороны клиента: всё, что он нажимает в кабинете.

Путь человека: прочитал правила → вошёл → встал → получил время →
подъехал и нажал «Я приехал», либо «Не успеваю». Проверяем каждый шаг
через те же ручки, что дёргает страница, — и то, что он видит в ответ.

Главное, что ломается молча:

  · кнопка на главном экране не должна показываться, если очередь
    выключена — показать и отказать по нажатию хуже, чем не показать;
  · время человек получает сразу и сообщением, а не узнаёт потом;
  · «Не успеваю» работает один раз, второй закрывает место;
  · встать в очередь без входа нельзя: сказать о сдвиге можно только
    тому, кого мы знаем.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_queue_cabinet.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-queue-cabinet'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-queue-cabinet'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Client, Shop
from app.security import create_token
from app.services import notices, shop_settings
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


# Что ушло клиенту сообщением — подменяем отправку
said = []


def fake_send(db, client, account, kind, text, about=None, about_id=None):
    said.append((client.id, text))
    return 'telegram'


notices.send_now = fake_send

with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop.last_sync_at = shop_now()
    shop_settings.set_value(db, 'queue_posts', '1', commit=False, shop=shop)

    peter = Client(account_id=shop.account_id, phone='79160000001',
                   name='Пётр', phone_verified_at=shop_now())
    olga = Client(account_id=shop.account_id, phone='79160000002',
                  name='Ольга', phone_verified_at=shop_now())
    db.add_all([peter, olga])
    db.commit()

    as_peter = {'Authorization': f'Bearer {create_token(peter.id)}'}
    as_olga = {'Authorization': f'Bearer {create_token(olga.id)}'}
    db.close()

    print('=== Кнопка на главном — без входа ===')
    open_ = http.get('/public/queue').json()
    check('очередь работает', open_['enabled'] is True, str(open_))
    check('зовём через час', open_['min_wait_minutes'] == 60, str(open_))
    check('подъезжать за 20 минут', open_['lead_minutes'] == 20, str(open_))
    check('перенос один', open_['moves'] == 1, str(open_))

    print()
    print('=== Без входа встать нельзя ===')
    # Сказать о сдвиге времени можно только тому, кого мы знаем
    anon = http.post('/queue/join', json={})
    check('отказано', anon.status_code == 401, str(anon.status_code))

    print()
    print('=== Встал — получил время сразу и сообщением ===')
    said.clear()
    joined = http.post('/queue/join', headers=as_peter, json={}).json()

    check('назначено время, к которому подъезжать', bool(joined['come_at']),
          str(joined))
    check('и черёд', bool(joined['turn_at']), str(joined))
    check('подъезжать на 20 минут раньше черёда',
          joined['come_at'] < joined['turn_at'], str(joined))
    check('ещё не на месте', joined['arrived'] is False, str(joined))
    check('перенос доступен', joined['can_move'] is True, str(joined))

    check('сообщение ушло', len(said) == 1, str(said))
    check('в нём время приезда', joined['come_at'][11:16] in said[-1][1],
          said[-1][1] if said else '')

    print()
    print('=== Дважды не встать ===')
    twice = http.post('/queue/join', headers=as_peter, json={})
    check('отказано', twice.status_code == 400, str(twice.status_code))

    print()
    print('=== Своё место видно при открытии страницы ===')
    # Человек открыл страницу, подъезжая: ему нужно его время и кнопка
    # «Я приехал», а не календарь записи
    mine = http.get('/queue/online', headers=as_peter).json()
    check('страница знает, что он в очереди', mine['mine'] is not None,
          str(mine))
    check('то же время', mine['mine']['come_at'] == joined['come_at'],
          str(mine['mine']))

    print()
    print('=== Я приехал ===')
    here = http.post('/queue/arrived', headers=as_peter).json()
    check('отмечен', here['arrived'] is True, str(here))
    check('и звать его теперь можно сразу',
          here['turn_at'] <= shop_now().isoformat()[:16] + ':59',
          str(here['turn_at']))

    print()
    print('=== Не успеваю — в конец, и это один раз ===')
    http.post('/queue/join', headers=as_olga, json={})
    said.clear()

    later = http.post('/queue/later', headers=as_olga).json()
    check('осталась в очереди', 'closed' not in later, str(later))
    check('перенос израсходован', later['can_move'] is False, str(later))
    check('и видно, что переносилась', later['moved'] is True, str(later))
    check('сказали новое время', len(said) == 1 and 'конец' in said[-1][1],
          str(said))

    print()
    print('=== Второй раз не успеваю — место закрывается ===')
    said.clear()
    again = http.post('/queue/later', headers=as_olga).json()
    check('место закрыто', again.get('closed') is True, str(again))
    check('и сказано, что делать дальше',
          'запишитесь' in again.get('reason', '').lower(), str(again))
    check('сообщение об этом тоже ушло',
          len(said) == 1 and 'закрыто' in said[-1][1], str(said))

    gone = http.get('/queue/online', headers=as_olga).json()
    check('в очереди её больше нет', gone['mine'] is None, str(gone))

    print()
    print('=== Уйти из очереди ===')
    left = http.post('/queue/leave', headers=as_peter).json()
    check('ушёл', left.get('ok') is True, str(left))
    check('места больше нет',
          http.get('/queue/online', headers=as_peter).json()['mine'] is None)

    print()
    print('=== Постов под очередь нет — кнопки нет ===')
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_settings.set_value(db, 'queue_posts', '0', shop=shop)
    db.close()

    check('на главном не показываем',
          http.get('/public/queue').json()['enabled'] is False)

finish()
