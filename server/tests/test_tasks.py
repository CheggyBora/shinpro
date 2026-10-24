"""
Календарь задач: обмен с цехом, дашборд, задачи из кабинета, сводка.

  · обмен: побеждает более поздняя правка — с любой стороны; при
    равенстве сервер свою строку не трогает;
  · since: отдаём только изменённое после; первый обмен — живые задачи
    за два месяца и всё, что впереди;
  · удаление доходит до второй стороны, а не теряется;
  · чужая точка чужих задач не видит и не затирает;
  · дашборд: поставить, поправить, перенести, отметить, удалить;
  · клиент заказал комплект из кабинета — ровно одна задача кладовщику,
    отменил запись — задача снята, перенесли — едет следом;
  · сообщения о складе — получателям склада, если они заданы;
  · сводка владельцу: утром раз и вечером раз, своим получателям.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_tasks_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-31'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-tasks-calendar'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-tasks'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging
from datetime import datetime, timedelta, time

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Appointment, Client, Shop, StoredSet, Task
from app.security import create_token
from app.services import notify, shop_settings, tasks, tenancy
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


# Telegram подменён: что ушло и в какой чат
sent = []


def fake_post(token, chat, text):
    sent.append((chat, text))
    return True


def sync_background(text, shop=None, kind=None):
    """Тот же путь, что в потоке, только сразу: тесту ждать нечего."""
    db = SessionLocal()
    try:
        notify.send(db, text, shop=getattr(shop, 'id', shop), kind=kind)
    finally:
        db.close()


notify._post = fake_post
notify.send_in_background = sync_background

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
TODAY = shop_now().date()
HOUR_AGO = (shop_now() - timedelta(hours=1)).replace(microsecond=0)


def iso(moment):
    return moment.isoformat(timespec='seconds')


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify',
                      json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def task_row(uid, **extra):
    row = {'uid': uid, 'category': 'work', 'due_date': TODAY.isoformat(),
           'due_time': '10:00', 'title': 'Заказать грузики',
           'updated_at': iso(HOUR_AGO), 'created_by': 'Пётр'}
    row.update(extra)
    return row


def by_uid(rows, uid):
    return next((row for row in rows if row['uid'] == uid), None)


def server_task(uid):
    db = SessionLocal()
    try:
        return db.query(Task).filter(Task.uid == uid).all()
    finally:
        db.close()


with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_id, slug, account_id = shop.id, shop.slug, shop.account_id
    other, other_key = tenancy.add_shop(db, shop.account, 'РИФ на Южной')
    other_id = other.id
    db.close()
    OTHER = {'X-Sync-Key': other_key}

    def exchange(since=None, tasks_in=(), counterparties=(), headers=KEY):
        answer = http.post('/sync/tasks', headers=headers, json={
            'since': since, 'tasks': list(tasks_in),
            'counterparties': list(counterparties)})
        return answer.status_code, answer.json()

    print('=== Обмен: первая присылка из цеха ===')
    code, first = exchange(None, [
        task_row('u-1'),
        task_row('u-old', due_date=(TODAY - timedelta(days=90)).isoformat(),
                 title='Давняя'),
        task_row('u-gone', deleted=True, title='Удалена в цеху'),
        task_row('u-bad', category='лишнее'),
        task_row('u-long', title='Я' * 500, note='н' * 9000,
                 license_plate='а 123 вв 777'),
    ], [{'uid': 'c-1', 'name': 'Еврошины', 'kind': 'Поставщик шин',
         'updated_at': iso(HOUR_AGO)}])
    check('обмен принят', code == 200, str(first)[:200])
    check('в ответе now', bool(first.get('now')), str(first.get('now')))
    check('принятая задача вернулась цеху', by_uid(first['tasks'], 'u-1') is not None)
    check('задача старше двух месяцев в первый обмен не едет',
          by_uid(first['tasks'], 'u-old') is None)
    check('удалённая в первый обмен не едет',
          by_uid(first['tasks'], 'u-gone') is None)
    check('чужой раздел не принят', 'u-bad' in first.get('rejected', []),
          str(first.get('rejected')))
    check('и не записан', not server_task('u-bad'))
    long_row = by_uid(first['tasks'], 'u-long')
    check('длинный заголовок обрезан',
          long_row is not None and len(long_row['title']) == 200)
    check('номер приведён к виду', long_row['license_plate'] == 'А123ВВ777',
          str(long_row['license_plate']))
    check('контрагент принят', by_uid(first['counterparties'], 'c-1') is not None)
    one = by_uid(first['tasks'], 'u-1')
    check('дата строкой YYYY-MM-DD', one['due_date'] == TODAY.isoformat())
    check('время правки — присланное, а не время доезда',
          one['updated_at'] == iso(HOUR_AGO), one['updated_at'])
    check('источник — цех', one['source'] == 'shop')
    cursor = first['now']

    print()
    print('=== since: только изменённое после ===')
    code, quiet = exchange(cursor)
    check('ничего не менялось — ничего не едет',
          code == 200 and quiet['tasks'] == [] and quiet['counterparties'] == [],
          str(quiet)[:200])

    print()
    print('=== Слияние: побеждает более поздняя правка ===')
    older = iso(HOUR_AGO - timedelta(minutes=30))
    exchange(cursor, [task_row('u-1', title='Старая правка', updated_at=older)])
    check('старая правка из цеха не затирает новую',
          server_task('u-1')[0].title == 'Заказать грузики')

    exchange(cursor, [task_row('u-1', title='Та же минута', updated_at=iso(HOUR_AGO))])
    check('при равенстве сервер свою строку не трогает',
          server_task('u-1')[0].title == 'Заказать грузики')

    newer = iso(HOUR_AGO + timedelta(minutes=10))
    code, answer = exchange(cursor, [task_row('u-1', title='Грузики, 2 коробки',
                                              updated_at=newer)])
    check('новая правка из цеха принята',
          server_task('u-1')[0].title == 'Грузики, 2 коробки')
    check('одна строка, не две', len(server_task('u-1')) == 1)
    cursor = answer['now']

    print()
    print('=== Дашборд ===')
    owner = enter(http, OWNER_PHONE, '4831')

    week = {'from': TODAY.isoformat(),
            'to': (TODAY + timedelta(days=6)).isoformat()}
    listed = http.get('/dashboard/tasks', headers=owner, params=week).json()
    check('задачи недели видны', by_uid(listed['tasks'], 'u-1') is not None,
          str(listed)[:200])
    check('название контрагента подставляется по uid',
          'counterparty_name' in by_uid(listed['tasks'], 'u-1'))
    check('удалённой в календаре нет', by_uid(listed['tasks'], 'u-gone') is None)

    nobody = http.post('/dashboard/tasks', headers=owner, json={
        'category': 'work', 'due_date': TODAY.isoformat(), 'title': 'Куда?'})
    check('точек две — без выбора точки задачу не ставим',
          nobody.status_code == 409, str(nobody.status_code))

    bad = http.post(f'/dashboard/tasks?shop={slug}', headers=owner, json={
        'category': 'garden', 'due_date': TODAY.isoformat(), 'title': 'x'})
    check('чужой раздел — отказ', bad.status_code == 400, str(bad.status_code))
    bad = http.post(f'/dashboard/tasks?shop={slug}', headers=owner, json={
        'category': 'work', 'due_date': TODAY.isoformat(), 'title': 'x',
        'due_time': '25:00'})
    check('несуществующее время — отказ', bad.status_code == 400)

    made = http.post(f'/dashboard/tasks?shop={slug}', headers=owner, json={
        'category': 'paint', 'due_date': TODAY.isoformat(), 'due_time': '9:30',
        'title': 'Покраска К555КК77', 'license_plate': 'к555кк77',
        'counterparty_uid': 'c-1', 'amount': '18700', 'note': 'R17 × 4'})
    check('задача поставлена', made.status_code == 200, made.text[:200])
    made = made.json()
    uid = made['uid']
    check('uid выдан сервером', len(uid) == 36, uid)
    check('источник — дашборд', made['source'] == 'dashboard')
    check('кто поставил', made['created_by'] == 'Иван Владелец',
          str(made['created_by']))
    check('время приведено к виду', made['due_time'] == '09:30')
    check('сумма числом', made['amount'] == 18700.0)
    check('контрагент по имени', made['counterparty_name'] == 'Еврошины')

    code, answer = exchange(cursor)
    check('задача из дашборда приехала в цех',
          by_uid(answer['tasks'], uid) is not None, str(answer)[:200])
    cursor = answer['now']

    moved = http.patch(f'/dashboard/tasks/{uid}', headers=owner, json={
        'due_date': (TODAY + timedelta(days=1)).isoformat(), 'due_time': None})
    check('перенесена на завтра',
          moved.status_code == 200 and moved.json()['due_date']
          == (TODAY + timedelta(days=1)).isoformat(), moved.text[:200])
    check('время снято', moved.json()['due_time'] is None)
    check('остальное не тронуто', moved.json()['title'] == 'Покраска К555КК77')

    done = http.patch(f'/dashboard/tasks/{uid}', headers=owner,
                      json={'done': True}).json()
    check('отмечено «сделано»', done['done_at'] is not None)
    check('и кем', done['done_by'] == 'Иван Владелец', str(done['done_by']))

    code, answer = exchange(cursor)
    pulled = by_uid(answer['tasks'], uid)
    check('правка из дашборда доехала до цеха',
          pulled is not None and pulled['done_at'] is not None, str(pulled))
    cursor = answer['now']

    undone = http.patch(f'/dashboard/tasks/{uid}', headers=owner,
                        json={'done': False}).json()
    check('отметку можно снять', undone['done_at'] is None
          and undone['done_by'] is None)

    gone = http.patch(f'/dashboard/tasks/{uid}', headers=owner,
                      json={'deleted': True})
    check('удалена', gone.status_code == 200 and gone.json()['deleted'] is True)
    listed = http.get('/dashboard/tasks', headers=owner,
                      params={'from': TODAY.isoformat(),
                              'to': (TODAY + timedelta(days=6)).isoformat()}).json()
    check('удалённой в календаре больше нет', by_uid(listed['tasks'], uid) is None)

    print()
    print('=== Удаление доходит до цеха ===')
    code, answer = exchange(cursor)
    pulled = by_uid(answer['tasks'], uid)
    check('цех получил удаление', pulled is not None and pulled['deleted'] is True,
          str(pulled))
    code, fresh = exchange(None)
    check('цеху с чистого листа удалённая не нужна',
          by_uid(fresh['tasks'], uid) is None)

    print()
    print('=== Удаление из цеха доходит до дашборда ===')
    exchange(answer['now'], [task_row('u-1', deleted=True,
                                      updated_at=iso(shop_now()))])
    listed = http.get('/dashboard/tasks', headers=owner, params=week).json()
    check('удалённая в цеху пропала из дашборда',
          by_uid(listed['tasks'], 'u-1') is None)

    print()
    print('=== Неотмеченные прошлые — сверху сегодня ===')
    exchange(None, [task_row('u-late', due_date=(TODAY - timedelta(days=3)).isoformat(),
                             title='Позвонить бухгалтеру', updated_at=iso(shop_now())),
                    task_row('u-late-done', due_date=(TODAY - timedelta(days=3)).isoformat(),
                             done_at=iso(HOUR_AGO), done_by='Пётр',
                             updated_at=iso(shop_now()))])
    listed = http.get('/dashboard/tasks', headers=owner, params=week).json()
    check('просроченная в списке «просрочено»',
          by_uid(listed['overdue'], 'u-late') is not None, str(listed['overdue'])[:200])
    check('сделанная прошлая — нет',
          by_uid(listed['overdue'], 'u-late-done') is None)
    later = http.get('/dashboard/tasks', headers=owner, params={
        'from': (TODAY + timedelta(days=7)).isoformat(),
        'to': (TODAY + timedelta(days=13)).isoformat()}).json()
    check('на будущей неделе «просрочено» не показываем', later['overdue'] == [])

    people = http.get('/dashboard/counterparties', headers=owner).json()
    check('контрагенты для выбора', [row['name'] for row in people] == ['Еврошины'],
          str(people))

    print()
    print('=== Чужая точка ===')
    code, alien = exchange(None, headers=OTHER)
    check('чужих задач не видит', alien['tasks'] == [] and alien['counterparties'] == [],
          str(alien)[:200])
    exchange(None, [task_row('u-late', title='Чужая с тем же uid',
                             updated_at=iso(shop_now() + timedelta(minutes=5)))],
             headers=OTHER)
    rows = server_task('u-late')
    mine = [row for row in rows if row.shop_id == shop_id]
    check('тот же uid у другой точки — другая задача',
          len(rows) == 2 and mine and mine[0].title == 'Позвонить бухгалтеру',
          str([(row.shop_id, row.title) for row in rows]))
    only = http.get('/dashboard/tasks', headers=owner,
                    params=dict(week, shop=other_id)).json()
    shown = only['overdue'] + only['tasks']
    check('дашборд по точке показывает только её',
          shown and all(row['shop_id'] == other_id for row in shown),
          str([(row['shop_id'], row['title']) for row in shown]))

    print()
    print('=== Кабинет: запись с комплектом со склада ===')
    db = SessionLocal()
    shop_settings.set_value(db, 'telegram_token', 'tok', shop=shop_id)
    shop_settings.set_value(db, 'telegram_chats', '100', shop=shop_id)
    shop_settings.set_value(db, 'telegram_chats_storage', '200', shop=shop_id)
    person = Client(account_id=account_id, phone='79160000001', name='Иван Петров')
    db.add(person)
    db.flush()
    sets = []
    for local_id, kind in ((58, 'Шины с дисками'), (59, 'Шины'), (60, 'Шины с дисками')):
        row = StoredSet(shop_id=shop_id, local_id=local_id, client_id=person.id,
                        license_plate='А123ВВ777', storage_type=kind,
                        diameter='R16', status='stored',
                        accepted_at=shop_now() - timedelta(days=100),
                        expires_at=shop_now() + timedelta(days=100))
        db.add(row)
        sets.append(row)
    db.commit()
    set_ids = [row.id for row in sets]
    cabinet = {'Authorization': f'Bearer {create_token(person.id)}'}
    db.close()

    at = datetime.combine(TODAY + timedelta(days=3), time(12, 0))
    sent.clear()
    booked = http.post(f'/booking?shop={slug}', headers=cabinet, json={
        'at': at.isoformat(), 'license_plate': 'А123ВВ777',
        'storage_ids': [set_ids[0]]})
    check('записался', booked.status_code == 200, booked.text[:200])
    appointment_id = booked.json()['id']

    rows = server_task(f'cab-appt-{appointment_id}')
    check('поставлена ровно одна задача', len(rows) == 1, str(len(rows)))
    task = rows[0]
    check('раздел — хранение', task.category == 'storage')
    check('к дате и времени записи', task.due_date == at.date()
          and task.due_time == '12:00', f'{task.due_date} {task.due_time}')
    check('номер комплекта — цеховой', task.storage_ref == '58'
          and '№58' in task.title, f'{task.storage_ref} / {task.title}')
    check('машина и клиент', task.license_plate == 'А123ВВ777'
          and task.client_name == 'Иван Петров' and task.client_phone == '79160000001')
    check('источник — кабинет', task.source == 'cabinet')
    check('в заметке — комплект', 'Шины с дисками' in (task.note or ''))
    check('сообщение ушло получателям склада, а не всем',
          [chat for chat, _ in sent] == ['200'], str(sent))
    check('в сообщении цеховой номер', sent and '№ 58' in sent[0][1],
          sent[0][1] if sent else '')

    db = SessionLocal()
    appointment = db.get(Appointment, appointment_id)
    again = db.query(StoredSet).filter(StoredSet.id == set_ids[0]).all()
    tasks.for_appointment(db, appointment, again, appointment.client)
    db.commit()
    db.close()
    check('повтор не ставит вторую', len(server_task(f'cab-appt-{appointment_id}')) == 1)

    code, answer = exchange(cursor)
    check('задача из кабинета приехала в цех',
          by_uid(answer['tasks'], f'cab-appt-{appointment_id}') is not None)
    cursor = answer['now']

    cancelled = http.delete(f'/booking/{appointment_id}', headers=cabinet)
    check('запись отменена', cancelled.status_code == 200, cancelled.text[:200])
    task = server_task(f'cab-appt-{appointment_id}')[0]
    check('задача снята вместе с записью', task.deleted is True)
    code, answer = exchange(cursor)
    pulled = by_uid(answer['tasks'], f'cab-appt-{appointment_id}')
    check('и цех об этом узнал', pulled is not None and pulled['deleted'] is True)
    cursor = answer['now']

    print()
    print('=== Цех переносит и отменяет запись ===')
    at2 = datetime.combine(TODAY + timedelta(days=4), time(12, 0))
    booked = http.post(f'/booking?shop={slug}', headers=cabinet, json={
        'at': at2.isoformat(), 'license_plate': 'А123ВВ777',
        'storage_ids': [set_ids[1]]})
    check('записался второй раз', booked.status_code == 200, booked.text[:200])
    second_id = booked.json()['id']

    moved = http.patch(f'/sync/appointments/{second_id}', headers=KEY, json={
        'scheduled_at': at2.replace(hour=15).isoformat()})
    check('перенесли', moved.status_code == 200, moved.text[:200])
    task = server_task(f'cab-appt-{second_id}')[0]
    check('задача поехала следом', task.due_time == '15:00', str(task.due_time))

    http.patch(f'/sync/appointments/{second_id}', headers=KEY,
               json={'status': 'cancelled'})
    task = server_task(f'cab-appt-{second_id}')[0]
    check('цех отменил — задача снята', task.deleted is True)

    print()
    print('=== Кабинет: «привезите комплект к дате» ===')
    sent.clear()
    wanted = datetime.combine(TODAY + timedelta(days=2), time(10, 0))
    first_try = http.post(f'/storage/{set_ids[2]}/request', headers=cabinet,
                          json={'at': wanted.isoformat()})
    check('заявка принята', first_try.status_code == 200, first_try.text[:200])
    http.post(f'/storage/{set_ids[2]}/request', headers=cabinet,
              json={'at': wanted.isoformat()})
    rows = server_task(f'cab-req-{set_ids[2]}')
    check('две одинаковые заявки — одна задача', len(rows) == 1, str(len(rows)))
    check('к дате и времени', rows[0].due_date == wanted.date()
          and rows[0].due_time == '10:00')
    check('заголовок с цеховым номером', rows[0].title == 'Привезти со склада №60',
          rows[0].title)
    check('сообщения — кладовщику', sent and all(chat == '200' for chat, _ in sent),
          str(sent))

    http.delete(f'/storage/{set_ids[2]}/request', headers=cabinet)
    check('заявку отменили — задача снята',
          server_task(f'cab-req-{set_ids[2]}')[0].deleted is True)

    print()
    print('=== Получатели склада не заданы — общие ===')
    db = SessionLocal()
    shop_settings.set_value(db, 'telegram_chats_storage', '', shop=shop_id)
    db.close()
    sent.clear()
    http.post(f'/storage/{set_ids[2]}/request', headers=cabinet,
              json={'at': wanted.isoformat()})
    check('ушло общим получателям', [chat for chat, _ in sent] == ['100'], str(sent))
    check('задача ожила', server_task(f'cab-req-{set_ids[2]}')[0].deleted is False)

    db = SessionLocal()
    check('у другой точки сообщения не настроены — ей ничего',
          notify.send(db, 'проверка', shop=other_id) == 0)
    check('без точки — никому', notify.send(db, 'проверка') == 0)
    db.close()

    print()
    print('=== Сводка владельцу ===')
    db = SessionLocal()
    shop_settings.set_value(db, 'telegram_chats_digest', '300', shop=shop_id)
    db.close()

    def digest(hour, minute=0):
        db = SessionLocal()
        try:
            here = db.get(Shop, shop_id)
            return tasks.digest_for_shop(
                db, here, now=datetime.combine(TODAY, time(hour, minute)))
        finally:
            db.close()

    exchange(None, [task_row('u-today', due_time='11:00', title='Привезти шины',
                             category='tires', license_plate='К555КК77',
                             updated_at=iso(shop_now()))])

    sent.clear()
    check('до утра — ничего', digest(8, 30) == [] and sent == [])
    check('утром — сводка', digest(9, 5) == ['morning'], str(sent))
    check('утренняя — получателям сводки', [chat for chat, _ in sent] == ['300'],
          str(sent))
    text = sent[0][1] if sent else ''
    check('в ней задачи на сегодня', 'На сегодня' in text and 'Привезти шины' in text
          and 'К555КК77' in text and 'Шины' in text, text)
    check('и сколько просрочено', 'Просрочено: 2' in text, text)
    check('сделанные не попали', 'Заказать грузики' not in text, text)

    sent.clear()
    check('второй раз утром — нет', digest(9, 10) == [] and sent == [])
    check('днём — нет', digest(15, 0) == [] and sent == [])
    check('вечером — что не отмечено', digest(20, 1) == ['evening'], str(sent))
    text = sent[0][1] if sent else ''
    check('вечерняя — список', 'Не отмечено: 4' in text
          and 'Позвонить бухгалтеру' in text, text)
    sent.clear()
    check('второй раз вечером — нет', digest(20, 6) == [] and sent == [])

    db = SessionLocal()
    for key in ('task_digest_sent_morning', 'task_digest_sent_evening'):
        shop_settings.set_value(db, key, '', shop=shop_id)
    shop_settings.set_value(db, 'telegram_chats_digest', '', shop=shop_id)
    db.close()
    sent.clear()
    check('утро после вечера не шлём', digest(21, 0) == ['evening'], str(sent))
    check('получателей сводки нет — общим', [chat for chat, _ in sent] == ['100'],
          str(sent))

    db = SessionLocal()
    shop_settings.set_value(db, 'task_digest_sent_evening', '', shop=shop_id)
    shop_settings.set_value(db, 'task_digest_enabled', '0', shop=shop_id)
    db.close()
    sent.clear()
    check('выключено — не шлём', digest(21, 0) == [] and sent == [])

    db = SessionLocal()
    result = tasks.send_digests(db, now=datetime.combine(TODAY, time(9, 5)))
    db.close()
    check('обход всех точек не падает на точке без бота',
          result == {'morning': 0, 'evening': 0}, str(result))

finish()
