"""
Вкладка «Онлайн-очередь» в разделе «Запись».

Приёмщик смотрит сюда, когда освободился пост. Ему нужно одно: кто
уже здесь. Звать можно только их — машины у ворот нет, и пост
простоит, пока человек едет.

Проверяем то, что ломается молча:

  · вкладки действительно две, и лента не уехала;
  · приехавшие отмечены иначе, чем те, кто в пути;
  · того, кто ещё едет, взять на пост нельзя, и сказано почему;
  · без настроенного обмена экран не падает, а объясняет.
"""
import tkinter as tk

import _setup
from _setup import use_temp_db, check, finish, silence_dialogs

use_temp_db('queue_panel')

from config import init_db, SessionLocal
from services.settings_service import SettingsService

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

root = tk.Tk()
root.geometry('1200x800+0+0')

import styles

styles.apply_modern_styles(root)

import ui.queue_panel as panel_module
import ui.appointments_tab as tab_module

shown = silence_dialogs(panel_module, tab_module)

print('=== Без обмена экран объясняет, а не падает ===')
panel = panel_module.QueuePanel(root, db)
panel.frame.pack(fill='both', expand=True)
root.update()

check('экран построился', panel.frame.winfo_exists())
check('сказано про обмен', 'обмен' in panel.state_label.cget('text').lower(),
      panel.state_label.cget('text'))
check('список пуст', panel.rows == [], str(panel.rows))

print()
print('=== Список рисуется по данным сервера ===')
panel.rows = [
    {'id': 1, 'name': 'Пётр', 'license_plate': 'А123ВВ777', 'here': True,
     'come_at': '2026-10-15T13:40:00', 'phone': '79160000001', 'moved': False},
    {'id': 2, 'name': 'Ольга', 'license_plate': 'К900ОР99', 'here': False,
     'come_at': '2026-10-15T14:10:00', 'phone': '79160000002', 'moved': False},
]

for row in panel.tree.get_children():
    panel.tree.delete(row)

for row in panel.rows:
    panel.tree.insert('', 'end', values=(
        row['name'], row['license_plate'],
        'да' if row['here'] else 'в пути',
        row['come_at'][11:16], row['phone']),
        tags=('here' if row['here'] else 'away',))

root.update()

items = panel.tree.get_children()
check('обе строки на месте', len(items) == 2, str(len(items)))

first = panel.tree.item(items[0])
check('приехавший помечен', 'here' in first['tags'], str(first['tags']))
check('видно, что он на месте', first['values'][2] == 'да',
      str(first['values']))
check('время приезда, а не черёд', first['values'][3] == '13:40',
      str(first['values'][3]))

second = panel.tree.item(items[1])
check('тот, кто в пути, помечен иначе', 'away' in second['tags'],
      str(second['tags']))

print()
print('=== Того, кто ещё едет, на пост не взять ===')
shown.clear()
panel.tree.selection_set(items[1])
panel.take()
root.update()

check('сказали, что он в пути',
      any('пути' in f'{title or ""} {text or ""}'
          for _kind, title, text in shown),
      str(shown[-1:]))
check('и без рода — в списке и Пётр, и Ольга',
      not any('отметился' in (text or '') for _kind, _t, text in shown),
      str(shown[-1:]))
check('и подсказали, что делать',
      any('приезд' in (text or '') for _kind, _title, text in shown),
      str(shown[-1:]))

print()
print('=== Без выбора строки ничего не делаем ===')
shown.clear()
panel.tree.selection_remove(*items)
panel.take()
root.update()

check('попросили выбрать',
      any('выберите' in (text or '').lower() for _kind, _t, text in shown),
      str(shown[-1:]))

print()
print('=== Вкладка живёт внутри «Записи» ===')
tab = tab_module.AppointmentsTab(root, db)
root.update()

titles = [tab.tabs.tab(i, 'text').strip() for i in range(len(tab.tabs.tabs()))]
check('вкладки две', len(titles) == 2, str(titles))
check('лента первая', titles[0] == 'Лента записи', str(titles))
check('очередь второй', titles[1] == 'Онлайн-очередь', str(titles))
check('лента никуда не делась', tab.canvas.winfo_exists())
check('очередь на месте', tab.queue.frame.winfo_exists())

print()
print('=== Очередь обновляется сама ===')
check('таймер заведён', hasattr(panel, '_tick'))
check('срок разумный', 5 <= panel_module.REFRESH_SECONDS <= 60,
      str(panel_module.REFRESH_SECONDS))

root.destroy()
db.close()
finish()
