"""
Календарь задач, склад, покраска и Telegram (docs/calendar.md).

Проверяем то, ради чего это делалось:

  · задачу можно завести, поправить, перенести и отметить;
  · неотмеченная задача прошлых дней не теряется — она в ленте красной;
  · задача про машину видна в её наряде;
  · фильтры по разделам не путают склад, покраску и шины;
  · обмен с сервером: своя свежая правка не затирается чужой старой;
  · склад и покраска ставят задачу и пишут в Telegram — тем, кого
    выбрали, а без интернета сообщение ждёт;
  · хранение из наряда открывает форму, заполненную из наряда.
"""
import _setup
from _setup import use_temp_db, check, finish

import os
from datetime import date, datetime, timedelta

use_temp_db('calendar')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from models import Service, CalendarTask, TireStorage, Client, TelegramOutbox
from models.calendar import WORK, STORAGE, TIRES, PAINT
from services import EmployeeService, OrderService
from services.shift_service import ShiftService
from services.settings_service import SettingsService
from services.calendar_service import CalendarService, TaskError, clean_time, parse_day
from services import telegram_outbox
from services.telegram_service import TelegramService, Recipient
from utils import get_moscow_time, as_naive

init_db()
db = SessionLocal()
calendar = CalendarService(db)
now = as_naive(get_moscow_time()).replace(second=0, microsecond=0)
today = now.date()

print('=== Время и дата пишутся по-человечески ===')
check('«9:5» → 09:05', clean_time('9:5') == '09:05')
check('«0930» → 09:30', clean_time('0930') == '09:30')
check('пусто — без времени', clean_time('') is None)
try:
    clean_time('25:00')
    check('25:00 — не время', False)
except TaskError:
    check('25:00 — не время', True)
check('«27.10.2026»', parse_day('27.10.2026') == date(2026, 10, 27))
check('«27.10» — этот год', parse_day('27.10') == date(today.year, 10, 27))

print()
print('=== Завести, поправить, перенести, отметить ===')
task = calendar.create('Еврошины — 8 шин R17', today, category=TIRES, due_time='10:00',
                       license_plate='а123вв777', note='Проверить по накладной')
check('номер приведён к виду', task.license_plate == 'А123ВВ777', task.license_plate)
check('uid есть', len(task.uid) >= 32)
try:
    calendar.create('', today)
    check('без названия — нельзя', False)
except TaskError:
    check('без названия — нельзя', True)
calendar.update(task, title='Еврошины — 8 шин R17 Nokian', due_time='11:30')
check('поправили', task.title.endswith('Nokian') and task.due_time == '11:30')
calendar.move(task, hours=1)
check('+1 час', task.due_time == '12:30' and task.due_date == today, f'{task.due_date} {task.due_time}')
calendar.move(task, days=1)
check('завтра', task.due_date == today + timedelta(days=1))
calendar.move(task, days=7)
check('через неделю', task.due_date == today + timedelta(days=8))
calendar.move(task, to_date=today, to_time='10:00')
check('любая дата', task.due_date == today and task.due_time == '10:00')
calendar.set_done(task, True, by='Сергей')
check('сделано — кто и когда', task.done_at is not None and task.done_by == 'Сергей')
calendar.set_done(task, False)
check('вернули в работу', task.done_at is None)

print()
print('=== Просроченное не теряется ===')
old = calendar.create('Заказать грузики', today - timedelta(days=1), category=WORK)
strip = calendar.strip(now)
check('вчерашняя неотмеченная — в ленте', old in strip)
check('и она красная', calendar.state(old, now) == 'overdue')
soon = calendar.create('Привезти со склада', today, category=STORAGE,
                       due_time=(now + timedelta(minutes=20)).strftime('%H:%M'))
if (now + timedelta(minutes=20)).date() == today:
    check('через 20 минут — жёлтая', calendar.state(soon, now) == 'soon')
check('считаем просроченные для меню', calendar.overdue_count(now) >= 1)
calendar.set_done(old, True)
check('отметили — ушла из ленты', old not in calendar.strip(now))
calendar.move(soon, days=1)

print()
print('=== Раздел и фильтры ===')
calendar.create('Покраска К555КК77', today, category=PAINT)
only_paint = calendar.day(today, categories={PAINT})
check('фильтр «Покраска»', only_paint and all(t.category == PAINT for t in only_paint))
both = calendar.day(today, categories={PAINT, TIRES})
check('два раздела сразу', {t.category for t in both} == {PAINT, TIRES}, str({t.category for t in both}))
week = calendar.week(today)
check('неделя — семь дней с понедельника',
      len(week) == 7 and min(week).weekday() == 0)

print()
print('=== Задача по машине — в её наряде ===')
hint = calendar.for_plate('А123ВВ777', now)
check('нашлась по номеру', [t.id for t in hint] == [task.id], str(hint))
calendar.delete(task)
check('удалённую не показываем', calendar.for_plate('А123ВВ777', now) == [])
check('но строка осталась — удаление дойдёт до сервера', calendar.by_uid(task.uid).deleted)

