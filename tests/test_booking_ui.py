"""
Экран записи: лента времени, карточки и короткая форма записи.

Экран собирается из холста и десятка обработчиков — опечатка видна
только при открытии. Поэтому здесь он действительно строится,
рисуется и по нему кликают.
"""
import _setup
from _setup import use_temp_db, check, finish, silence_dialogs

use_temp_db('booking_ui')

import tkinter as tk
from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Appointment, Client, Car
from services import AppointmentService, ClientService
from services.settings_service import SettingsService

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

service = AppointmentService(db)
clients = ClientService(db)

root = tk.Tk()
root.withdraw()
root.geometry('1200x800')

import styles
styles.apply_modern_styles(root)

import ui.appointments_tab as tab_module
import ui.appointment_dialogs as dialogs_module

shown = silence_dialogs(tab_module, dialogs_module)

TODAY = tab_module.get_moscow_time().date()


def at(hour, minute=0):
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute)


print('=== Экран записи открывается ===')
tab = tab_module.AppointmentsTab(root, db)
tab.frame.pack(fill='both', expand=True)
root.update()
check('экран построен', tab.frame.winfo_exists() == 1)
check('день по умолчанию — сегодня', tab.current_day == TODAY)

print('\n=== Лента размечена по часам ===')
grid = tab.canvas.find_withtag('grid')
check('сетка нарисована', len(grid) > 24, str(len(grid)))
check('высота ленты — ровно сутки',
      tab.canvas.cget('scrollregion').split()[-1] == str(24 * tab_module.HOUR_HEIGHT),
      tab.canvas.cget('scrollregion'))

print('\n=== Записи появляются карточками ===')
first = service.create(scheduled_at=at(10), duration_minutes=60,
                       license_plate='А123ВВ777', client_name='Андрей',
                       client_phone='79099018931')
tab.load_day()
root.update()

tag = f'appt_{first.id}'
items = tab.canvas.find_withtag(tag)
check('карточка нарисована', len(items) == 2, str(len(items)))

texts = [tab.canvas.itemcget(item, 'text') for item in items
         if tab.canvas.type(item) == 'text']
check('на карточке только номер машины', texts == ['А123ВВ777'], str(texts))

print('\n=== Карточка стоит на своём часе ===')
rectangle = [item for item in items if tab.canvas.type(item) == 'rectangle'][0]
top = tab.canvas.coords(rectangle)[1]
check('десять часов — десятая полоса',
      abs(top - 10 * tab_module.HOUR_HEIGHT) < 5, str(top))

print('\n=== Щелчок по карточке открывает подробности ===')
details = dialogs_module.AppointmentDetailsDialog(root, db, first.id)
root.update()
check('окно подробностей открылось', details.dialog.winfo_exists() == 1)
details.dialog.destroy()

print('\n=== Пересечение уходит во вторую колонку ===')
service.set_posts_for_day(TODAY, 2)
second = service.create(scheduled_at=at(10, 30), duration_minutes=60,
                        license_plate='К900ОР99')
tab.load_day()
root.update()

first_x = tab.canvas.coords(
    [i for i in tab.canvas.find_withtag(f'appt_{first.id}')
     if tab.canvas.type(i) == 'rectangle'][0])[0]
second_x = tab.canvas.coords(
    [i for i in tab.canvas.find_withtag(f'appt_{second.id}')
     if tab.canvas.type(i) == 'rectangle'][0])[0]
check('вторая карточка правее первой', second_x > first_x,
      f'{second_x} против {first_x}')

print('\n=== Выбор постов сам по себе ничего не меняет ===')
tab.scope_days.set(1)
before = service.get_posts_for_day(TODAY)
tab.choose_posts(3)
root.update()
check('в базе пока прежнее значение',
      service.get_posts_for_day(TODAY) == before, str(before))
check('на экране выбрана тройка', tab.selected_posts == 3)
check('и сказано, что надо нажать «Применить»',
      'Применить' in tab.posts_hint.cget('text'), tab.posts_hint.cget('text'))

print('\n=== «Применить» закрепляет ===')
tab.apply_posts()
root.update()
check('на сегодня три поста', service.get_posts_for_day(TODAY) == 3)
check('на завтра по-прежнему один',
      service.get_posts_for_day(TODAY + timedelta(days=1)) == 1)
check('показано подтверждение',
      'Готово' in tab.posts_hint.cget('text'), tab.posts_hint.cget('text'))
check('строка состояния обновилась',
      '3 поста' in tab.posts_state.cget('text'), tab.posts_state.cget('text'))

print('\n=== И раздаются на неделю вперёд ===')
tab.scope_days.set(7)
tab.choose_posts(2)
tab.apply_posts()
root.update()
week = [service.get_posts_for_day(TODAY + timedelta(days=i)) for i in range(7)]
check('вся неделя по два', week == [2] * 7, str(week))
check('восьмой день не тронут',
      service.get_posts_for_day(TODAY + timedelta(days=7)) == 1)

