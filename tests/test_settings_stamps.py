"""
Время правки настроек: без него спор с дашбордом не решить.

Посты под запись, часы и выключатель приёма записи меняют и здесь, в
цеху, и владелец из дашборда. Разошлись — прав тот, кто поставил
позже. Значит, цех обязан помнить, когда он менял настройку, и честно
это отдавать.

Главная ловушка — окно настроек сохраняет все поля сразу. Нажал
«Сохранить», поменяв одно число, — записались все десять. Если при
этом двигать время правки у всех, цех выигрывал бы любой спор просто
тем, что кто-то открыл настройки, и правка владельца молча исчезала
бы.
"""
import time

import _setup
from _setup import use_temp_db, check, finish

use_temp_db('settings_stamps')

_setup.silence_dialogs()

from datetime import timedelta

from config import init_db, SessionLocal
from services.settings_service import SettingsService
from services.sync_service import SyncService
from utils import get_moscow_time

init_db()
db = SessionLocal()
settings = SettingsService(db)
settings.ensure_defaults()

print('=== У настроек с самого начала есть время правки ===')
check('время есть', settings.changed_at('booking_posts') is not None,
      str(settings.changed_at('booking_posts')))

print()
print('=== Правка двигает время ===')
was = settings.changed_at('booking_posts')
time.sleep(0.01)
settings.set('booking_posts', '3')

check('значение записалось', settings.get('booking_posts') == '3',
      str(settings.get('booking_posts')))
check('время сдвинулось', settings.changed_at('booking_posts') > was,
      f"{settings.changed_at('booking_posts')} против {was}")

print()
print('=== Запись того же значения время не двигает ===')
# Иначе любое сохранение настроек отменяло бы правку из дашборда,
# даже если человек ничего не менял
was = settings.changed_at('booking_posts')
time.sleep(0.01)
settings.set('booking_posts', '3')

check('время осталось прежним', settings.changed_at('booking_posts') == was,
      f"{settings.changed_at('booking_posts')} против {was}")

print()
print('=== Но пачку правок такой вызов всё равно закрывает ===')
# Окно настроек пишет всё с commit=False и закрывает последним вызовом.
# Если последним окажется неизменённое значение, остальное обязано
# сохраниться, а не остаться висеть
settings.set('booking_opens_at', '06:30', commit=False)
settings.set('booking_posts', '3')      # то же самое, но с commit

db.expire_all()
check('предыдущая правка сохранилась',
      settings.get('booking_opens_at') == '06:30',
      str(settings.get('booking_opens_at')))

print()
print('=== Цех отдаёт метки в обмен ===')
sync = SyncService(db)
stamps = sync._settings_changed_at()

check('метки есть по всем спорным настройкам',
      set(stamps) == set(sync.SHARED_SETTINGS), str(sorted(stamps)))
check('о бесспорных не говорим',
      'booking_slot_step' not in stamps, str(sorted(stamps)))

payload = sync.collect_push(None)
check('метки уехали вместе с настройками',
      payload['settings_changed_at'] == stamps, str(payload.get('settings_changed_at')))
check('посты под запись тоже уехали',
      payload['settings'].get('booking_posts') == '3',
      str(payload['settings'].get('booking_posts')))

print()
print('=== Правка из дашборда принимается со своим временем ===')
later = (get_moscow_time() + timedelta(minutes=5)).isoformat()
taken = sync._adopt_settings([
    {'key': 'booking_posts', 'value': '1', 'changed_at': later},
])

check('приняли одну', taken == 1, str(taken))
check('значение владельца', settings.get('booking_posts') == '1',
      str(settings.get('booking_posts')))
check('и время его же, а не «сейчас»',
      settings.changed_at('booking_posts') > get_moscow_time(),
      str(settings.changed_at('booking_posts')))

print()
print('=== Чужого сервер цеху не навяжет ===')
# Принимаем только то, что сами считаем спорным. Иначе сервер мог бы
# переписать цеху проценты мастерам или реквизиты
before = settings.get('order_base_minutes')
check('есть что защищать', before is not None, str(before))

sync._adopt_settings([
    {'key': 'order_base_minutes', 'value': '999', 'changed_at': later},
])
check('время наряда не тронуто',
      settings.get('order_base_minutes') == before,
      str(settings.get('order_base_minutes')))

db.close()
finish()
