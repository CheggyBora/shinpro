"""
Тестовый запуск на копии рабочей базы: наружу — ничего.

В копии базы включён обмен с настоящим ключом точки и настоящий бот.
Пробный наряд не должен уйти ни на сервер (в кабинет, клиенту), ни в
Telegram. Проверяем, что метка рядом с программой всё это глушит.
"""
import os

import _setup
from _setup import use_temp_db, check, finish

use_temp_db('offline_mode')

from config import init_db, SessionLocal, offline_test_mode
from services.sync_service import SyncService, SyncError
from services.telegram_service import TelegramService, TelegramError

init_db()
db = SessionLocal()
sync = SyncService(db)
sync.save_settings('https://example.invalid', 'real-key', True)
TelegramService(db).save_token('123:real')

print('=== Обычный запуск ===')
os.environ.pop('TIRE_OFFLINE', None)
check('метки нет', offline_test_mode() is False)
check('обмен включён', sync.is_enabled() is True)

print()
print('=== С меткой — наружу ничего ===')
os.environ['TIRE_OFFLINE'] = '1'
check('тестовый режим', offline_test_mode() is True)
check('обмен выключен', sync.is_enabled() is False)
try:
    sync._call('GET', '/sync/live/qr')
    check('на сервер не уходит', False)
except SyncError as e:
    check('на сервер не уходит', 'Тестовый режим' in str(e), str(e))
try:
    TelegramService(db)._call('sendMessage', {'chat_id': '1', 'text': 'x'})
    check('в Telegram не уходит', False)
except TelegramError as e:
    check('в Telegram не уходит', 'Тестовый режим' in str(e), str(e))
check('настройки связи в копии не тронуты',
      sync.get_url() == 'https://example.invalid' and sync.get_key() == 'real-key')
os.environ.pop('TIRE_OFFLINE', None)

db.close()
finish()
