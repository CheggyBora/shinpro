"""
Наряды не пропадают при отключении электричества (жалоба 27.10.2026).

База пишет каждое изменение на диск сразу (synchronous=FULL): с NORMAL
последние правки при обрыве питания оставались в памяти Windows и терялись.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('durability')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, engine, IS_SQLITE

init_db()
with engine.connect() as connection:
    journal = connection.exec_driver_sql('PRAGMA journal_mode').scalar()
    sync = connection.exec_driver_sql('PRAGMA synchronous').scalar()
check('база SQLite', IS_SQLITE)
check('журнал упреждающей записи (WAL)', str(journal).lower() == 'wal', str(journal))
check('каждая запись — сразу на диск (FULL)', int(sync) == 2, str(sync))

from ui.order_screen.widget import OrderWidget
check('в наряде можно заказать комплект со склада', hasattr(OrderWidget, 'storage_order'))
finish()
