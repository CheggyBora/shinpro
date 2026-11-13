"""
Контроль в сводке дашборда и выработка мастеров (13.11.2026).

  · скидка от 15% — в «Контроле», 10% — нет; возврат; недостача кассы;
  · мастера: средний чек и гарантийные переделки — по исходному наряду.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_control_dashboard_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-control-dashboard-0123'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-control'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.services.dashboard_service import DashboardService
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
moment = shop_now().replace(microsecond=0)


def visit(local_id, total, full, discount=0, master=1, **extra):
    row = {'local_id': local_id, 'visited_at': moment.isoformat(), 'total_amount': total,
           'payment_method': 'cash', 'general_discount': discount, 'shift_local_id': 7,
           'license_plate': f'А00{local_id}АА77',
           'items': [{'service_name': 'Шиномонтаж', 'quantity': 1, 'unit_price': full, 'total': total,
                      'discount_percent': discount, 'direction': 'tire'}],
           'accruals': [{'employee_local_id': master, 'amount': round(total * 0.4, 2)}]}
    row.update(extra)
    return row


with TestClient(app) as http:
    answer = http.post('/sync/push', headers=KEY, json={
        'employees': [{'local_id': 1, 'name': 'Иван'}, {'local_id': 2, 'name': 'Пётр'}],
        'shifts': [{'local_id': 7, 'started_at': moment.isoformat(), 'status': 'closed',
                    'ended_at': moment.isoformat(), 'cash_diff': -300, 'cash_diff_reason': 'не нашли'}],
        'visits': [visit(1, 1800, 2000, discount=10),
                   visit(2, 1600, 2000, discount=20),
                   visit(3, 2000, 2000, refunded_amount=500, refunded_at=moment.isoformat(),
                         refund_reason='клиент недоволен'),
                   visit(4, 0, 0, master=2, is_warranty=True, warranty_of_local_id=1,
                         accruals=[{'employee_local_id': 2, 'amount': 0}])]})
    check('обмен принят', answer.status_code == 200, answer.text[:300])

    db = SessionLocal()
    day = moment.date()
    control = DashboardService(db).summary(day, day)['control']
    check('скидка 20% — замечание, 10% — нет', [r['local_id'] for r in control['discounts']] == [2]
          and control['discounts'][0]['amount'] == 400, str(control['discounts']))
    check('возврат 500 с причиной', control['refunds'] and control['refunds'][0]['amount'] == 500
          and control['refunds'][0]['reason'] == 'клиент недоволен', str(control['refunds']))
    check('недостача 300', control['cash'] and control['cash'][0]['diff'] == -300, str(control['cash']))
    masters = {m['employee_local_id']: m for m in DashboardService(db).masters(day, day)}
    ivan = masters.get(1, {})
    check('у Ивана гарантийная переделка — по его наряду', ivan.get('warranty') == 1, str(ivan))
    check('средний чек Ивана', ivan.get('orders') and
          abs(ivan['average_check'] - ivan['revenue'] / ivan['orders']) < 0.01, str(ivan))
    check('у Петра переделок нет', masters.get(2, {}).get('warranty', 0) == 0, str(masters.get(2)))
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
