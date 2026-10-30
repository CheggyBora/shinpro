"""
Разделы задач и Telegram по разделам (решение владельца 30.10.2026).

  · свои разделы добавляются, встроенные переименовываются и скрываются,
    удаления нет; «Рабочую» не скрыть;
  · задача уходит тем, кто отмечен для её раздела; раздел без своих —
    как у задач вообще;
  · в задаче людей можно поменять (блок «Уведомить») — только для неё;
  · контрагент с ником получает лично;
  · разделы и получатели уходят на сервер;
  · в отчёте за смену — имена мастеров.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('task_sections')
shown = _setup.silence_dialogs()

import tkinter as tk
from datetime import date

from config import init_db, SessionLocal
from models import calendar as cal
from models.calendar import Counterparty, TelegramOutbox, new_uid
from services import task_sections, telegram_outbox
from services.calendar_service import CalendarService
from services.telegram_service import TelegramService, Recipient
from services.sync_service import SyncService

init_db()
db = SessionLocal()

print('=== Разделы ===')
sections = task_sections.refresh(db)
check('встроенные на месте', [r['key'] for r in sections] == ['work', 'storage', 'tires', 'paint', 'supply'])
mine = task_sections.add(db, 'От контрагента')
check('свой раздел — ключ c1', mine['key'] == 'c1' and cal.CATEGORY_TITLES['c1'] == 'От контрагента')
check('в новых задачах шиномонтажа он есть', 'c1' in cal.categories_of('tire'))
try:
    task_sections.add(db, 'от контрагента')
    check('такое же название — отказ', False)
except task_sections.SectionError as e:
    check('такое же название — отказ', 'уже есть' in str(e))
task_sections.rename(db, 'tires', 'Шины на заказ')
check('встроенный переименован', cal.CATEGORY_TITLES['tires'] == 'Шины на заказ')
task_sections.set_hidden(db, 'paint', True)
check('скрытого в новых задачах нет', 'paint' not in cal.categories_of('tire'))
check('но старые задачи с ним правятся', 'paint' in cal.known_categories('tire'))
try:
    task_sections.set_hidden(db, 'work', True)
    check('«Рабочую» не скрыть', False)
except task_sections.SectionError:
    check('«Рабочую» не скрыть', True)
task_sections.set_hidden(db, 'paint', False)
color = task_sections.load(db)[-1]['colors']
task_sections.set_color(db, 'c1', 3)
check('свой раздел перекрашен', task_sections.load(db)[-1]['colors'] != color)
check('разделы держатся после перезапуска',
      [r['title'] for r in task_sections.load(SessionLocal())][-1] == 'От контрагента')

print('\n=== Кому уходит задача ===')
telegram = TelegramService(db)
telegram.save_token('123:TOKEN')
telegram.save_recipients([Recipient('101', 'Олег', enabled=True, username='oleg'),
                          Recipient('202', 'Дмитрий', enabled=False, username='dima'),
                          Recipient('303', 'Сергей', enabled=False, username='serg')])
service = CalendarService(db)
check('раздел без своих — тем, кому отчёт за смену',
      service.notify_defaults('paint') == ['101'])
telegram_outbox.set_route(db, 'task_paint', ['202'])
check('у «Покраски» — маляр, хоть отчёт за смену ему и не идёт',
      service.notify_defaults('paint') == ['202'])
telegram_outbox.set_route(db, 'task', ['303'])
check('раздел без своих — как у задач вообще', service.notify_defaults('c1') == ['303'])

sent = []


def fake_call(self, method, fields, files=None):
    sent.append((fields.get('chat_id'), fields.get('text', '')))
    return {'username': 'bot'}


TelegramService._call = fake_call
party = Counterparty(uid=new_uid(), name='Покраска «Колор»', telegram='kolor', direction='tire')
telegram.save_recipients(telegram.get_recipients() + [Recipient('404', 'Колор', username='kolor')])
db.add(party)
db.commit()

task = service.create(title='Забрать диски', category='paint', due_date=date.today(),
                      counterparty_uid=party.uid)
service.announce(task)
telegram_outbox.flush(db)
check('по разделу — маляру и контрагенту лично',
      sorted(chat for chat, _ in sent) == ['202', '404'], str(sent))
check('в тексте — раздел задачи', 'Покраска' in sent[0][1])

sent.clear()
task = service.create(title='Привёз шины на шиномонтаж', category='c1', due_date=date.today())
service.announce(task, chats=['101', '303'])
telegram_outbox.flush(db)
check('отмеченные в задаче — только им', sorted(c for c, _ in sent) == ['101', '303'], str(sent))
check('в тексте — свой раздел', 'От контрагента' in sent[0][1])

sent.clear()
task = service.create(title='Никому', category='work', due_date=date.today(),
                      counterparty_uid=party.uid)
service.announce(task, chats=[], personal=False)
telegram_outbox.flush(db)
check('сняли всех и контрагента — не уходит никому', sent == [], str(sent))
check('и в очереди не висит', not telegram_outbox.pending(db))

print('\n=== Окно задачи: «Уведомить» ===')
import styles
from ui.task_dialog import TaskDialog
root = tk.Tk()
root.geometry('+-3000+0')
styles.apply_modern_styles(root)
dialog = TaskDialog(root, db, defaults={'category': 'paint', 'direction': 'tire'})
root.update()
ticked = {chat for chat, var in dialog.notify_vars.items() if var.get()}
check('раздел «Покраска» — отмечен маляр', ticked == {'202'}, str(ticked))
dialog.category.set('c1')
dialog._category_chosen()
ticked = {chat for chat, var in dialog.notify_vars.items() if var.get()}
check('сменили раздел — отметки по новому', ticked == {'303'}, str(ticked))
dialog.notify_vars['101'].set(True)
dialog._touched()
dialog.category.set('paint')
dialog._category_chosen()
check('тронули руками — раздел отметки не сбивает', dialog.notify_vars['101'].get())
dialog.party.set('Покраска «Колор»')
dialog._draw_personal()
check('контрагент с ником — строка «лично»', dialog.personal_var is not None and dialog.personal_var.get())
dialog.title.insert(0, 'Отвезти диски')
sent.clear()
dialog.save()
telegram_outbox.flush(db)
check('сохранили — ушло отмеченным и контрагенту',
      sorted(c for c, _ in sent) == ['101', '303', '404'],
      str(sent))
root.destroy()

print('\n=== На сервер ===')
settings = SyncService(db).collect_push()['settings']
check('разделы уходят', '"От контрагента"' in settings['task_sections'])
check('получатели раздела уходят', settings['telegram_chats_task_paint'] == '202'
      and settings['telegram_chats_task'] == '303', str(settings.get('telegram_chats_task_paint')))

db.close()
finish()
