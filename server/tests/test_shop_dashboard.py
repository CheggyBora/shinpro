"""
Магазин в дашборде (решение владельца 08.11.2026).

  · строки и начисления магазина сервер хранит как «shop», а не
    превращает в шиномонтаж;
  · фильтр «Магазин» — выручка и зарплата с продаж;
  · точка говорит, включён ли у неё магазин.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_shop_dashboard_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-shop-dashboard-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-shop'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Shop, VisitItem, SalaryAccrual
from app.services import shop_settings
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
    answer = http.post('/sync/push', headers=KEY, json={
        'settings': {'direction_shop': '1'},
        'visits': [{
            'local_id': 1, 'visited_at': paid.isoformat(), 'total_amount': 2150.0,
            'payment_method': 'cash', 'directions': 'tire',
            'items': [{'service_name': 'Шиномонтаж', 'quantity': 1, 'unit_price': 2000, 'total': 2000,
                       'direction': 'tire'},
                      {'service_name': 'Ароматизатор', 'quantity': 1, 'unit_price': 150, 'total': 150,
                       'direction': 'shop', 'is_goods': True}],
            'accruals': [{'employee_local_id': 1, 'amount': 800, 'direction': 'tire'},
                         {'employee_local_id': 1, 'amount': 15, 'direction': 'shop'}]}]})
    check('цех отдал наряд', answer.status_code == 200, answer.text[:200])

    db = SessionLocal()
    shop = db.query(Shop).first()
    items = {row.service_name: row.direction for row in db.query(VisitItem).all()}
    check('строка магазина — «shop»', items.get('Ароматизатор') == 'shop', str(items))
    accruals = sorted(row.direction for row in db.query(SalaryAccrual).all())
    check('начисление с продажи — «shop»', 'shop' in accruals, str(accruals))
    check('магазин у точки включён', shop_settings.shop_on(db, shop))

    day = paid.date()
    whole = DashboardService(db).summary(day, day)
    only_shop = DashboardService(db, direction='shop').summary(day, day)
    check('всё вместе — 2150', whole['revenue'] == 2150.0, str(whole['revenue']))
    check('«Магазин» — 150', only_shop['revenue'] == 150.0, str(only_shop['revenue']))
    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
