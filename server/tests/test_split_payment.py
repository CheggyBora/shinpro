"""
Раздельная оплата: часть наличными, часть картой (решение владельца 30.10.2026).

  · цех присылает payment_method = mixed и cash_amount — сервер хранит;
  · в сводке наличная часть идёт в «наличные», остаток — в «карту»;
  · фильтр «наличные» и «карта» показывают раздельный наряд в обоих;
  · в списке и карточке видно, сколько чем заплатили.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_split_payment_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-split-payment-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-split-payment'
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
    visit = dict(visited_at=paid.isoformat())
    answer = http.post('/sync/push', headers=KEY, json={'visits': [
        dict(visit, local_id=1, total_amount=5400.0, payment_method='mixed', cash_amount=2000.0),
        dict(visit, local_id=2, total_amount=1000.0, payment_method='cash'),
        dict(visit, local_id=3, total_amount=700.0, payment_method='card',
             cash_amount=300.0)]})
    check('цех отдал наряды', answer.status_code == 200, str(answer.status_code))

    db = SessionLocal()
    row = db.query(Visit).filter(Visit.local_id == 1).first()
    check('раздельная: наличные сохранены', row.payment_method == 'mixed'
          and row.cash_amount == 2000.0, f'{row.payment_method} {row.cash_amount}')
    card_only = db.query(Visit).filter(Visit.local_id == 3).first()
    check('у «карты» наличных не бывает', card_only.cash_amount is None)

    service = DashboardService(db)
    summary = service.summary(paid.date(), paid.date())
    check('наличные: 1000 + 2000', summary['cash'] == 3000.0, str(summary['cash']))
    check('карта: 700 + 3400', summary['card'] == 4100.0, str(summary['card']))

    cash_rows = {r['local_id'] for r in service.orders(paid.date(), paid.date(),
                                                       payment_method='cash')}
    card_rows = {r['local_id'] for r in service.orders(paid.date(), paid.date(),
                                                       payment_method='card')}
    check('фильтр «наличные» — с раздельной', cash_rows == {1, 2}, str(cash_rows))
    check('фильтр «карта» — с раздельной', card_rows == {1, 3}, str(card_rows))

    row = [r for r in service.orders(paid.date(), paid.date()) if r['local_id'] == 1][0]
    check('в списке — сколько наличными', row['payment_method'] == 'mixed'
          and row['cash_amount'] == 2000.0)
    card = service.order_card(1)
    check('в карточке — тоже', card['cash_amount'] == 2000.0)
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
