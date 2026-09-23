"""
Сводка по смене, автозакрытие и отправка в Telegram.

Смену регулярно забывают закрыть. Программа закрывает её утром сама,
считает итоги и отправляет владельцу сводку.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('shift_report')

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Service, Shift, AuditLog
from services import OrderService, SalaryService, EmployeeService, TelegramService
from services.shift_service import ShiftService
from services.shift_report_service import ShiftReportService
from services.settings_service import SettingsService
from services.export_service import get_exports_dir, get_default_exports_dir
from utils import as_naive

init_db()
db = SessionLocal()

settings = SettingsService(db)
settings.ensure_defaults()

shift_service = ShiftService(db)
report_service = ShiftReportService(db)
order_service = OrderService(db)

shift = shift_service.open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.register_employee(2)
emp.start_shift(1)
emp.start_shift(2)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0,
               consumable_cost=100.0))
db.commit()
service = db.query(Service).first()

for plate, method in [('А123ВВ777', 'cash'), ('К900ОР99', 'card')]:
    order = order_service.create_order(plate, 'R16', 'car')
    order_service.add_service_to_order(order.id, service.id)
    SalaryService(db).process_payment(order.id, method, order_service.calculate_total(order.id))

print('=== Сводка по смене ===')
summary = report_service.build_summary(shift)
check('нарядов в смене 2', summary['orders_count'] == 2, str(summary['orders_count']))
check('выручка 2000', summary['revenue'] == 2000.0, str(summary['revenue']))
check('наличными 1000', summary['cash'] == 1000.0, str(summary['cash']))
check('безналом 1000', summary['card'] == 1000.0, str(summary['card']))
check('расходники 200', summary['consumables'] == 200.0, str(summary['consumables']))
check('зарплата посчитана', summary['salary_total'] > 0, str(summary['salary_total']))
check('разбивка по двум мастерам', len(summary['by_master']) == 2,
      str(summary['by_master']))
check('маржа = выручка - расходники - зарплата',
      summary['margin'] == round(summary['revenue'] - summary['consumables']
                                 - summary['salary_total'], 2),
      str(summary['margin']))
check('средний чек 1000', summary['average_check'] == 1000.0, str(summary['average_check']))

print('\n=== Текст сводки ===')
text = report_service.format_summary(summary)
for fragment in ('Смена', 'Выручка', 'Расходники', 'Зарплата', 'мастер №1',
                 'Осталось шиномонтажу'):
    check(f'в тексте есть «{fragment}»', fragment in text, text[:120])

print('\n=== Без настроек ничего не отправляется ===')
telegram = TelegramService(db)
check('Telegram не настроен', telegram.is_configured() is False)
check('отправка сводки не выполняется', report_service.send_summary(shift) is False)

try:
    telegram.send_message('проверка')
    check('отправка без настроек отклонена', False, 'сообщение ушло')
except Exception as e:
    check('отправка без настроек отклонена', True, str(e))

print('\n=== Настройки Telegram сохраняются ===')
telegram.save_settings('123:ABC', '-100500')
check('токен сохранён', telegram.get_token() == '123:ABC')
check('чат сохранён', telegram.get_chat_id() == '-100500')
check('теперь считается настроенным', telegram.is_configured() is True)
telegram.save_settings('', '')

print('\n=== Правило автозакрытия ===')
check('время автозакрытия 9:00', report_service.get_autoclose_time() == (9, 0),
      str(report_service.get_autoclose_time()))

# Смена открыта сегодня — закрывать рано
check('свежую смену не закрываем',
      report_service.find_overdue_shift() is None)

# Отматываем открытие на вчера
yesterday = as_naive(shift.start_time) - timedelta(days=1)
shift.start_time = yesterday
db.commit()

before_deadline = datetime(yesterday.year, yesterday.month, yesterday.day,
                           8, 30) + timedelta(days=1)
after_deadline = datetime(yesterday.year, yesterday.month, yesterday.day,
                          9, 15) + timedelta(days=1)

check('до 9:00 не закрываем',
      report_service.find_overdue_shift(now=before_deadline) is None)
check('после 9:00 смена подлежит закрытию',
      report_service.find_overdue_shift(now=after_deadline) is not None)

print('\n=== Автозакрытие срабатывает ===')
closed = report_service.autoclose_if_needed(now=after_deadline)
check('смена закрыта', closed is not None and closed.id == shift.id)
db.refresh(shift)
check('статус closed', shift.status == 'closed', shift.status)
check('время закрытия проставлено', shift.end_time is not None)

entries = db.query(AuditLog).filter(AuditLog.action == 'shift.autoclose').all()
check('автозакрытие записано в журнал', len(entries) == 1, str(len(entries)))

check('повторно закрывать нечего',
      report_service.autoclose_if_needed(now=after_deadline) is None)

print('\n=== Автозакрытие можно выключить ===')
new_shift = shift_service.open_shift(open_posts=1)
new_shift.start_time = as_naive(new_shift.start_time) - timedelta(days=2)
db.commit()

settings.set('shift_autoclose_enabled', '0')
check('выключенное автозакрытие ничего не трогает',
      report_service.find_overdue_shift(now=after_deadline) is None)

settings.set('shift_autoclose_enabled', '1')
check('включённое снова находит смену',
      report_service.find_overdue_shift() is not None)

print('\n=== Папка выгрузки берётся из настроек ===')
import os
import tempfile

check('по умолчанию папка рядом с программой',
      get_exports_dir(db) == get_default_exports_dir(),
      get_exports_dir(db))

custom = os.path.join(tempfile.gettempdir(), 'tire_shop_custom_exports')
settings.set('export_folder', custom)
check('используется заданная папка', get_exports_dir(db) == custom, get_exports_dir(db))
check('папка создана', os.path.isdir(custom))

settings.set('export_folder', 'Z:\\несуществующий\\путь')
fallback = get_exports_dir(db)
check('недоступная папка не ломает выгрузку',
      fallback == get_default_exports_dir(), fallback)

settings.set('export_folder', '')
db.close()
finish()
