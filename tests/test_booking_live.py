"""
Запись должна быть видна сразу с обеих сторон.

Записи живут на сервере в одном экземпляре: и цех, и кабинет читают и
пишут туда же. Поэтому занять одно время дважды нельзя — сервер
откажет тому, кто сохранил вторым.

Опасность не в данных, а в разговоре. Приёмщик смотрит на ленту,
открытую десять минут назад, видит свободное окно, зовёт клиента на
это время — и получает отказ при сохранении. Клиенту уже обещано.

Поэтому проверяем:

  · лента перечитывает день сама, пока открыта;
  · тихое обновление не затирает несохранённый выбор постов —
    приёмщик мог покрутить счётчик и не нажать «Применить»;
  · тихое обновление не трогает своих же данных без сервера:
    локальная база не устаревает, и дёргать её незачем;
  · отказ сервера обновляет ленту позади формы, чтобы было видно,
    кто занял время;
  · число постов уходит на сервер сразу, а не ждёт обмена.
"""
import _setup
from _setup import use_temp_db, check, finish, silence_dialogs

use_temp_db('booking_live')

import tkinter as tk
from datetime import timedelta

from config import init_db, SessionLocal
from services.settings_service import SettingsService

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

root = tk.Tk()
root.geometry('1200x800+0+0')

import styles

styles.apply_modern_styles(root)

import ui.appointments_tab as tab_module
import ui.appointment_dialogs as dialogs_module

shown = silence_dialogs(tab_module, dialogs_module)

tab = tab_module.AppointmentsTab(root, db)
tab.frame.pack(fill='both', expand=True)
root.update()

print('=== Лента завела себе таймер ===')
check('таймер есть', hasattr(tab, 'schedule_refresh'))
check('обновление есть', hasattr(tab, '_auto_refresh'))
check('срок разумный', 5 <= tab_module.REFRESH_SECONDS <= 60,
      str(tab_module.REFRESH_SECONDS))

print()
print('=== Тихое обновление не затирает выбор постов ===')
tab.choose_posts(3)
check('выбрали три', tab.selected_posts == 3)

tab.load_day(silent=True)
check('выбор остался после тихого обновления', tab.selected_posts == 3,
      str(tab.selected_posts))

tab.load_day()
check('а по действию человека подтянулся с дня',
      tab.selected_posts == tab.day_state.get('posts', 1),
      f"{tab.selected_posts} против {tab.day_state.get('posts')}")

print()
print('=== Без сервера лента себя не дёргает ===')
calls = []
original = tab.load_day
tab.load_day = lambda silent=False: calls.append(silent)

check('работаем на своей базе', tab.booking.is_remote is False)
tab._auto_refresh()
check('запроса не было', calls == [], str(calls))

print()
print('=== С сервером — перечитывает ===')


class Remote:
    is_remote = True


tab.booking = Remote()
tab._auto_refresh()
check('перечитал тихо', calls == [True], str(calls))

print()
print('=== Поверх открытого окна не перерисовывает ===')
calls.clear()
blocker = tk.Toplevel(root)
blocker.geometry('200x100+100+100')
root.update()
blocker.grab_set()

tab._auto_refresh()
check('пока открыта форма — не трогает', calls == [], str(calls))

blocker.grab_release()
blocker.destroy()
root.update()
tab.load_day = original

print()
print('=== Отказ сервера обновляет ленту позади формы ===')
import inspect

source = inspect.getsource(dialogs_module.AppointmentDialog.save)
body = source[source.index('except Exception'):]
check('на отказе звоним в ленту', 'self.on_saved()' in body,
      body[:200])

print()
print('=== Число постов уходит на сервер сразу ===')
import services.booking_api as booking_api

posts_source = inspect.getsource(booking_api.BookingApi.set_posts_for_days)
check('посты пишутся запросом к серверу',
      "'/sync/posts'" in posts_source or '"/sync/posts"' in posts_source,
      posts_source)

import services.shift_service as shift_service

shift_source = inspect.getsource(shift_service)
check('смена зовёт срочный обмен при смене постов',
      'изменилось число постов' in shift_source)

root.destroy()
db.close()
finish()
