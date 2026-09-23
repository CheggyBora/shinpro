"""
Программа запускается, когда смена осталась открытой.

Раньше это был самый болезненный отказ: если компьютер перезагрузили
посреди рабочего дня, окно вообще не открывалось — при построении
вкладки сотрудников падало вычитание времени с разными часовыми поясами.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('app_starts')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Shift

init_db()
initialize_data()

db = SessionLocal()
db.add(Shift(status='open'))
db.commit()
db.close()

import tkinter as tk
from ui import MainWindow

root = tk.Tk()
root.withdraw()  # окно на экране не показываем

try:
    app = MainWindow(root)
    root.update()
    check('окно построено при открытой смене', True)

    status = app.employees_tab.shift_status_label.cget('text')
    check('статус смены показан', 'Смена открыта' in status, status)
    check('длительность смены посчитана без сбоя', 'работает' in status, status)
except Exception as e:
    check('окно построено при открытой смене', False, f'{type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()
finally:
    root.destroy()

finish()
