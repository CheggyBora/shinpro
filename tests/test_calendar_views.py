"""
Календарь: комментарии, время «с–до», месяц (решение владельца 29.10.2026).

Задача — с галочкой, напоминает, краснеет и переходит на завтра.
Комментарий — просто запись на день: не просрочивается, не висит в
ленте над нарядами и не всплывает в наряде машины.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('calendar_views')

from datetime import timedelta

from config import init_db, SessionLocal
from models.calendar import KIND_NOTE, KIND_TASK
from services.calendar_service import CalendarService, TaskError, clean_times
from utils import get_moscow_time, as_naive

init_db()
db = SessionLocal()
cal = CalendarService(db)
now = as_naive(get_moscow_time()).replace(second=0, microsecond=0)
today = now.date()


def error(action):
    try:
        action()
    except TaskError as e:
        return str(e)
    return None


print('=== Время «с» и «до» ===')
check('11:00–12:30', clean_times('11:00', '1230') == ('11:00', '12:30'))
check('«до» без «с» отбрасываем', clean_times('', '12:00') == (None, None))
check('«до» раньше «с» — ошибка', error(lambda: clean_times('12:00', '11:00')))
task = cal.create('Забрать диски', today, category='paint', due_time='11:00', end_time='12:30')
check('задача с «до»', task.end_time == '12:30' and task.kind == KIND_TASK)
cal.move(task, hours=1)
check('+1 час сохраняет длительность', (task.due_time, task.end_time) == ('12:00', '13:30'),
      f'{task.due_time}–{task.end_time}')
cal.update(task, due_time='')
check('убрали «с» — «до» тоже ушло', task.due_time is None and task.end_time is None)

print('\n=== Комментарий ===')
yesterday = today - timedelta(days=1)
note = cal.create('Свет отключали с 12 до 13', yesterday, kind=KIND_NOTE)
check('комментарий без раздела — в «Рабочей»', note.kind == KIND_NOTE and note.category == 'work')
check('пустой комментарий — просит текст', 'комментарий' in (error(
    lambda: cal.create('  ', today, kind=KIND_NOTE)) or ''))
old = cal.create('Позвонить', yesterday)
check('вчерашняя задача — просрочена', old in cal.overdue(today))
check('вчерашний комментарий — нет', note not in cal.overdue(today))
note_today = cal.create('Ваня до обеда', today, kind=KIND_NOTE)
plate_note = cal.create('Клиент просил без звонка', today, kind=KIND_NOTE,
                        license_plate='А123ВС77')
strip = cal.strip(now)
check('в ленте над нарядами комментариев нет',
      note_today not in strip and plate_note not in strip and old in strip)
check('в наряде машины комментарий не всплывает', plate_note not in cal.for_plate('А123ВС77', now))
check('в дне календаря комментарий есть', note_today in cal.day(today))

print('\n=== Фильтр «Комментарии» ===')
only_notes = cal.day(today, categories={KIND_NOTE})
check('только комментарии', only_notes and all(t.kind == KIND_NOTE for t in only_notes))
paint_and_notes = cal.day(today, categories={'paint', KIND_NOTE})
check('покраска + комментарии', task in paint_and_notes and note_today in paint_and_notes)
check('раздел без комментариев их не показывает',
      note_today not in cal.day(today, categories={'work'}))

print('\n=== Месяц ===')
start = today.replace(day=1)
month = cal.days(start, 35)
check('35 дней подряд', len(month) == 35 and min(month) == start)
check('записи по своим дням', note_today in month[today] and note in month.get(yesterday, [note]))

print('\n=== Обмен ===')
payload = cal.task_payload(task)
check('серверу уходят вид и «до»', payload['kind'] == KIND_TASK and 'end_time' in payload)
cal.apply_server({'tasks': [{
    'uid': 'dash-note-1', 'kind': 'note', 'category': 'work', 'due_date': today.isoformat(),
    'due_time': '08:30', 'end_time': '09:00', 'title': 'С дашборда', 'source': 'dashboard',
    'updated_at': now.isoformat()}]})
row = cal.by_uid('dash-note-1')
check('комментарий из дашборда', row.kind == KIND_NOTE and row.end_time == '09:00')
later = (now + timedelta(minutes=5)).isoformat()
cal.apply_server({'tasks': [{
    'uid': 'dash-note-1', 'category': 'work', 'due_date': today.isoformat(),
    'due_time': '08:30', 'title': 'С дашборда', 'source': 'dashboard', 'updated_at': later}]})
check('старый сервер без вида и «до» их не стирает', row.kind == KIND_NOTE and row.end_time == '09:00')

print('\n=== Сетка: одновременные записи рядом ===')
from ui.calendar_tab import CalendarTab


class T:
    def __init__(self, start, end=None):
        self.due_time, self.end_time = start, end


a, b, c, d = T('11:00', '12:30'), T('11:30', '12:00'), T('14:00'), T('12:30', '13:00')
lanes = {id(t): (lane, count) for t, lane, count in CalendarTab._lanes([a, b, c, d])}
check('11:00–12:30 и 11:30 — две дорожки', lanes[id(a)] == (0, 2) and lanes[id(b)] == (1, 2))
check('12:30 после конца — снова одна', lanes[id(d)] == (0, 1) and lanes[id(c)] == (0, 1))

print('\n=== Telegram: задача уходит, комментарий — нет ===')
from models.calendar import TelegramOutbox
from services import telegram_outbox
from services.calendar_service import clean_telegram
from services.telegram_service import TelegramService, Recipient

check('ник чистится', clean_telegram('https://t.me/Ivan_Shiny/') == 'ivan_shiny'
      and clean_telegram('@Ivan_Shiny') == 'ivan_shiny' and clean_telegram('') is None)
check('кириллица в нике — ошибка', error(lambda: clean_telegram('@иван')))
party = cal.save_counterparty(None, name='Покраска «Колор»', telegram='@Kolor_Paint')
check('ник контрагента сохранён без @', party.telegram == 'kolor_paint')

before = db.query(TelegramOutbox).count()
note = cal.create('Просто запись', today, kind=KIND_NOTE)
check('комментарий в Telegram не уходит', cal.announce(note) is None
      and db.query(TelegramOutbox).count() == before)
job = cal.create('Забрать диски', today, category='paint', due_time='11:00',
                 end_time='12:30', counterparty_uid=party.uid)
cal.announce(job)
rows = db.query(TelegramOutbox).order_by(TelegramOutbox.id).all()[before:]
check('задача — в общую очередь и лично контрагенту',
      len(rows) == 2 and rows[0].target is None and rows[1].target == 'kolor_paint')
check('в тексте время и контрагент',
      '11:00–12:30' in rows[0].text and 'Колор' in rows[0].text and 'Покраска' in rows[0].text)


class FakeTelegram:
    def __init__(self, chats):
        self.chats, self.asked = chats, 0

    def chat_of(self, nick):
        return self.chats.get(nick)

    def fetch_people(self):
        self.asked += 1


telegram_outbox._asked_at = None
fake = FakeTelegram({})
check('не писал боту — ждём, бота спросили', telegram_outbox._personal(db, fake, rows[1]) is None
      and fake.asked == 1 and 'не писал' in (rows[1].last_error or ''))
check('бота второй раз сразу не дёргаем',
      telegram_outbox._personal(db, fake, rows[1]) is None and fake.asked == 1)
fake.chats['kolor_paint'] = '555'
people = telegram_outbox._personal(db, fake, rows[1])
check('написал — шлём ему лично', [p.chat_id for p in people] == ['555'])

service = TelegramService(db)
service.save_recipients([Recipient('777', 'Ваня', True, '@Vanya_Master')])
db.commit()
check('ник получателя запоминается', service.chat_of('vanya_master') == '777'
      and service.usernames() == {'vanya_master': '777'})

db.close()
finish()
