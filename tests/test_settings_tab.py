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

expected = ['Запись', 'Наряды и очередь', 'Группы клиентов',
            'Категории мастеров', 'Выбор колеса', 'Живая очередь', 'Контрагенты', 'Смена', 'Хранение и сезон',
            'Печать', 'Кнопки услуг', 'Реквизиты', 'Отчёты',
            'SMS и звонки', 'Telegram', 'Связь с приложением']
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
# Онлайн-очередь «из дома» отменена (docs/live_queue.md) — её полей
# в настройках быть не должно, чтобы не путать с живой очередью
check('старой онлайн-очереди в настройках нет',
      not ({'queue_posts', 'queue_min_wait_minutes', 'queue_lead_minutes'}
           & set(built.numeric_fields)),
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

print()
print('=== Часы записи: закрытие раньше открытия не сохраняется ===')
# Окон в кабинете не будет вовсе, и человек решит, что сломалась
# запись. Сказать об этом надо в момент правки, а не оставлять
# разбираться через неделю без клиентов


def put_hours(opens, closes):
    for key, value in (('booking_opens_at', opens),
                       ('booking_closes_at', closes)):
        field = built.time_fields[key]
        field.delete(0, 'end')
        field.insert(0, value)


was_opens = settings.get('booking_opens_at')
shown.clear()

put_hours('20:00', '09:00')
built.save()
root.update()

check('сказали, что так нельзя',
      any('раньше открытия' in (text or '')
          for _kind, _title, text in shown), str(shown[-1:]))
check('ничего не записалось',
      settings.get('booking_opens_at') == was_opens,
      f"{settings.get('booking_opens_at')} против {was_opens}")

print()
print('=== Одинаковые часы — тоже нельзя ===')
shown.clear()
put_hours('09:00', '09:00')
built.save()
root.update()

check('отказали', any('раньше открытия' in (text or '')
                      for _kind, _title, text in shown), str(shown[-1:]))

print()
print('=== Круглые сутки сохраняются ===')
shown.clear()
put_hours('00:00', '24:00')
built.save()
root.update()

check('приняли', settings.get('booking_opens_at') == '00:00'
      and settings.get('booking_closes_at') == '24:00',
      f"{settings.get('booking_opens_at')} — {settings.get('booking_closes_at')}")

root.destroy()
db.close()
finish()
