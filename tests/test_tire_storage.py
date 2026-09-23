"""
Хранение шин работает в общей сессии базы.

Раньше сервис открывал свою собственную сессию, и запись, созданная им,
не была видна остальной программе — её приходилось перезапрашивать вручную.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('tire_storage')

from config import init_db, SessionLocal
from models import TireStorage, Settings, AuditLog
from services.tire_storage_service import TireStorageService
from services import AuditService

init_db()
db = SessionLocal()
service = TireStorageService(db)

print('=== Цена берётся из настроек ===')
check('цена по умолчанию для R16', service.calculate_price('R16') == 5000.0,
      str(service.calculate_price('R16')))
db.add(Settings(key='storage_price_r16', value='5500'))
db.commit()
check('цена из настроек перекрывает умолчание', service.calculate_price('R16') == 5500.0,
      str(service.calculate_price('R16')))
check('неизвестный размер даёт 0', service.calculate_price('R99') == 0.0)
check('мусор вместо размера не роняет расчёт', service.calculate_price('абв') == 0.0)

print('\n=== Приёмка видна в общей сессии сразу ===')
storage = service.accept_storage('a123bb777', 'AB123456', 'Шины с дисками', 'R16',
                                 'Nokian', '', 'малый', '', 'литые')
check('запись создана', storage is not None and storage.id is not None)
check('номер нормализован', storage.car_number == 'А123ВВ777', storage.car_number)
check('цена проставлена из настроек', storage.price == 5500.0, str(storage.price))

# Раньше здесь требовался повторный запрос: сервис писал в другую сессию
same = db.query(TireStorage).filter(TireStorage.id == storage.id).first()
check('запись сразу видна основной сессии', same is storage,
      'объект тот же' if same is storage else 'потребовался бы перезапрос')

print('\n=== Поиск по номеру в любом написании ===')
check('поиск латиницей', len(service.search_by_car_number('A123BB777')) == 1)
check('поиск нижним регистром', len(service.search_by_car_number('а123вв777')) == 1)
check('поиск с пробелами', len(service.search_by_car_number(' А123 ВВ 777 ')) == 1)
check('чужой номер не находится', len(service.search_by_car_number('Х999ХХ99')) == 0)

print('\n=== Выдача комплекта ===')
released = service.release_storage(storage.id)
check('статус стал "выдан"', released.status == 'released')
check('дата выдачи проставлена', released.released_date is not None)

entries = [e for e in AuditService(db).get_recent() if e.action == AuditService.STORAGE_RELEASE]
check('выдача записана в журнал', len(entries) == 1)
check('в записи есть номер машины', 'А123ВВ777' in entries[0].description,
      entries[0].description)

print('\n=== Повторная выдача отклоняется ===')
try:
    service.release_storage(storage.id)
    check('повторная выдача отклонена', False, 'выдача прошла второй раз')
except ValueError as e:
    check('повторная выдача отклонена', True, str(e))

print('\n=== Выдача несуществующего комплекта ===')
check('несуществующий комплект даёт None', service.release_storage(9999) is None)

db.close()
finish()