print()
print('=== Обмен: чья правка новее ===')
tasks, parties = calendar.unsent()
check('новое ждёт отправки', task in tasks)
answer = {'tasks': [], 'counterparties': []}
calendar.apply_server(answer, tasks, parties)
check('после обмена — отдано', calendar.unsent()[0] == [])
fresh = calendar.create('Своя свежая', today)
payload = calendar.task_payload(fresh)
stale = dict(payload, title='Старая с сервера',
             updated_at=(as_naive(fresh.updated_at) - timedelta(minutes=5)).isoformat())
calendar.apply_server({'tasks': [stale]})
check('старая серверная не затирает свежую', fresh.title == 'Своя свежая')
newer = dict(payload, title='Владелец поправил', due_time='15:00',
             updated_at=(as_naive(fresh.updated_at) + timedelta(minutes=5)).isoformat())
calendar.apply_server({'tasks': [newer]})
check('новая серверная — принята', fresh.title == 'Владелец поправил' and fresh.due_time == '15:00')
from_dashboard = {'uid': 'dash-1', 'category': 'work', 'due_date': today.isoformat(),
                  'due_time': None, 'title': 'Позвонить бухгалтеру', 'deleted': False,
                  'source': 'dashboard', 'created_by': 'Владелец',
                  'updated_at': now.isoformat()}
calendar.apply_server({'tasks': [from_dashboard]})
row = calendar.by_uid('dash-1')
check('задача из дашборда появилась', row is not None and row.source == 'dashboard')
check('и не уходит обратно лишний раз', row not in calendar.unsent()[0])

print()
print('=== Контрагенты ===')
party = calendar.save_counterparty(name='Еврошины', kind='поставщик шин', phone='+7 495 000-00-00')
check('заведён', party.uid and calendar.counterparties()[0].name == 'Еврошины')
try:
    calendar.save_counterparty(name='  ')
    check('без названия — нельзя', False)
except TaskError:
    check('без названия — нельзя', True)
linked = calendar.create('Поставка', today, category=TIRES, counterparty_uid=party.uid)
check('задачи контрагента', linked in calendar.tasks_of_counterparty(party.uid))

print()
print('=== Telegram: кому и когда ===')
telegram = TelegramService(db)
telegram.save_token('123:test')
telegram.save_recipients([Recipient('100', 'Владелец'), Recipient('200', 'Водитель'),
                          Recipient('300', 'Маляр')])
check('без выбора — всем', [r.chat_id for r in telegram_outbox.recipients(db, 'storage')] == ['100', '200', '300'])
telegram_outbox.set_route(db, 'storage', ['200'])
check('склад — водителю', [r.chat_id for r in telegram_outbox.recipients(db, 'storage')] == ['200'])
check('для сервера — его номер', telegram_outbox.chats_for_server(db, 'storage') == '200')
check('покраска — по-прежнему всем', len(telegram_outbox.recipients(db, 'paint')) == 3)

sent = []
offline = {'on': True}


def fake_call(self, method, fields, files=None):
    from services.telegram_service import TelegramError
    if offline['on']:
        raise TelegramError('нет связи')
    sent.append((fields['chat_id'], fields['text']))
    return {}


TelegramService._call = fake_call
telegram_outbox.queue(db, 'storage', 'Привезти со склада №1')
check('без связи — не ушло', telegram_outbox.flush(db) == 0 and len(telegram_outbox.pending(db)) == 1)
offline['on'] = False
check('связь вернулась — ушло', telegram_outbox.flush(db) == 1 and telegram_outbox.pending(db) == [])
check('и только водителю', sent == [('200', 'Привезти со склада №1')], str(sent))

print()
print('=== Склад: задачи и сообщения ===')
storage = TireStorage(car_number='А123ВВ777', storage_type='Шины с дисками', diameter='R16',
                      brand='Nokian', price=5000, client_name='Иван Петров', client_phone='79161234567')
db.add(storage)
db.commit()
to = calendar.storage_to_warehouse(storage, today + timedelta(days=1))
check('«отвезти на склад» — раздел хранения', to.category == STORAGE and to.storage_ref == str(storage.id))
back = calendar.storage_from_warehouse(storage, today + timedelta(days=3), '10:00', 'Перекидка')
check('«привезти со склада» — к дате и времени',
      back.due_time == '10:00' and 'Перекидка' in back.note and back.license_plate == 'А123ВВ777')
paint = calendar.paint_job('К555КК77', today + timedelta(days=5), 'R17', 4, 18700,
                           details='Пескоструй', client_name='Иван Петров')
check('покраска — с суммой', paint.category == PAINT and paint.amount == 18700)

db.close()

print()
print('=== В окне: лента, календарь, хранение из наряда, покраска ===')
import tkinter as tk
import ui.tire_storage_tab
import ui.paint_tab
import ui.calendar_tab
import ui.task_dialog
shown = _setup.silence_dialogs(ui.tire_storage_tab, ui.paint_tab, ui.calendar_tab, ui.task_dialog)
from ui import MainWindow

