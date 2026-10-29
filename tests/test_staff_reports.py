"""
Отчёты людям из «Доступа» дашборда (решение владельца 29.10.2026).

Сервер в ответе на обмен присылает {отчёт: [ники]}. Программа шлёт
сводку по смене, склад, покраску и задачи и этим людям — если они
писали боту, — вдобавок к своим получателям и без повторов.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('staff_reports')

import json

from config import init_db, SessionLocal
from services import telegram_outbox
from services.settings_service import SettingsService
from services.sync_service import SyncService
from services.telegram_service import TelegramService, Recipient, STAFF_REPORTS_KEY

init_db()
db = SessionLocal()
telegram = TelegramService(db)
settings = SettingsService(db)
settings.set('telegram_bot_token', 'bot-token')
telegram.save_recipients([
    Recipient('100', 'Владелец', True, 'owner_rif'),
    Recipient('200', 'Ольга', False, 'olga_admin'),
])
db.commit()

print('=== Сервер прислал, кому что ===')
sync = SyncService(db)
asked = []
TelegramService.fetch_people = lambda self: asked.append(1) or (0, 0)
sync._adopt_staff_reports({'shift': ['olga_admin'], 'storage': ['olga_admin', 'new_driver']})
plan = json.loads(settings.get(STAFF_REPORTS_KEY))
check('план сохранён', plan.get('shift') == ['olga_admin'])
check('есть незнакомый ник — спросили бота, кто ему писал', asked == [1])

print('\n=== Сводка по смене ===')
people = telegram.staff_recipients('shift')
check('Ольге — хотя галочка «отправлять» у неё в программе снята',
      [p.chat_id for p in people] == ['200'])
telegram.save_recipients([Recipient('100', 'Владелец', False, 'owner_rif'),
                          Recipient('200', 'Ольга', False, 'olga_admin')])
db.commit()
check('никто не отмечен в программе, но Ольге отмечено в дашборде — сводка уйдёт',
      telegram.is_configured('shift') and not telegram.is_configured())
telegram.save_recipients([Recipient('100', 'Владелец', True, 'owner_rif'),
                          Recipient('200', 'Ольга', False, 'olga_admin')])
db.commit()

print('\n=== Склад ===')
chats = [r.chat_id for r in telegram_outbox.recipients(db, 'storage')]
check('владельцу и Ольге, водителя пока нет — он боту не писал', chats == ['100', '200'], str(chats))
telegram_outbox.set_route(db, 'storage', ['100'])
db.commit()
chats = [r.chat_id for r in telegram_outbox.recipients(db, 'storage')]
check('свой выбор в программе остаётся, Ольга — вдобавок', chats == ['100', '200'], str(chats))
settings.set(STAFF_REPORTS_KEY, json.dumps({'storage': ['owner_rif']}))
chats = [r.chat_id for r in telegram_outbox.recipients(db, 'storage')]
check('одному чату — одно сообщение', chats == ['100'], str(chats))

print('\n=== Покраски никому из «Доступа» не отмечено ===')
check('только свои получатели', [r.chat_id for r in telegram_outbox.recipients(db, 'paint')] == ['100'])

db.close()
finish()
