"""
Смена закрывается каждое утро в 9:05 (правило владельца 27.10.2026).

Когда бы её ни открыли — в ближайшие 9:05 после открытия. Открыли меньше
чем за час до них — до следующего утра. Без открытой смены наряд не
меняется: нажатия мастера с телефона ждут, пока смену откроют.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('shift_autoclose')

from datetime import datetime

from config import init_db, SessionLocal
from models import Settings, Shift
from services.settings_service import SettingsService
from services.shift_report_service import ShiftReportService

init_db()
db = SessionLocal()

print('=== Старое 09:00 становится 09:05 один раз ===')
db.add(Settings(key='shift_autoclose_time', value='09:00'))
db.commit()
SettingsService(db).ensure_defaults()
check('09:00 по умолчанию переведено в 09:05',
      SettingsService(db).get('shift_autoclose_time') == '09:05')
SettingsService(db).set('shift_autoclose_time', '09:00')
SettingsService(db).ensure_defaults()
check('своё время владельца второй раз не трогаем',
      SettingsService(db).get('shift_autoclose_time') == '09:00')
SettingsService(db).set('shift_autoclose_time', '09:05')

report = ShiftReportService(db)
check('время закрытия — 9:05', report.get_autoclose_time() == (9, 5))


def deadline_for(opened, now):
    db.query(Shift).delete()
    db.add(Shift(start_time=opened, status='open'))
    db.commit()
    return report.find_overdue_shift(now=now) is not None


print('\n=== Ближайшие 9:05 после открытия ===')
check('открыли днём 1-го — в 9:04 2-го ещё работает',
      not deadline_for(datetime(2026, 10, 1, 10, 0), datetime(2026, 10, 2, 9, 4)))
check('открыли днём 1-го — в 9:05 2-го закрываем',
      deadline_for(datetime(2026, 10, 1, 10, 0), datetime(2026, 10, 2, 9, 5)))
check('открыли ночью в 2:00 — закрываем в 9:05 того же утра',
      deadline_for(datetime(2026, 10, 2, 2, 0), datetime(2026, 10, 2, 9, 5)))
check('открыли в 9:02 — через три минуты не закрываем',
      not deadline_for(datetime(2026, 10, 2, 9, 2), datetime(2026, 10, 2, 9, 6)))
check('открыли в 9:02 — закрываем следующим утром',
      deadline_for(datetime(2026, 10, 2, 9, 2), datetime(2026, 10, 3, 9, 5)))
check('открыли в 8:30 — закрываем следующим утром, не через 35 минут',
      not deadline_for(datetime(2026, 10, 2, 8, 30), datetime(2026, 10, 2, 9, 10)))

print('\n=== Без открытой смены нажатия с телефона ждут ===')
db.query(Shift).delete()
db.commit()
from services.sync_service import SyncService
called = []
sync = SyncService(db)
sync._call = lambda *args, **kwargs: called.append(args) or {}
answer = sync.master_exchange()
check('смены нет — на сервер за нажатиями не ходим, наряды не трогаем',
      answer['changed'] is False and called == [], str(called))

db.close()
finish()
