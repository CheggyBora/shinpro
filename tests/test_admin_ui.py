"""Экран администратора: вход по PIN, журнал действий, смена кода."""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('admin_ui')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Shift
from services import AuditService

init_db()
initialize_data()

db = SessionLocal()
db.add(Shift(status='open'))
AuditService(db).log(AuditService.ORDER_DELETE, 'Наряд №42 (А123ВВ777) на 1500 руб.')
AuditService(db).log(AuditService.PRICE_CHANGE, '«Шиномонтаж» — R16: 400 -> 450')
db.commit()
db.close()

import tkinter as tk
from tkinter import ttk
import ui.price_list_tab

# Всплывающие окна в тесте заменяем печатью, иначе процесс зависнет
popups = _setup.silence_dialogs(ui.price_list_tab)

from ui import MainWindow


def find_dialogs(widget, acc=None):
    """Выпадающие списки Combobox — тоже Toplevel, отсекаем их по overrideredirect."""
    if acc is None:
        acc = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Toplevel) and not child.wm_overrideredirect():
            acc.append(child)
        find_dialogs(child, acc)
    return acc


def collect(widget, kind, acc=None):
    if acc is None:
        acc = []
    if isinstance(widget, kind):
        acc.append(widget)
    for child in widget.winfo_children():
        collect(child, kind, acc)
    return acc


def texts(widget, acc=None):
    if acc is None:
        acc = []
    try:
        value = widget.cget('text')
        if value:
            acc.append(str(value))
    except Exception:
        pass
    for child in widget.winfo_children():
        texts(child, acc)
    return acc


root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
price_tab = app.price_list_tab

print('=== Вход в прайс-лист закрыт PIN-кодом ===')
check('без ввода PIN доступа нет', price_tab.is_authenticated is False)

price_tab.pin_entry.delete(0, tk.END)
price_tab.pin_entry.insert(0, '1111')
price_tab.check_pin()
root.update()
check('неверный PIN не пускает', price_tab.is_authenticated is False)

failed = [e for e in AuditService(price_tab.db).get_recent()
          if e.action == AuditService.PIN_FAILED]
check('неудачная попытка попала в журнал', len(failed) == 1, str(len(failed)))

print('\n=== Вход с кодом по умолчанию ===')
price_tab.pin_entry.delete(0, tk.END)
price_tab.pin_entry.insert(0, '0000')
price_tab.check_pin()
root.update()
check('верный PIN пускает', price_tab.is_authenticated is True)

screen_texts = texts(price_tab.content_frame)
check('предупреждение о коде по умолчанию показано',
      any('PIN-код по умолчанию' in t for t in screen_texts),
      [t for t in screen_texts if 'PIN' in t])
check('есть кнопка журнала', any('Журнал действий' in t for t in screen_texts))
check('есть кнопка смены PIN', any('Сменить PIN' in t for t in screen_texts))

print('\n=== Журнал действий открывается и показывает записи ===')
price_tab.show_audit_log()
root.update()
dialogs = find_dialogs(root)
check('окно журнала открылось', len(dialogs) == 1, f'окон: {len(dialogs)}')

if dialogs:
    trees = collect(dialogs[0], ttk.Treeview)
    rows = [trees[0].item(r)['values'] for r in trees[0].get_children()] if trees else []
    check('записи журнала выведены', len(rows) == 3, f'строк: {len(rows)}')
    blob = str(rows)
    check('видно удаление наряда', 'Удаление наряда' in blob, blob[:160])
    check('видно изменение цены', 'Изменение цены' in blob, blob[:160])
    check('видно подробности', 'А123ВВ777' in blob)
    dialogs[0].destroy()
    root.update()

print('\n=== Смена PIN-кода ===')
price_tab.show_change_pin()
root.update()
dialogs = find_dialogs(root)
check('окно смены PIN открылось', len(dialogs) == 1, f'окон: {len(dialogs)}')

if dialogs:
    entries = collect(dialogs[0], tk.Entry)
    check('три поля для ввода', len(entries) == 3, f'полей: {len(entries)}')
    check('код скрыт звёздочками',
          all(e.cget('show') for e in entries),
          str([e.cget('show') for e in entries]))
    dialogs[0].destroy()
    root.update()

print('\n=== Смена кода через сервис работает ===')
from services import AuthService
auth = AuthService(price_tab.db)
auth.change_pin('0000', '4321')
check('новый код принимается', auth.verify_pin('4321') is True)
check('предупреждение о коде по умолчанию снято', auth.is_default_pin() is False)

root.destroy()
finish()
