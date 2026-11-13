"""
Копия базы на сервере — сторона программы (решение 13.11.2026).

  · копия уходит сжатой, не чаще раза в три часа, при закрытии смены —
    всегда;
  · «Восстановить с сервера»: база заменяется копией, текущая остаётся
    рядом (damaged), ключ обмена — тот, что ввели на новом компьютере.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('cloud_backup')

import gzip
import os

from config import init_db, SessionLocal, get_db_file_path
from models import WorkOrder
from services import OrderService, cloud_backup
from services.sync_service import SyncService

init_db()
db = SessionLocal()
SyncService(db).save_settings('https://srv.example.ru', 'old-key', True)
order = OrderService(db).create_order('А123ВВ777', 'R16', 'car', create_client=False)
db.close()
path = get_db_file_path()

stored = {}


def fake_request(sync, method, url_path, data=None):
    if method == 'POST':
        stored['copy'] = data
        return b'{"ok": true}', {}
    if url_path == '/sync/backup':
        return b'{"copies": [{"name": "x", "taken": "13.11.2026 10:00", "size": 1}]}', {}
    return stored['copy'], {}


cloud_backup._request = fake_request

print('=== Отправка ===')
check('первая — уходит', cloud_backup.upload(path) is True)
check('сжата и это база SQLite', gzip.decompress(stored['copy'])[:15] == b'SQLite format 3')
check('через минуту без закрытия смены — рано', cloud_backup.upload(path) is False)
check('при закрытии смены — всегда', cloud_backup.upload(path, force=True) is True)

print('\n=== Сломался компьютер: новая база, код подключения, восстановить ===')
db = SessionLocal()
db.query(WorkOrder).delete()
db.commit()
SyncService(db).save_settings('https://srv.example.ru', 'new-key', True)
check('наряда нет — «новый компьютер»', db.query(WorkOrder).count() == 0)
db.close()
check('копия на сервере видна', cloud_backup.latest_info()['taken'] == '13.11.2026 10:00')
cloud_backup.restore(path)
db = SessionLocal()
check('наряд вернулся', db.query(WorkOrder).count() == 1)
check('ключ обмена — новый, введённый сейчас', SyncService(db).get_key() == 'new-key')
check('прежняя база — рядом, damaged',
      any(name.startswith(os.path.basename(path) + '.damaged_') for name in os.listdir(os.path.dirname(path))))
db.close()

stored['copy'] = gzip.compress(b'not a database')
try:
    cloud_backup.restore(path)
    check('чужой файл — отказ', False)
except Exception as e:
    check('чужой файл — отказ', True, str(e)[:80])

finish()
