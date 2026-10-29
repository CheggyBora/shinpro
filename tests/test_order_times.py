"""
Время наряда: когда создан и когда пробит (решение владельца 29.10.2026).

Видно в открытом наряде, в истории, в отчёте по нарядам; серверу
уходит время создания — дашборд показывает «10:12 → 11:05 · 53 мин».
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('order_times')

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Service, WorkOrder
from services import OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService
from services.statistics_service import StatisticsService
from services.sync_service import SyncService
from utils import short_stamp, span_text

init_db()
db = SessionLocal()

print('=== Как время пишется ===')
today = datetime(2026, 10, 29).date()
check('сегодня — только время', short_stamp(datetime(2026, 10, 29, 10, 12), today) == '10:12')
check('другой день — с датой', short_stamp(datetime(2026, 10, 28, 18, 40), today) == '28.10 18:40')
check('другой год — с годом', short_stamp(datetime(2025, 10, 28, 18, 40), today) == '28.10.2025 18:40')
check('нет времени — прочерк', short_stamp(None) == '—')
check('53 мин', span_text(datetime(2026, 10, 29, 10, 12), datetime(2026, 10, 29, 11, 5)) == '53 мин')
check('2 ч 05 мин', span_text(datetime(2026, 10, 29, 9, 0), datetime(2026, 10, 29, 11, 5)) == '2 ч 05 мин')
check('больше суток', span_text(datetime(2026, 10, 27, 9, 0), datetime(2026, 10, 29, 11, 5)) == '2 дн 2 ч')

print('\n=== Наряд: создан и пробит ===')
ShiftService(db).open_shift(open_posts=1)
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.commit()
orders = OrderService(db)
order = orders.create_order('А123ВВ777', 'R16', 'car')
orders.add_service_to_order(order.id, db.query(Service).first().id)
order = db.query(WorkOrder).get(order.id)
order.created_at = order.created_at - timedelta(minutes=53)
db.commit()
SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))
db.refresh(order)
check('у наряда есть оба времени', order.created_at is not None and order.paid_at is not None)

start = datetime.combine(order.paid_at.date(), datetime.min.time())
report = StatisticsService(db).get_orders_report(start, start + timedelta(days=1))
check('в отчёте по нарядам — время создания', report and report[0].get('created_at') == order.created_at)

visits = SyncService(db)._collect_visits()
mine = [v for v in visits if v['local_id'] == order.id]
check('серверу уходит время создания', mine and mine[0].get('opened_at') is not None
      and mine[0]['opened_at'] < mine[0]['visited_at'], str(mine[:1]))

db.close()
finish()
