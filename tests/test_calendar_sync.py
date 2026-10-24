"""
Календарь целиком: цех ↔ сервер ↔ дашборд (docs/calendar.md).

Настоящий сервер (FastAPI) и программа цеха в одном прогоне: обмен идёт
тем же кодом, что в работе, только без сети.

  · задача из цеха появляется в дашборде;
  · задача из дашборда — в цеху, правка и «сделано» доходят обратно;
  · удаление доходит до второй стороны;
  · контрагент из цеха виден в дашборде для выбора.
"""
import _setup
from _setup import use_temp_db, check, finish

import os
import sys
import tempfile
from datetime import timedelta

use_temp_db('calendar_sync')
os.chdir(_setup.PROJECT_DIR)

_server_db = os.path.join(tempfile.gettempdir(), 'tire_calendar_sync_server.db')
if os.path.exists(_server_db):
    os.remove(_server_db)
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _server_db.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-calendar-sync'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-calendar-sync'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
sys.path.insert(0, os.path.join(_setup.PROJECT_DIR, 'server'))

from fastapi.testclient import TestClient
from app.main import app as server_app
from app.database import SessionLocal as ServerSession
from app.models import Shop

from config import init_db, SessionLocal
from models.calendar import TIRES, WORK
from services.sync_service import SyncService, SyncError
from services.calendar_service import CalendarService
from utils import get_moscow_time, as_naive

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def staff_headers(http):
    """Владелец в дашборде: заводим и выдаём токен напрямую, без SMS."""
    from app.models.staff import StaffUser, ROLE_OWNER
    from app.security import create_staff_token
    sdb = ServerSession()
    shop = sdb.query(Shop).first()
    staff = StaffUser(account_id=shop.account_id, phone='79160000999',
                      name='Владелец', role=ROLE_OWNER)
    sdb.add(staff)
    sdb.commit()
    token = create_staff_token(staff)
    sdb.close()
    return {'Authorization': f'Bearer {token}'}


with TestClient(server_app) as server:
    sdb = ServerSession()
    slug = sdb.query(Shop).first().slug
    sdb.close()

    def call(method, path, payload=None):
        answer = server.request(method, path, json=payload, headers=KEY)
        if answer.status_code >= 400:
            raise SyncError(answer.text)
        return answer.json()

    init_db()
    db = SessionLocal()
    sync = SyncService(db)
    sync._call = call
    calendar = CalendarService(db)
    today = as_naive(get_moscow_time()).date()

    print('=== Задача из цеха — в дашборде ===')
    party = calendar.save_counterparty(name='Еврошины', kind='поставщик шин')
    shop_task = calendar.create('Еврошины — 8 шин R17', today, category=TIRES, due_time='10:00',
                                license_plate='А123ВВ777', counterparty_uid=party.uid)
    sync.tasks_exchange()
    check('ушла — больше не ждёт', calendar.unsent() == ([], []))
    headers = staff_headers(server)
    listed = server.get(f'/dashboard/tasks?from={today}&to={today}&shop={slug}', headers=headers)
    check('дашборд отвечает', listed.status_code == 200, listed.text[:300])
    rows = listed.json() if listed.status_code == 200 else []
    rows = rows.get('tasks', rows) if isinstance(rows, dict) else rows
    mine = next((r for r in rows if r.get('uid') == shop_task.uid), None)
    check('задача видна в дашборде', mine is not None and mine.get('due_time') == '10:00', str(rows)[:300])
    parties = server.get(f'/dashboard/counterparties?shop={slug}', headers=headers)
    names = [p.get('name') for p in (parties.json() if parties.status_code == 200 else [])]
    check('контрагент виден для выбора', 'Еврошины' in names, str(names))

    print()
    print('=== Задача из дашборда — в цеху ===')
    created = server.post(f'/dashboard/tasks?shop={slug}', headers=headers, json={
        'category': 'work', 'due_date': today.isoformat(), 'title': 'Позвонить бухгалтеру'})
    check('поставили из дашборда', created.status_code in (200, 201), created.text[:300])
    uid = created.json().get('uid') if created.status_code in (200, 201) else None
    sync.tasks_exchange()
    row = calendar.by_uid(uid) if uid else None
    check('появилась в цеху', row is not None and row.title == 'Позвонить бухгалтеру')

    print()
    print('=== Правка, «сделано» и удаление ходят в обе стороны ===')
    moved = server.patch(f'/dashboard/tasks/{shop_task.uid}?shop={slug}', headers=headers,
                         json={'due_time': '15:00', 'done': True})
    check('владелец перенёс и отметил', moved.status_code == 200, moved.text[:300])
    sync.tasks_exchange()
    db.refresh(shop_task)
    check('в цеху — новое время', shop_task.due_time == '15:00', shop_task.due_time)
    check('и отметка «сделано»', shop_task.done_at is not None)
    if row is not None:
        calendar.delete(row)
        sync.tasks_exchange()
        after = server.get(f'/dashboard/tasks?from={today}&to={today}&shop={slug}', headers=headers).json()
        after = after.get('tasks', after) if isinstance(after, dict) else after
        check('удалённая в цеху пропала из дашборда', all(r.get('uid') != uid for r in after))

    db.close()

finish()