print('\n=== Свой срок в днях ===')
tab.scope_days.set(tab_module.CUSTOM_SCOPE)
tab.custom_days.set('10')
check('срок посчитан по числу', tab.scope_length() == 10, str(tab.scope_length()))
tab.choose_posts(1)
tab.apply_posts()
root.update()
ten = [service.get_posts_for_day(TODAY + timedelta(days=i)) for i in range(10)]
check('десять дней по одному посту', ten == [1] * 10, str(ten))
check('одиннадцатый день не тронут',
      service.get_posts_for_day(TODAY + timedelta(days=10)) == 1)

print('\n=== Мусор в сроке не роняет экран ===')
tab.custom_days.set('абв')
check('непонятный срок считается как один день', tab.scope_length() == 1,
      str(tab.scope_length()))
tab.custom_days.set('999')
check('срок больше допустимого урезается',
      tab.scope_length() == tab_module.MAX_SCOPE_DAYS, str(tab.scope_length()))
tab.scope_days.set(1)

print('\n=== Переход по дням ===')
service.set_posts_for_day(TODAY, 3)
tab.load_day()
tab.choose_posts(1)
tab.shift_day(1)
root.update()
check('день сменился', tab.current_day == TODAY + timedelta(days=1))
check('чужих карточек нет', len(tab.canvas.find_withtag('card')) == 0)
check('незакреплённый выбор не переехал на новый день',
      tab.selected_posts == service.get_posts_for_day(tab.current_day),
      str(tab.selected_posts))
check('на прошлом дне осталось прежнее',
      service.get_posts_for_day(TODAY) == 3,
      str(service.get_posts_for_day(TODAY)))
tab.go_today()
root.update()
check('вернулись на сегодня', tab.current_day == TODAY)

# --------------------------------------------------------------------
print('\n=== Форма записи: номер подтягивает клиента ===')
dialog = dialogs_module.AppointmentDialog(root, db, when=at(15))
root.update()

dialog.plate_entry.insert(0, 'а123вв777')
dialog.lookup_by_plate()
root.update()

check('номер приведён к нормальному виду',
      dialog.plate_entry.get() == 'А123ВВ777', dialog.plate_entry.get())
check('имя подставилось', dialog.name_entry.get() == 'Андрей',
      dialog.name_entry.get())
check('телефон подставился', '909' in dialog.phone_entry.get(),
      dialog.phone_entry.get())
check('видно, что клиент найден', 'Клиент' in dialog.found_label.cget('text'),
      dialog.found_label.cget('text'))

print('\n=== Форма записи: незнакомый номер ===')
dialog.plate_entry.delete(0, tk.END)
dialog.plate_entry.insert(0, 'Х555ХХ99')
dialog.lookup_by_plate()
root.update()
check('сказано, что машина новая',
      'ещё нет' in dialog.found_label.cget('text'),
      dialog.found_label.cget('text'))

print('\n=== Запись сохраняется, клиент заводится ===')
dialog.name_entry.delete(0, tk.END)
dialog.name_entry.insert(0, 'Новый клиент')
dialog.phone_entry.delete(0, tk.END)
dialog.phone_entry.insert(0, '8 999 111-22-33')
dialog.wheels_var.set(dialogs_module.WHEELS_TIRES)

before = db.query(Client).count()
dialog.save()
root.update()

check('окно закрылось', dialog.dialog.winfo_exists() == 0)
check('клиент заведён', db.query(Client).count() == before + 1)

created = clients.get_car('Х555ХХ99')
check('машина заведена', created is not None)
check('колёса записаны', created.wheels_assembled is False)

booked = [a for a in service.get_for_day(TODAY)
          if a.license_plate == 'Х555ХХ99']
check('запись создана', len(booked) == 1, str(len(booked)))
check('время как в форме', booked[0].scheduled_at.hour == 15,
      str(booked[0].scheduled_at))
check('время работ взято по колёсам',
      booked[0].duration_minutes == service.duration_for_wheels(False),
      str(booked[0].duration_minutes))

print('\n=== Пустая форма не создаёт запись ===')
empty = dialogs_module.AppointmentDialog(root, db, when=at(16))
root.update()
before = db.query(Appointment).count()
empty.save()
root.update()
check('запись не создана', db.query(Appointment).count() == before)
check('окно осталось открытым', empty.dialog.winfo_exists() == 1)
empty.dialog.destroy()

print('\n=== Отметка приезда ===')
details = dialogs_module.AppointmentDetailsDialog(root, db, first.id)
root.update()
details.mark_arrived()
root.update()
check('запись отмечена как приехавшая',
      service.get(first.id).status == Appointment.STATUS_ARRIVED,
      service.get(first.id).status)

tab.load_day()
root.update()
check('карточка осталась в ленте',
      len(tab.canvas.find_withtag(f'appt_{first.id}')) == 2)

root.destroy()
db.close()
finish()
