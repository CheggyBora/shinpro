"""
Бот организации на сервере — сторона программы (решение 13.11.2026).

  · сервер прислал бота — программа берёт его токен, людей из его списка
    (новые — выключенными, как раньше) и телеграм сама не опрашивает;
  · токен в настройках поменять нельзя — он с сервера;
  · сервер прислал пусто — программа снова сама по себе.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('org_bot')

from config import init_db, SessionLocal
from services.sync_service import SyncService
from services.telegram_service import TelegramService, Recipient

init_db()
db = SessionLocal()
telegram = TelegramService(db)
telegram.save_token('old-token')
telegram.save_recipients([Recipient('111', 'Сергей', enabled=True, username='serg_svarka')])

asked = []
real_call = TelegramService._call


def fake_call(self, method, fields, files=None):
    asked.append(method)
    if method == 'getUpdates':
        raise AssertionError('бот на сервере — телеграм не спрашиваем')
    return {}


TelegramService._call = fake_call

print('=== Сервер прислал бота ===')
SyncService(db)._adopt_org_bot({'org_bot': {'username': 'rif_shop_bot', 'token': 'org-token'},
                                'telegram_people': [
                                    {'chat_id': '111', 'username': 'serg_svarka', 'name': 'Сергей Петров'},
                                    {'chat_id': '222', 'username': '', 'name': 'Ольга'}]})
telegram = TelegramService(db)
check('токен — с сервера', telegram.get_token() == 'org-token')
check('бот на сервере', telegram.org_bot() == 'rif_shop_bot')
people = {r.chat_id: r for r in telegram.get_recipients()}
check('новый человек появился выключенным', '222' in people and not people['222'].enabled)
check('старый остался включённым', people['111'].enabled)
check('телеграм сами не спрашивали', 'getUpdates' not in asked, str(asked))
added, seen = telegram.fetch_people()
check('«Обновить список» берёт список сервера', seen == 2 and added == 0, f'{added} {seen}')
telegram.save_token('hand-token')
check('токен руками не меняется', telegram.get_token() == 'org-token')

print('\n=== Бота с сервера убрали ===')
SyncService(db)._adopt_org_bot({'org_bot': {}, 'telegram_people': []})
telegram = TelegramService(db)
check('бот снова у программы', telegram.org_bot() == '')
telegram.save_token('hand-token')
check('токен снова меняется', telegram.get_token() == 'hand-token')

print('\n=== Старый сервер без бота в ответе ===')
SyncService(db)._adopt_org_bot({'staff_reports': {}})
check('ничего не трогаем', TelegramService(db).get_token() == 'hand-token')

TelegramService._call = real_call
db.close()
finish()
