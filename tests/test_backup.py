"""Резервное копирование базы и режим WAL."""
import _setup
from _setup import check, finish

import os
import shutil
import sqlite3
import tempfile

# Отдельная папка: рядом с базой создаётся backups/, и остатки прошлого
# прогона не должны влиять на подсчёт копий
WORK_DIR = os.path.join(tempfile.gettempdir(), 'tire_shop_test_backup')
shutil.rmtree(WORK_DIR, ignore_errors=True)
os.makedirs(WORK_DIR)

DB_PATH = os.path.join(WORK_DIR, 'tire_shop.db')
os.environ['DATABASE_URL'] = f'sqlite:///{DB_PATH}'

from config import init_db, SessionLocal, engine
from models import Client
from services.backup_service import (create_backup, list_backups, cleanup_old,
                                     get_backup_dir, restore_from_backup)

init_db()

db = SessionLocal()
db.add(Client(name='Андрей', phone='79099018931'))
db.commit()
db.close()

backup_dir = get_backup_dir(DB_PATH)

print('=== Режим WAL включён ===')
with engine.connect() as conn:
    from sqlalchemy import text
    mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    check('журнал упреждающей записи включён', str(mode).lower() == 'wal', str(mode))

print('\n=== Копия снимается ===')
path = create_backup(DB_PATH, force=True)
check('копия создана', path is not None and os.path.exists(path), str(path))
check('копия не пустая', os.path.getsize(path) > 0)

print('\n=== В копии есть данные ===')
conn = sqlite3.connect(path)
names = [r[0] for r in conn.execute("SELECT name FROM clients")]
conn.close()
check('данные попали в копию', names == ['Андрей'], str(names))

print('\n=== Копии не плодятся при перезапусках ===')
skipped = create_backup(DB_PATH)  # без force, сразу после предыдущей
check('повторная копия не создаётся', skipped is None, str(skipped))
check('копия по-прежнему одна', len(list_backups(backup_dir)) == 1)

print('\n=== Старые копии удаляются ===')
import time
for i in range(5):
    time.sleep(1.05)  # имя копии содержит секунды
    create_backup(DB_PATH, force=True)
total = len(list_backups(backup_dir))
check('копий накопилось 6', total == 6, str(total))

removed = cleanup_old(backup_dir, keep=3)
check('лишние копии удалены', removed == 3, f'удалено {removed}')
check('осталось ровно 3', len(list_backups(backup_dir)) == 3)

print('\n=== Восстановление из копии ===')
newest = list_backups(backup_dir)[0]
# Портим базу
with open(DB_PATH, 'wb') as f:
    f.write('это больше не база данных'.encode('utf-8'))

restore_from_backup(newest, DB_PATH)
conn = sqlite3.connect(DB_PATH)
names = [r[0] for r in conn.execute("SELECT name FROM clients")]
conn.close()
check('база восстановлена из копии', names == ['Андрей'], str(names))

damaged = [n for n in os.listdir(os.path.dirname(DB_PATH)) if '.damaged_' in n]
check('повреждённый файл сохранён для разбора', len(damaged) == 1, str(damaged))

finish()
