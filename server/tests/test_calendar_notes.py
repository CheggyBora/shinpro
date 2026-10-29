"""
Календарь: комментарии и время «до» (решение владельца 29.10.2026).

  · вид записи и «до» ездят в обмене в обе стороны;
  · старый цех вида не знает — его отметка не превращает комментарий
    в задачу и не стирает «до»;
  · комментарий не просрочивается и не попадает в сводку владельцу;
  · «до» раньше «с» — ошибка, без «с» «до» не бывает;
  · дашборду — часы работы точки для сетки «Неделя» и «День».
"""
import os
import sys
import tempfile
from datetime import timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_calendar_notes_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-calendar-notes-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-notes'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Shop, Task
from app.api.tasks import _hours
from app.services import tasks
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


def error(action):
    try:
        action()
    except tasks.TaskError as e:
        return str(e)
    return None


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

with TestClient(app) as http:
    http.post('/sync/push', headers=KEY, json={'settings': {
        'booking_opens_at': '08:00', 'booking_closes_at': '20:00'}})

    db = SessionLocal()
    shop = db.query(Shop).first()
    now = shop_now().replace(microsecond=0)
    today = now.date()
    yesterday = today - timedelta(days=1)

    print('=== Обмен: вид и «до» ===')
    answer = tasks.exchange(db, shop, {'tasks': [
        {'uid': 'n1', 'kind': 'note', 'category': 'work', 'due_date': yesterday.isoformat(),
         'title': 'Свет отключали', 'updated_at': now.isoformat(), 'source': 'shop'},
        {'uid': 't1', 'category': 'paint', 'due_date': yesterday.isoformat(),
         'due_time': '11:00', 'end_time': '12:30', 'title': 'Забрать диски',
         'updated_at': now.isoformat(), 'source': 'shop'},
    ]}, now=now)
    rows = {row['uid']: row for row in answer['tasks']}
    check('комментарий принят', rows['n1']['kind'] == 'note')
    check('задача с «до»', rows['t1']['kind'] == 'task' and rows['t1']['end_time'] == '12:30')

    later = (now + timedelta(minutes=1)).isoformat()
    tasks.exchange(db, shop, {'tasks': [
        {'uid': 'n1', 'category': 'work', 'due_date': yesterday.isoformat(),
         'title': 'Свет отключали', 'updated_at': later, 'source': 'shop'},
        {'uid': 't1', 'category': 'paint', 'due_date': yesterday.isoformat(),
         'due_time': '11:00', 'title': 'Забрать диски', 'updated_at': later, 'source': 'shop'},
    ]}, now=now)
    note = db.query(Task).filter(Task.uid == 'n1').first()
    task = db.query(Task).filter(Task.uid == 't1').first()
    check('старый цех не превратил комментарий в задачу', note.kind == 'note')
    check('старый цех не стёр «до»', task.end_time == '12:30')

    print('\n=== Комментарий не просрочивается ===')
    overdue, _rows = tasks.for_range(db, [shop.id], today, today, today=today)
    uids = {row.uid for row in overdue}
    check('вчерашняя задача — просрочена', 't1' in uids)
    check('вчерашний комментарий — нет', 'n1' not in uids)
    for_today, late = tasks._undone(db, shop.id, today)
    check('в сводке владельцу комментария нет', all(row.kind != 'note' for row in late + for_today))

    print('\n=== Время «до» ===')
    check('«до» раньше «с» — ошибка', error(lambda: tasks.clean_fields(
        {'category': 'work', 'due_date': today.isoformat(), 'title': 'x',
         'due_time': '12:00', 'end_time': '11:00'})))
    fields = tasks.clean_fields({'category': 'work', 'due_date': today.isoformat(),
                                 'title': 'x', 'due_time': '', 'end_time': '11:00'})
    check('без «с» «до» нет', fields['end_time'] is None)

    created = tasks.create(db, shop, {'kind': 'note', 'category': 'work',
                                      'due_date': today.isoformat(), 'title': 'Из дашборда',
                                      'due_time': '10:00', 'end_time': '11:00'})
    check('дашборд ставит комментарий', created.kind == 'note' and created.end_time == '11:00')
    tasks.patch(db, created, {'due_time': '11:30'})
    check('«с» позже «до» — «до» убрали', created.end_time is None)

    print('\n=== Telegram: задача из дашборда, контрагент по нику ===')
    from app.models import Counterparty
    from app.services import notify, shop_settings
    tasks.exchange(db, shop, {'counterparties': [
        {'uid': 'cp1', 'name': 'Покраска «Колор»', 'telegram': '@Kolor_Paint',
         'updated_at': now.isoformat()}]}, now=now)
    party = db.query(Counterparty).filter(Counterparty.uid == 'cp1').first()
    check('ник контрагента приехал из цеха', party.telegram == 'kolor_paint')
    tasks.exchange(db, shop, {'counterparties': [
        {'uid': 'cp1', 'name': 'Покраска «Колор»',
         'updated_at': (now + timedelta(minutes=1)).isoformat()}]}, now=now)
    check('старый цех без ника его не стирает', party.telegram == 'kolor_paint')

    job = tasks.create(db, shop, {'category': 'paint', 'due_date': today.isoformat(),
                                  'title': 'Забрать диски', 'due_time': '11:00',
                                  'end_time': '12:30', 'counterparty_uid': 'cp1'},
                       author='Иван')
    text = tasks.telegram_text(job, 'Покраска «Колор»')
    check('текст: время, раздел, контрагент, кто поставил',
          '11:00–12:30' in text and 'Покраска' in text and 'Колор' in text and 'Иван' in text)
    check('контрагент задачи находится', tasks.counterparty_of(job).uid == 'cp1')

    check('чат по нику — пока цех не прислал, нет',
          notify.personal_chat(db, shop, 'kolor_paint') is None)
    shop_settings.set_value(db, 'telegram_usernames', '{"kolor_paint": "555"}', shop=shop)
    check('чат по нику — из присланного цехом', notify.personal_chat(db, shop, '@Kolor_Paint') == '555')
    check('в Telegram задача, не комментарий', 'task' in notify.KINDS)

    print('\n=== Часы сетки ===')
    hours = _hours(db, [shop.id])
    check('по часам работы точки', hours == {'from': 8, 'to': 20}, str(hours))
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
