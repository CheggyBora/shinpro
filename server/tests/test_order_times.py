"""
Время наряда: когда создан и когда пробит (решение владельца 29.10.2026).

  · цех присылает opened_at — сервер хранит его рядом с visited_at;
  · старый цех opened_at не присылает — уже известное не стирается;
  · дашборд отдаёт оба времени в списке нарядов и в карточке.
"""
import os
import sys
import tempfile
from datetime import timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_order_times_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-order-times-0123456789ab'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-order-times'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Visit
from app.services.dashboard_service import DashboardService
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

with TestClient(app) as http:
    paid = shop_now().replace(microsecond=0)
    opened = paid - timedelta(minutes=53)
    answer = http.post('/sync/push', headers=KEY, json={'visits': [
        {'local_id': 7, 'visited_at': paid.isoformat(), 'opened_at': opened.isoformat(),
         'total_amount': 1500.0}]})
    check('цех отдал наряд', answer.status_code == 200, str(answer.status_code))

    db = SessionLocal()
    row = db.query(Visit).filter(Visit.local_id == 7).first()
    check('время создания сохранено', row.opened_at == opened, str(row.opened_at))

    http.post('/sync/push', headers=KEY, json={'visits': [
        {'local_id': 7, 'visited_at': paid.isoformat(), 'total_amount': 1500.0}]})
    db.expire_all()
    row = db.query(Visit).filter(Visit.local_id == 7).first()
    check('старый цех без opened_at его не стирает', row.opened_at == opened)

    service = DashboardService(db)
    card = service.order_card(7)
    check('в карточке наряда — оба времени',
          card['opened_at'] == opened and card['visited_at'] == paid)
    rows = service.orders(paid.date(), paid.date())
    check('в списке нарядов — время создания', rows and rows[0]['opened_at'] == opened)
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
