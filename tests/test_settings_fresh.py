"""
Настройки на новой точке: «Сохранить» срабатывает сразу.

На свежей базе часы записи и даты сезона брались из базы с пустой
строкой вместо значения по умолчанию — поля открывались пустыми, и
«Сохранить» отказывал «Время «» непонятно». Вместе с ним не сохранялся
ключ звонков, и вход в дашборд по звонку не включался (30.10.2026).
"""
import _setup
from _setup import use_temp_db, check, finish, silence_dialogs

use_temp_db('settings_fresh')
shown = silence_dialogs()

import tkinter as tk
from config import init_db, SessionLocal
import styles
import ui.settings_dialog as settings_module
from services.settings_service import SettingsService
from services.sync_service import SyncService

init_db()
db = SessionLocal()
root = tk.Tk()
root.geometry('+-3000+0')
styles.apply_modern_styles(root)

dialog = settings_module.SettingsDialog(root, db)
root.update()
check('часы записи — по умолчанию', dialog.time_fields['booking_opens_at'].get() == '07:00'
      and dialog.time_fields['booking_closes_at'].get() == '24:00')
check('даты сезона — по умолчанию', dialog.season_fields['season_autumn_at'].get() == '01.10')

key = dialog.text_fields['call_token']
key.delete(0, 'end')
key.insert(0, 'KEY-FROM-FLASHCALL')
dialog.save()
check('сохранилось без ошибок', not any(kind == 'showerror' for kind, *_ in shown), str(shown))

settings = SettingsService(SessionLocal())
check('ключ звонков записан, звонок включён', settings.get('call_token') == 'KEY-FROM-FLASHCALL'
      and settings.get('call_provider') == 'flashcall')
sent = SyncService(SessionLocal()).collect_push()['settings']
check('ключ уходит на сервер', sent['call_provider'] == 'flashcall'
      and sent['call_token'] == 'KEY-FROM-FLASHCALL')

root.destroy()
finish()
