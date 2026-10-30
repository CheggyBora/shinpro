"""
Разделы задач на сервере (решение владельца 30.10.2026).

  · цех присылает свои разделы — задача своего раздела проходит
    проверку и из цеха, и из дашборда;
  · переименованный раздел так и называется в Telegram и в сводке;
  · дашборд получает разделы вместе с задачами;
  · задача раздела уходит тем, кто отмечен для раздела; не отмечено —
    как у задач вообще, потом — как сводке по смене.
"""
import json
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_task_sections_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-task-sections-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-sections'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Shop
from app.services import tasks, notify, task_sections
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
SECTIONS = [
    {'key': 'work', 'title': 'Рабочая', 'directions': ['tire', 'wash'], 'hidden': False},
    {'key': 'tires', 'title': 'Шины на заказ', 'directions': ['tire'], 'hidden': False},
    {'key': 'paint', 'title': 'Покраска', 'directions': ['tire'], 'hidden': True},
    {'key': 'c1', 'title': 'От контрагента', 'directions': ['tire'], 'hidden': False,
     'color': '#be185d', 'background': '#fce7f3'},
    {'key': 'bad"><', 'title': 'Взлом', 'directions': ['tire']},
    {'key': 'c2', 'title': 'Цвет', 'directions': ['tire'], 'color': 'red;}body{x'},
]

with TestClient(app) as http:
    http.post('/sync/push', headers=KEY, json={'settings': {
        'task_sections': json.dumps(SECTIONS, ensure_ascii=False),
        'telegram_chats': '101',
        'telegram_chats_task': '303',
        'telegram_chats_task_c1': '202',
    }})
    db = SessionLocal()
    shop = db.query(Shop).first()
    today = shop_now().date()

    print('=== Разделы точки ===')
    sections = task_sections.load(db, shop)
    keys = [row['key'] for row in sections]
    check('встроенные и свои', keys[:5] == ['work', 'storage', 'tires', 'paint', 'supply']
          and 'c1' in keys, str(keys))
    check('кривой ключ отброшен', 'bad"><' not in keys)
    check('кривой цвет заменён', next(r for r in sections if r['key'] == 'c2')['color'] == '#334155')
    check('переименован', task_sections.titles(db, shop)['tires'] == 'Шины на заказ')

    print('\n=== Задача своего раздела ===')
    answer = tasks.exchange(db, shop, {'tasks': [
        {'uid': 's1', 'category': 'c1', 'due_date': today.isoformat(), 'title': 'Привёз шины',
         'updated_at': shop_now().isoformat(), 'source': 'shop'}]})
    check('из цеха принята', any(row['uid'] == 's1' and row['category'] == 'c1'
                                 for row in answer['tasks']))
    created = tasks.create(db, shop, {'category': 'c1', 'due_date': today.isoformat(),
                                      'title': 'Из дашборда'})
    check('из дашборда принята', created.category == 'c1')
    try:
        tasks.create(db, shop, {'category': 'c9', 'due_date': today.isoformat(), 'title': 'x'})
        check('несуществующий — отказ', False)
    except tasks.TaskError as e:
        check('несуществующий — отказ, со списком разделов', 'От контрагента' in str(e), str(e))
    hidden = tasks.create(db, shop, {'category': 'paint', 'due_date': today.isoformat(),
                                     'title': 'Скрытый раздел'})
    check('скрытый — для старых задач принимается', hidden.category == 'paint')

    text = tasks.telegram_text(created, titles=task_sections.titles(db, shop))
    check('в Telegram — название раздела', 'От контрагента' in text, text)
    morning = tasks.morning_text([created], [], task_sections.titles(db, shop))
    check('в сводке — тоже', 'От контрагента' in morning)

    print('\n=== Кому ===')
    check('свой раздел — своим', notify.chats_for(db, shop, notify.task_kind('c1')) == ['202'])
    check('без своих — как задачам вообще', notify.chats_for(db, shop, notify.task_kind('tires')) == ['303'])
    check('задачи вообще', notify.chats_for(db, shop, notify.KIND_TASK) == ['303'])
    check('склад — как сводке по смене', notify.chats_for(db, shop, notify.KIND_STORAGE) == ['101'])
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
