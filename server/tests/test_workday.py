"""
Рабочий день — это смена (решение владельца 27.10.2026).

Смена открыта в 18:00 1-го и закрыта в 03:00 2-го. Наряд, пробитый в
01:00 2-го, — в её дне, 1-м. Возврат в 02:00 2-го — тоже в 1-м. Наряд
без смены (старая запись) — по календарному дню, как раньше. «Сегодня»
в час ночи при открытой вчерашней смене — вчерашний день.
"""
import os
import sys
import tempfile
from datetime import date, datetime

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_workday_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-workday-0123456789abcdef'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-workday'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import CashOrder, SalaryAccrual, Shop, ShopShift, Visit
from app.services import workday
from app.services.dashboard_service import DashboardService

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


D1, D2 = date(2026, 10, 1), date(2026, 10, 2)

with TestClient(app):
    db = SessionLocal()
    shop = db.query(Shop).first()
    sid = shop.id

    db.add(ShopShift(shop_id=sid, local_id=7, started_at=datetime(2026, 10, 1, 18, 0),
                     ended_at=datetime(2026, 10, 2, 3, 0), status='closed'))
    db.add(ShopShift(shop_id=sid, local_id=8, started_at=datetime(2026, 10, 2, 9, 0),
                     ended_at=datetime(2026, 10, 2, 20, 0), status='closed'))
    # Вечером в смене 7, ночью после полуночи — тоже в смене 7
    evening = Visit(local_id=1, shop_id=sid, shift_local_id=7, total_amount=1000,
                    visited_at=datetime(2026, 10, 1, 19, 0), payment_method='cash')
    night = Visit(local_id=2, shop_id=sid, shift_local_id=7, total_amount=2000,
                  visited_at=datetime(2026, 10, 2, 1, 0), payment_method='cash',
                  refunded_amount=500, refunded_at=datetime(2026, 10, 2, 2, 0))
    day = Visit(local_id=3, shop_id=sid, shift_local_id=8, total_amount=4000,
                visited_at=datetime(2026, 10, 2, 12, 0), payment_method='card')
    # Старая запись без смены — по календарному дню
    old = Visit(local_id=4, shop_id=sid, total_amount=300,
                visited_at=datetime(2026, 10, 2, 0, 30), payment_method='cash')
    db.add_all([evening, night, day, old])
    db.flush()
    db.add(SalaryAccrual(visit_id=night.id, employee_local_id=1, amount=800))
    db.add(SalaryAccrual(visit_id=day.id, employee_local_id=1, amount=1600))
    db.add(CashOrder(shop_id=sid, uid='n1', kind='out', amount=150, shift_local_id=7,
                     created_at=datetime(2026, 10, 2, 2, 30)))
    db.commit()

    service = DashboardService(db, shop_ids=[sid])

    print('=== День 1-й — это смена 18:00–03:00 ===')
    first = service.summary(D1, D1)
    check('оба наряда смены, включая пробитый после полуночи',
          first['cars'] == 2 and first['revenue'] == 3000, str(first)[:200])
    check('ночной возврат — в этой смене', first['refunded'] == 500, str(first['refunded']))
    check('зарплата — по смене', first['salary'] == 800, str(first['salary']))

    second = service.summary(D2, D2)
    check('2-й — дневная смена и старая запись без смены',
          second['cars'] == 2 and second['revenue'] == 4300 and second['refunded'] == 0,
          str(second)[:200])

    both = service.summary(D1, D2)
    days = {row['day']: row for row in both['by_day']}
    check('по дням: ночь не перетекает во 2-е',
          days['2026-10-01']['revenue'] == 2500 and days['2026-10-01']['cars'] == 2
          and days['2026-10-02']['revenue'] == 4300, str(both['by_day']))

    masters = {row['employee_local_id']: row for row in service.masters(D1, D1)}
    check('мастера — по смене', masters[1]['salary'] == 800, str(masters))
    check('наряды 1-го — оба смены 7',
          sorted(row['local_id'] for row in service.orders(D1, D1)) == [1, 2])

    print('\n=== Касса — тоже сменами ===')
    from app.services import cash
    rows = cash.orders_for(db, [sid], None, None, {sid: 'РИФ'},
                           period=workday.Period(db, D1, D1, [sid]))
    check('ордер в 02:30 — в смене 1-го', len(rows) == 1, str(rows)[:200])

    print('\n=== Какой сейчас рабочий день ===')
    db.add(ShopShift(shop_id=sid, local_id=9, started_at=datetime(2026, 10, 5, 18, 0),
                     status='open'))
    db.commit()
    check('открыта смена с 5-го вечера — рабочий день 5-е, даже если уже ночь',
          workday.work_day(db, [sid]) == date(2026, 10, 5))

    db.close()

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