root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
check('в меню есть «Календарь»', any(t.startswith('Календарь') for t in app.nav.titles()), str(app.nav.titles()))
check('лента над нарядами нарисована', len(app.orders_tab.tasks_strip.winfo_children()) > 1)

cal = app.calendar_tab
cal.go_today()
root.update()
cal.toggle_filter(PAINT)
check('фильтр запомнился', SettingsService(app.db).get('calendar_filter') == PAINT)
cal.toggle_filter('all')
check('«Все» — снова всё', SettingsService(app.db).get('calendar_filter') == '')

ShiftService(app.db).open_shift(open_posts=2)
EmployeeService(app.db).register_employee(1)
EmployeeService(app.db).start_shift(1)
app.db.add(Service(name='Хранение шин', vehicle_type='car', price_r16=5000))
app.db.commit()
order = OrderService(app.db).create_order('А123ВВ777', 'R16', 'car', client_name='Иван Петров',
                                          client_phone='79161234567')
order.client.driver_license = '77 12 345678'
app.db.commit()
app.orders_tab.open_order_tab(order)
root.update()
app.storage_from_order(order, release=False)
root.update()
st = app.tire_storage_tab
check('открылась вкладка хранения', app.nav.current() == app.nav.titles().index('Хранение шин'))
check('номер подставлен', st.car_number_entry.get() == 'А123ВВ777')
check('клиент подставлен', st.client_name_entry.get() == 'Иван Петров')
check('телефон подставлен', '916' in st.client_phone_entry.get(), st.client_phone_entry.get())
check('водительское подставлено', st.driver_license_entry.get() == '77 12 345678')
check('диаметр подставлен', st.diameter_var.get() == 'R16')

st.show_receipt_dialog = lambda *a, **k: None
st.accept_storage_with_payment('cash', 5000)
db = SessionLocal()
kept = db.query(TireStorage).filter(TireStorage.car_number == 'А123ВВ777').order_by(TireStorage.id.desc()).first()
check('комплект принят с клиентом', kept.client_name == 'Иван Петров' and kept.client_id == order.client_id)
task_to = db.query(CalendarTask).filter(CalendarTask.storage_ref == str(kept.id),
                                       CalendarTask.title.like('Отвезти%')).first()
check('задача «отвезти на склад»', task_to is not None and task_to.category == STORAGE)
check('сообщение в очереди', db.query(TelegramOutbox).filter(
    TelegramOutbox.text.like('%Отвезти на склад%')).count() == 1)
db.close()

app.storage_from_order(order, release=True)
root.update()
selected = st.storage_tree.selection()
check('выдача: комплект машины выбран', bool(selected) and
      st.storage_tree.item(selected[0])['values'][1] == 'А123ВВ777')
from ui.tire_storage_tab import WarehouseOrderDialog
dialog = WarehouseOrderDialog(st.frame, app.db, st.service.get_storage_by_id(kept.id))
dialog.time.delete(0, 'end')
dialog.time.insert(0, '9:30')
dialog.save()
db = SessionLocal()
task_back = db.query(CalendarTask).filter(CalendarTask.storage_ref == str(kept.id),
                                         CalendarTask.title.like('Привезти%')).first()
check('заказ со склада — задача', task_back is not None and task_back.due_time == '09:30')
db.close()

paint_tab = app.paint_tab
paint_tab.plate.pick('А123ВВ777')
check('покраска: владелец подставлен', 'Иван' in paint_tab.owner_label.cget('text'))
paint_tab.place_order()
db = SessionLocal()
painted = db.query(CalendarTask).filter(CalendarTask.category == PAINT,
                                       CalendarTask.license_plate == 'А123ВВ777').first()
check('оформили покраску — задача с суммой', painted is not None and painted.amount > 0)
check('и сообщение', db.query(TelegramOutbox).filter(TelegramOutbox.kind == 'paint').count() >= 1)
db.close()

app._calendar_refresh()
widget = app.orders_tab.active_orders[order.id]
widget.refresh_tasks()
root.update()
check('в наряде видны задачи машины', len(widget.tasks_box.winfo_children()) >= 1)

from ui.task_dialog import TaskDialog
editor = TaskDialog(root, app.db, None, None, {'due_date': today})
editor.title.insert(0, 'Из окна')
editor.time.insert(0, '18:00')
editor.save()
db = SessionLocal()
check('задача из окна сохранилась',
      db.query(CalendarTask).filter(CalendarTask.title == 'Из окна',
                                    CalendarTask.due_time == '18:00').count() == 1)
db.close()

from ui.car_info import CarInfo
card = CarInfo(root, app.db, 'А123ВВ777')
root.update()
check('«всё по машине» открылось', card.owner is not None and card.owner.name == 'Иван Петров')
card.dialog.destroy()

root.destroy()
finish()
