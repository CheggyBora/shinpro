"""
Срок хранения комплекта.

Раньше комплект лежал бессрочно: приняли, взяли деньги, и всё. При этом
кабинет обещал владельцу предупредить, когда срок кончится, — обещание,
которое нечем было выполнить.

Главная тонкость здесь в том, что пустой срок значит две разных вещи:
«срока ещё не было в программе» и «договорились хранить бессрочно».
Отличить их по строке нельзя, поэтому разом сроки проставляются ровно
один раз, при первом запуске новой версии. Если это сломать, у всех,
кто хранит без срока, однажды появится выдуманная дата, и людям уйдут
напоминания о том, о чём никто не договаривался.
"""
import sys
from datetime import timedelta

import _setup  # noqa: F401
from _setup import use_temp_db, check, finish

use_temp_db('storage_term')

from config import init_db, SessionLocal
from services.settings_service import SettingsService
from services.tire_storage_service import TireStorageService
from utils import get_moscow_time

init_db()
db = SessionLocal()
service = TireStorageService(db)
settings = SettingsService(db)
settings.ensure_defaults()


def accept(plate='А123ВВ777'):
    return service.accept_storage(
        car_number=plate, driver_license='7777 123456',
        storage_type='шины с дисками', diameter='R17',
        brand='Nokian', damage='', wear='5 мм')


def months(value):
    """Поменять срок в настройках. Сервис читает её при каждом расчёте."""
    global service
    settings.set('storage_months', str(value))
    service = TireStorageService(db)


print('=== По умолчанию срок — полгода ===')
check('настройка на месте', settings.get_int('storage_months') == 6,
      str(settings.get_int('storage_months')))

one = accept()
check('срок проставлен', one.expires_at is not None)

left = (one.expires_at - get_moscow_time()).days
check('это примерно полгода', 175 <= left <= 185, f'{left} дней')

print('\n=== Срок считается от настройки, а не зашит ===')
months(3)
three = accept('В222АА178')
left = (three.expires_at - get_moscow_time()).days
check('три месяца', 85 <= left <= 95, f'{left} дней')

print('\n=== Ноль месяцев — хранение бессрочное ===')
months(0)
forever = accept('С333СС777')
check('срока нет', forever.expires_at is None, str(forever.expires_at))
months(6)

print('\n=== Срок можно переставить руками ===')
agreed = get_moscow_time() + timedelta(days=45)
service.set_deadline(three.id, agreed)

db.expire_all()
three = service.get_storage_by_id(three.id)
check('стоит то, о чём договорились',
      abs((three.expires_at - agreed).total_seconds()) < 2,
      str(three.expires_at))

print('\n=== Истекающие видно списком ===')
soon = accept('Е444ЕЕ777')
service.set_deadline(soon.id, get_moscow_time() + timedelta(days=3))

overdue = accept('К555КК777')
service.set_deadline(overdue.id, get_moscow_time() - timedelta(days=10))

ids = [row.id for row in service.expiring(days=7)]
check('нашлись оба', {soon.id, overdue.id} <= set(ids), str(ids))
check('дальние не попали', three.id not in ids and one.id not in ids, str(ids))
check('просроченный первым', ids[0] == overdue.id, str(ids))

print('\n=== Выданный комплект из списка уходит ===')
service.release_storage(soon.id)
ids = [row.id for row in service.expiring(days=7)]
check('остался только просроченный', ids == [overdue.id], str(ids))

print('\n=== Бессрочное хранение дозаполнение не трогает ===')
# Отметку ставит init_db при первом запуске — значит проход по складу
# уже был, и пустой срок теперь означает только договорённость
check('отметка стоит с первого запуска',
      settings.get_raw(TireStorageService.FILLED_KEY) == '1',
      str(settings.get_raw(TireStorageService.FILLED_KEY)))
check('второй раз не ходим', service.fill_missing_deadlines() == 0)

db.expire_all()
forever = service.get_storage_by_id(forever.id)
check('срок у бессрочного не появился', forever.expires_at is None,
      str(forever.expires_at))

print('\n=== Обновление старой версии: сроки проставляются разом ===')
# Так выглядит склад программы, которая про сроки ещё не знала
legacy = accept('М666ММ777')
legacy.expires_at = None
legacy.accepted_date = get_moscow_time() - timedelta(days=100)

older = accept('Н777НН777')
older.expires_at = None
older.accepted_date = get_moscow_time() - timedelta(days=20)
db.commit()

settings.set(TireStorageService.FILLED_KEY, '0')
filled = service.fill_missing_deadlines()
check('проставили всем пустым', filled == 3, str(filled))

db.expire_all()
legacy = service.get_storage_by_id(legacy.id)
check('срок от дня приёмки, а не от сегодня',
      60 <= (legacy.expires_at - get_moscow_time()).days <= 90,
      f'{(legacy.expires_at - get_moscow_time()).days} дней')

check('повторно ничего не трогаем', service.fill_missing_deadlines() == 0)

print('\n=== Руками выставленный срок дозаполнение не портит ===')
db.expire_all()
three = service.get_storage_by_id(three.id)
check('остался договорный',
      abs((three.expires_at - agreed).total_seconds()) < 2,
      str(three.expires_at))

print('\n=== Обмен отдаёт срок серверу ===')
from services.sync_service import SyncService

payload = SyncService(db)._collect_storage()
sent = {row['license_plate']: row['expires_at'] for row in payload}

check('у лежащих срок не пустой',
      sent.get('А123ВВ777') is not None, str(sent.get('А123ВВ777')))
check('выданный не уехал', 'Е444ЕЕ777' not in sent, str(sorted(sent)))

print('\n=== Срок ноль — и дозаполнять нечего ===')
months(0)
settings.set(TireStorageService.FILLED_KEY, '0')
blank = accept('Р888РР777')
check('новый без срока', blank.expires_at is None, str(blank.expires_at))
check('проход по складу ничего не делает',
      service.fill_missing_deadlines() == 0)

db.close()
finish()
