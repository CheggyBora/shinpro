"""
PIN хранится хешем, действия записываются в журнал.

Раньше PIN лежал в базе открытым текстом — любой, кто открыл файл базы,
видел его. А удаление наряда или правка цен не оставляли следов вовсе.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('auth_audit')

from config import init_db, SessionLocal
from models import Settings, Service, AuditLog
from services import AuthService, AuditService, OrderService, EmployeeService
from services.shift_service import ShiftService
from services.auth_service import PIN_HASH_KEY, LEGACY_PIN_KEY

init_db()
db = SessionLocal()

print('=== Старый открытый PIN превращается в хеш ===')
db.add(Settings(key=LEGACY_PIN_KEY, value='1234'))
db.commit()

auth = AuthService(db)
auth.ensure_pin_hashed()

legacy = db.query(Settings).filter(Settings.key == LEGACY_PIN_KEY).first()
stored = db.query(Settings).filter(Settings.key == PIN_HASH_KEY).first()

check('открытый PIN удалён из базы', legacy is None)
check('хеш сохранён', stored is not None and stored.value)
check('в базе нет самого кода', '1234' not in (stored.value or ''), stored.value[:40])
check('хеш выглядит как pbkdf2', stored.value.startswith('pbkdf2_sha256$'), stored.value[:30])

print('\n=== Проверка PIN ===')
check('верный PIN принимается', auth.verify_pin('1234') is True)
check('неверный PIN отклоняется', auth.verify_pin('0000') is False)
check('пустой PIN отклоняется', auth.verify_pin('') is False)
check('None отклоняется', auth.verify_pin(None) is False)

print('\n=== Смена PIN ===')
try:
    auth.change_pin('9999', '5678')
    check('смена с неверным текущим кодом отклонена', False, 'смена прошла')
except ValueError as e:
    check('смена с неверным текущим кодом отклонена', True, str(e))

for bad, why in [('12', 'короткий'), ('abcd', 'не цифры'), ('0000', 'код по умолчанию')]:
    try:
        auth.change_pin('1234', bad)
        check(f'слабый PIN отклонён ({why})', False, 'принят')
    except ValueError as e:
        check(f'слабый PIN отклонён ({why})', True, str(e))

auth.change_pin('1234', '5678')
check('новый PIN работает', auth.verify_pin('5678') is True)
check('старый PIN больше не подходит', auth.verify_pin('1234') is False)

print('\n=== Предупреждение о коде по умолчанию ===')
check('текущий PIN не является кодом по умолчанию', auth.is_default_pin() is False)

print('\n=== Соль у каждого своя ===')
from services.auth_service import _hash_pin
check('одинаковые PIN дают разные хеши', _hash_pin('1111') != _hash_pin('1111'))

print('\n=== Журнал действий ===')
ShiftService(db).open_shift()
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=400.0))
db.commit()
service = db.query(Service).first()

order_service = OrderService(db)
audit = AuditService(db)

before = db.query(AuditLog).count()

print('  -- изменение ставки ЗП')
emp.update_salary_percent(1, 45.0, '5678')
entries = audit.get_recent()
salary_entries = [e for e in entries if e.action == AuditService.SALARY_PERCENT_CHANGE]
check('изменение ставки записано', len(salary_entries) == 1)
check('видно, что именно поменялось',
      '40' in salary_entries[0].description and '45' in salary_entries[0].description,
      salary_entries[0].description)

print('  -- неверный PIN')
try:
    emp.update_salary_percent(1, 50.0, '0000')
except ValueError:
    pass
failed = [e for e in audit.get_recent() if e.action == AuditService.PIN_FAILED]
check('неудачная попытка входа записана', len(failed) == 1, str(len(failed)))
check('ставка НЕ изменилась после неверного PIN',
      db.query(type(emp.get_all_employees()[0])).first().salary_percent == 45.0)

print('  -- удаление черновика наряда')
draft = order_service.create_order('А123ВВ777', 'R16', 'car')
draft_id = draft.id
ok, _ = order_service.hard_delete_unpaid_order(draft_id)
hard = [e for e in audit.get_recent() if e.action == AuditService.ORDER_HARD_DELETE]
check('удаление черновика записано', ok and len(hard) == 1)
check('в записи есть номер наряда и машина',
      str(draft_id) in hard[0].description and 'А123ВВ777' in hard[0].description,
      hard[0].description)

print('  -- удаление оплаченного наряда')
from services import SalaryService
paid = order_service.create_order('К900ОР99', 'R16', 'car')
order_service.add_service_to_order(paid.id, service.id)
SalaryService(db).process_payment(paid.id, 'cash', order_service.calculate_total(paid.id))
ok, _ = order_service.delete_work_order(paid.id, reason='ошибка кассира')
soft = [e for e in audit.get_recent() if e.action == AuditService.ORDER_DELETE]
check('удаление оплаченного наряда записано', ok and len(soft) == 1)
check('причина удаления сохранена', 'ошибка кассира' in soft[0].description,
      soft[0].description)

print('\n=== Журнал читается по-человечески ===')
check('у действия есть понятное название',
      AuditService.title(AuditService.ORDER_DELETE) == 'Удаление наряда')
check('записей в журнале прибавилось', db.query(AuditLog).count() > before)
check('свежие записи идут первыми',
      audit.get_recent()[0].created_at >= audit.get_recent()[-1].created_at)

db.close()
finish()
