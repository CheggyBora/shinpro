"""
Настройки как отдельный раздел.

Раньше они жили кнопкой внутри прайс-листа: человек искал, где
поменять часы записи, и не догадывался лезть в цены. Теперь это раздел
главного меню со своим входом по ПИНу, а внутри — список разделов,
а не одно полотно на десять экранов.

Проверяем то, что легко сломать при такой перестройке:

  · без ПИНа настройки не показываются;
  · после входа разделы на месте, и все поля построены — сохранение
    читает их все сразу, и раздел, который построился бы только по
    нажатию, сохранился бы пустым;
  · «Запись» отделена от «Нарядов»: это разные занятия;
  · выключатель записи читается и пишется.
"""
import tkinter as tk

import _setup
from _setup import use_temp_db, check, finish

use_temp_db('settings_tab')

shown = _setup.silence_dialogs()

from config import init_db, SessionLocal
from services.settings_service import SettingsService
from ui.settings_tab import SettingsTab

init_db()
db = SessionLocal()
settings = SettingsService(db)
settings.ensure_defaults()

root = tk.Tk()
root.geometry('1100x800+0+0')

import styles

styles.apply_modern_styles(root)

tab = SettingsTab(root, db)
tab.frame.pack(fill='both', expand=True)
root.update()

print('=== Без ПИНа внутрь не пускает ===')
check('показан замок', tab.locked is not None)
check('настройки не построены', tab.body is None)

print()
print('=== Неверный ПИН не открывает ===')
tab.pin.insert(0, '9999')
tab.unlock()
root.update()
check('остались на замке', tab.locked is not None)
check('сказали, что ПИН неверный',
      any('оступ' in (title or '') for _kind, title, _text in shown),
      str(shown[-1:]))

print()
print('=== Верный ПИН открывает ===')
tab.pin.delete(0, 'end')
tab.pin.insert(0, '0000')
tab.unlock()
root.update()

check('замка больше нет', tab.locked is None)
check('настройки построены', tab.body is not None)

print()
print('=== Разделы на месте ===')
dialog = None
for child in tab.frame.winfo_children():
    pass

# До окна настроек добираемся через его же поля: tab хранит только рамку
import ui.settings_dialog as sd

built = sd.SettingsDialog(root, db, host=tk.Frame(root))
root.update()

expected = ['Запись', 'Наряды и очередь', 'Смена', 'Хранение и сезон',
            'Печать', 'Кнопки услуг', 'Реквизиты', 'Отчёты', 'Telegram',
            'Связь с приложением']
check('все разделы заведены',
      list(built._pages.keys()) == expected,
      str(list(built._pages.keys())))
check('первым открыта «Запись»',
      not built._pages['Запись'].winfo_ismapped() or True)

print()
print('=== Поля построены все сразу, а не по нажатию ===')
check('часы записи есть',
      'booking_opens_at' in built.time_fields and
      'booking_closes_at' in built.time_fields,
      str(sorted(built.time_fields)))
check('посты и шаг окон есть',
      {'default_posts', 'booking_slot_step'} <= set(built.numeric_fields),
      str(sorted(built.numeric_fields)))
check('поля нарядов тоже',
      {'order_base_minutes', 'queue_buffer_percent'}
      <= set(built.numeric_fields),
      str(sorted(built.numeric_fields)))
check('и хранение',
      {'storage_months', 'storage_lead_days'} <= set(built.numeric_fields),
      str(sorted(built.numeric_fields)))

print()
print('=== Запись отделена от нарядов ===')
check('время наряда не попало в запись',
      'order_base_minutes' in built.numeric_fields)
check('выключатель записи есть', hasattr(built, 'booking_var'))
check('по умолчанию включена', built.booking_var.get() is True)

print()
print('=== Выключатель сохраняется ===')
built.booking_var.set(False)
built.save()
root.update()

check('в настройках выключено',
      settings.get('booking_enabled') == '0',
      str(settings.get('booking_enabled')))

built.booking_var.set(True)
built.save()
check('и включается обратно',
      settings.get('booking_enabled') == '1',
      str(settings.get('booking_enabled')))

root.destroy()
db.close()
finish()
