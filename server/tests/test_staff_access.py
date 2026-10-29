"""
Доступ в дашборд (решения владельца 29.10.2026).

  · вход только звонком: звонок подключён, SMS нет — код не высылается;
  · смена номера: старый номер не пускает, ПИН сброшен; номер владельца
    меняет только владелец; сервер не воскрешает старый номер владельца;
  · владелец сервера — по флагу, «Заказчики» остаются после смены номера;
  · свои галочки календаря, склада и кассы;
  · Telegram и отчёты у человека: уходят только при праве на содержимое,
    цех узнаёт ники в ответе на обмен, сервер шлёт по ним сводку задач.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_staff_access_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-51'
ADMIN_PHONE = '+7 916 555-12-51'
NEW_OWNER_PHONE = '+7 903 111-22-51'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-staff-access-1234'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-staff-access'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging

from fastapi.testclient import TestClient

from app.main import app, _mark_platform_owner
from app.database import SessionLocal
from app.models import Shop, StaffUser
from app.services import notify, onboarding, shop_settings
from app.services.staff_service import StaffService

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


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
KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify', json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


with TestClient(app) as http:
    http.post('/sync/push', headers=KEY, json={'settings': {'telegram_token': 'bot-token'}})
    owner = enter(http, OWNER_PHONE, '4832')
    db = SessionLocal()
    shop = db.query(Shop).first()

    print('=== Вход только звонком ===')
    start = http.post('/staff/start', json={'phone': ADMIN_PHONE}).json()
    check('звонка нет — код можно (как раньше)', start['code_available'] is True)
    shop_settings.set_value(db, 'call_provider', 'flashcall', shop=shop)
    shop_settings.set_value(db, 'call_token', 'flash-key', shop=shop)
    db.commit()
    start = http.post('/staff/start', json={'phone': ADMIN_PHONE}).json()
    check('звонок есть, SMS нет — только звонок',
          start['call_available'] is True and start['code_available'] is False, str(start))
    refused = http.post('/staff/code', json={'phone': OWNER_PHONE})
    check('код не высылается', refused.status_code == 400 and 'звонком' in refused.json()['detail'],
          refused.text)
    client_start = http.post('/auth/start', json={'phone': '+7 905 000-00-51'})
    check('на сайте записи — тоже только звонок',
          client_start.status_code == 200 and client_start.json().get('code_available') is False,
          client_start.text)
    shop_settings.set_value(db, 'call_token', '', shop=shop)
    shop_settings.set_value(db, 'call_provider', 'off', shop=shop)
    db.commit()

    print('\n=== Админ, права, отчёты ===')
    added = http.post('/staff/people', headers=owner, json={
        'phone': ADMIN_PHONE, 'name': 'Ольга', 'role': 'admin'}).json()
    check('админу по умолчанию — календарь, склад, касса',
          {'calendar', 'stock', 'cash'} <= set(added['permissions'])
          and 'staff' not in added['permissions'], str(added['permissions']))
    admin = enter(http, ADMIN_PHONE, '5821')
    check('календарь открыт', http.get('/dashboard/tasks', headers=admin).status_code == 200)

    http.patch(f"/staff/people/{added['id']}", headers=owner, json={'permissions': ['orders']})
    admin = enter(http, ADMIN_PHONE, '5821')
    check('сняли «Календарь» — календаря нет', http.get('/dashboard/tasks', headers=admin).status_code == 403)
    check('сняли «Кассу» — кассы нет', http.get('/dashboard/cash', headers=admin).status_code == 403)

    bad = http.patch(f"/staff/people/{added['id']}", headers=owner, json={'telegram': '@иван'})
    check('кривой ник — понятная ошибка', bad.status_code == 400 and 'латиницей' in bad.json()['detail'])
    saved = http.patch(f"/staff/people/{added['id']}", headers=owner, json={
        'telegram': '@Olga_Admin', 'reports': ['shift', 'task', 'digest', 'nonsense']}).json()
    check('ник и отчёты сохранены', saved['telegram'] == 'olga_admin'
          and saved['reports'] == ['shift', 'task', 'digest'], str(saved))
    roles = http.get('/staff/roles', headers=owner).json()
    check('список отчётов с правами', any(r['key'] == 'shift' and r['permission'] == 'revenue'
                                          for r in roles['reports']))

    pushed = http.post('/sync/push', headers=KEY, json={'settings': {
        'telegram_usernames': '{"olga_admin": "777"}'}}).json()
    check('без права «выручка» сводку по смене не получит',
          'shift' not in pushed.get('staff_reports', {}), str(pushed.get('staff_reports')))
    http.patch(f"/staff/people/{added['id']}", headers=owner,
               json={'permissions': ['orders', 'revenue', 'calendar']})
    pushed = http.post('/sync/push', headers=KEY, json={}).json()
    check('цех узнаёт, кому слать: сводка по смене и задачи',
          pushed['staff_reports'].get('shift') == ['olga_admin']
          and pushed['staff_reports'].get('task') == ['olga_admin'], str(pushed['staff_reports']))
    people = {p['id']: p for p in http.get('/staff/people', headers=owner).json()}
    check('видно, что пишет боту', people[added['id']]['telegram_ok'] is True)
    db.expire_all()
    check('сводка задач с сервера — ей тоже', '777' in notify.chats_for(db, shop, 'digest'))

    print('\n=== Смена номера ===')
    owner_row = db.query(StaffUser).filter(StaffUser.role == 'owner').first()
    http.patch(f"/staff/people/{added['id']}", headers=owner,
               json={'permissions': ['orders', 'staff']})
    admin = enter(http, ADMIN_PHONE, '5821')
    stolen = http.patch(f'/staff/people/{owner_row.id}', headers=admin,
                        json={'phone': '+7 999 000-00-51'})
    check('номер владельца админ сменить не может',
          stolen.status_code == 400 and 'только владелец' in stolen.json()['detail'], stolen.text)
    self_promote = http.patch(f"/staff/people/{added['id']}", headers=admin, json={'role': 'owner'})
    check('админ не может сделать себя владельцем',
          self_promote.status_code == 400 and 'только владелец' in self_promote.json()['detail'],
          self_promote.text)
    changed = http.patch(f'/staff/people/{owner_row.id}', headers=owner, json={'phone': NEW_OWNER_PHONE})
    check('владелец сменил свой номер', changed.status_code == 200 and changed.json()['pin_is_set'] is False,
          changed.text)
    old = http.post('/staff/login', json={'phone': OWNER_PHONE, 'pin': '4832'})
    check('старый номер больше не пускает', old.status_code == 401)
    check('с новым номером — заново подтвердить номер',
          http.post('/staff/start', json={'phone': NEW_OWNER_PHONE}).json()['step'] != 'pin')

    db.expire_all()
    again = StaffService(db, owner_row.account_id).ensure_owner(OWNER_PHONE)
    check('перезапуск сервера не заводит владельца со старым номером',
          again.id == owner_row.id and db.query(StaffUser).filter(StaffUser.role == 'owner').count() == 1)
    _mark_platform_owner(db, owner_row.account_id)
    db.expire_all()
    owner_row = db.query(StaffUser).filter(StaffUser.id == owner_row.id).first()
    check('«Заказчики» остались у владельца с новым номером',
          owner_row.is_platform_owner and onboarding.is_platform_owner(db, owner_row))
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
