"""
Окно настроек и окно порядка кнопок.

Собираются они из десятков полей, и опечатка в любом видна только
при открытии. Поэтому здесь окна действительно создаются, заполняются
и сохраняются — как если бы их открыл человек.
"""
import _setup
from _setup import use_temp_db, check, finish, silence_dialogs

use_temp_db('settings_ui')

import tkinter as tk

from config import init_db, SessionLocal
from models import Service
from services import TelegramService, Recipient
from services.settings_service import SettingsService
from services.service_layout import build_columns

init_db()
db = SessionLocal()
settings = SettingsService(db)
settings.ensure_defaults()

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.add(Service(name='Балансировка', vehicle_type='car', price_r16=500.0))
db.add(Service(name='Мойка', vehicle_type='car', price_r16=300.0))
db.commit()

root = tk.Tk()
root.withdraw()

import styles
styles.apply_modern_styles(root)

import ui.settings_dialog as settings_module
import ui.service_buttons_dialog as buttons_module

shown = silence_dialogs(settings_module, buttons_module)

print('=== Окно настроек открывается ===')
dialog = settings_module.SettingsDialog(root, db)
root.update()
check('окно создано', dialog.dialog.winfo_exists() == 1)

print('\n=== Реквизиты подставились в поля ===')
check('название на месте',
      dialog.company_fields['company_name'].get() == 'Шиномонтаж «РИФ»',
      dialog.company_fields['company_name'].get())
check('ИНН на месте',
      dialog.company_fields['company_inn'].get() == '770208926387')

print('\n=== Правка реквизитов сохраняется ===')
dialog.company_fields['company_phone'].delete(0, tk.END)
dialog.company_fields['company_phone'].insert(0, '+7 495 111-22-33')
dialog.company_fields['company_address'].delete(0, tk.END)
dialog.company_fields['company_address'].insert(0, 'г. Тула, ул. Мира, 5')

print('\n=== Получатели правятся в окне ===')
dialog.recipients = [Recipient('-100500', 'Владелец'),
                     Recipient('-100600', 'Бухгалтер', enabled=False)]
dialog._refresh_recipients()
rows = dialog.recipients_tree.get_children()
check('в списке двое', len(rows) == 2, str(len(rows)))
check('выключенный помечен',
      dialog.recipients_tree.item(rows[1])['values'][2] == 'нет',
      str(dialog.recipients_tree.item(rows[1])['values']))

dialog.recipients_tree.selection_set(rows[1])
dialog.toggle_recipient()
check('переключение включает отправку', dialog.recipients[1].enabled is True)

dialog.token_entry.delete(0, tk.END)
dialog.token_entry.insert(0, '999:XYZ')

dialog.save()
root.update()

print('\n=== Сохранённое лежит в базе ===')
saved = SettingsService(db)
check('телефон сохранён', saved.get('company_phone') == '+7 495 111-22-33',
      saved.get('company_phone'))
check('адрес сохранён', saved.get('company_address') == 'г. Тула, ул. Мира, 5')

telegram = TelegramService(db)
check('токен сохранён', telegram.get_token() == '999:XYZ')
recipients = telegram.get_recipients()
check('оба получателя сохранены', len(recipients) == 2, str(len(recipients)))
check('оба включены', len(telegram.get_active_recipients()) == 2)
check('окно закрылось', dialog.dialog.winfo_exists() == 0)

print('\n=== Проверка связи без токена не падает ===')
second = settings_module.SettingsDialog(root, db)
root.update()
second.token_entry.delete(0, tk.END)
second.recipients = []
second.test_telegram()
root.update()
check('сказано, чего не хватает',
      'токен' in second.telegram_status.cget('text').lower(),
      second.telegram_status.cget('text'))
second.dialog.destroy()

print('\n=== Окно порядка кнопок ===')
buttons = buttons_module.ServiceButtonsDialog(root, db)
root.update()
check('четыре колонки', len(buttons.lists) == 4, str(len(buttons.lists)))

first_column = list(buttons.lists[0].get(0, 'end'))
check('услуги прайса разложены', 'Шиномонтаж' in first_column, str(first_column))

print('\n=== Перестановка внутри колонки ===')
position = first_column.index('Шиномонтаж')
buttons.lists[0].selection_set(position)
buttons.move_inside(1)
moved = list(buttons.lists[0].get(0, 'end'))
check('услуга сдвинулась вниз', moved.index('Шиномонтаж') == position + 1,
      str(moved))

print('\n=== Перенос в соседнюю колонку ===')
buttons.lists[0].selection_clear(0, 'end')
buttons.lists[0].selection_set(0)
top_name = buttons.lists[0].get(0)
buttons.move_between(1)
check('услуга ушла из первой колонки',
      top_name not in list(buttons.lists[0].get(0, 'end')))
check('и появилась во второй',
      top_name in list(buttons.lists[1].get(0, 'end')))

print('\n=== Из крайней колонки не уезжает за край ===')
before = list(buttons.lists[3].get(0, 'end'))
if before:
    buttons.lists[0].selection_clear(0, 'end')
    buttons.lists[3].selection_set(0)
    buttons.move_between(1)
    check('крайняя колонка не потеряла услугу',
          list(buttons.lists[3].get(0, 'end')) == before)
else:
    check('крайняя колонка не потеряла услугу', True, 'колонка пуста')

print('\n=== Порядок сохраняется ===')
expected = [list(listbox.get(0, 'end')) for listbox in buttons.lists]
buttons.save()
root.update()

stored = build_columns(db, ['Шиномонтаж', 'Балансировка', 'Мойка'])
check('раскладка совпала с окном', stored == expected,
      f'{stored} против {expected}')
check('окно закрылось', buttons.dialog.winfo_exists() == 0)

print('\n=== Новая услуга появляется в кнопках сама ===')
db.add(Service(name='Правка диска', vehicle_type='car', price_r16=1500.0))
db.commit()
with_new = build_columns(db, ['Шиномонтаж', 'Балансировка', 'Мойка', 'Правка диска'])
placed = [name for column in with_new for name in column]
check('новая услуга получила место', 'Правка диска' in placed, str(placed))

root.destroy()
db.close()
finish()
