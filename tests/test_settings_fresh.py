"""
Настройки на новой точке: «Сохранить» срабатывает сразу.

На свежей базе часы записи и даты сезона брались из базы с пустой
строкой вместо значения по умолчанию — поля открывались пустыми, и
«Сохранить» отказывал «Время «» непонятно». Вместе с ним не сохранялся
ключ звонков, и вход в дашборд по звонку не включался (30.10.2026).

Решение владельца 30.10.2026 после этого:
  · ошибка в одном поле не останавливает сохранение остальных — поле
    подсвечено, сказано, что и где не сохранилось;
  · удачный пробный звонок сохраняет ключ сам, без «Сохранить».
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

print('\n=== Ошибка в одном поле ===')
# Встроенные настройки — как в программе: после сохранения не закрываются
host = tk.Frame(root)
host.pack()
dialog = settings_module.SettingsDialog(root, db, host=host)
root.update()
key = dialog.text_fields['call_token']
shown.clear()
dialog.time_fields['booking_opens_at'].delete(0, 'end')
dialog.numeric_fields['booking_posts'].delete(0, 'end')
dialog.numeric_fields['booking_posts'].insert(0, '5')
key.delete(0, 'end')
key.insert(0, 'SECOND-KEY')
dialog.save()
settings = SettingsService(SessionLocal())
check('ключ всё равно сохранён', settings.get('call_token') == 'SECOND-KEY')
check('и другое правильное поле', settings.get('booking_posts') == '5')
check('неправильное осталось как было', settings.get('booking_opens_at') == '07:00')
warning = [m for kind, title, m in shown if kind == 'showwarning']
check('сказано, что и где не сохранилось', warning and 'Приём машин → Записывать с' in warning[0]
      and 'остальное сохранено' in warning[0], str(shown))
check('поле подсвечено', str(dialog.time_fields['booking_opens_at'].cget('style')) == 'Bad.TEntry')
dialog.time_fields['booking_opens_at'].insert(0, '08:00')
shown.clear()
dialog.save()
check('поправили — сохранилось и подсветка снята',
      SettingsService(SessionLocal()).get('booking_opens_at') == '08:00'
      and str(dialog.time_fields['booking_opens_at'].cget('style')) == 'TEntry'
      and shown and shown[0][0] == 'showinfo', str(shown))

print('\n=== Пробный звонок сохраняет ключ ===')
import ui.call_key_check as call_screen
from services import flashcall
answers = [('c1', '+74950000001', 60), (flashcall.CONFIRMED, '+79099018931')]
flashcall.get_phone = lambda token, phone: answers.pop(0)
flashcall.status = lambda token, check_id: answers.pop(0)
call_screen.POLL_MS = 50
dialog.text_fields['call_token'].delete(0, 'end')
dialog.text_fields['call_token'].insert(0, 'CHECKED-KEY')
SettingsService(SessionLocal()).set('call_provider', 'off')
check_window = dialog.check_call_key()
check_window.start()
for _ in range(80):
    root.update()
    root.after(20)
    if 'Ключ сохранён' in check_window.state.cget('text'):
        break
check('в окне — «ключ сохранён»', 'Ключ сохранён' in check_window.state.cget('text'),
      check_window.state.cget('text'))
settings = SettingsService(SessionLocal())
check('ключ записан без «Сохранить»', settings.get('call_token') == 'CHECKED-KEY'
      and settings.get('call_provider') == 'flashcall')
check_window.close()

print('\n=== Telegram: проверка без получателей ===')
# Получатели появляются после «Старт» по ссылке на бота — значит, токен
# проверяется и сохраняется раньше, чем есть кому писать
from services.telegram_service import TelegramService
calls = []


def fake_call(self, method, fields, files=None):
    calls.append(method)
    return {'username': 'rif_test_bot'}


TelegramService._call = fake_call
dialog.token_entry.delete(0, 'end')
dialog.token_entry.insert(0, '123:BOT-TOKEN')
# Без mainloop окно не примет ответ из чужого потока — проверка идёт здесь же
import threading


class InPlace:
    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


real_thread, threading.Thread = threading.Thread, InPlace
dialog.test_telegram()
threading.Thread = real_thread
for _ in range(100):
    root.update()
    root.after(20)
    if 'отвечает' in dialog.telegram_status.cget('text'):
        break
check('бот проверен без получателей', 'rif_test_bot отвечает' in dialog.telegram_status.cget('text')
      and calls == ['getMe'], dialog.telegram_status.cget('text'))
check('токен сохранён сразу', TelegramService(SessionLocal()).get_token() == '123:BOT-TOKEN')

root.destroy()
finish()
