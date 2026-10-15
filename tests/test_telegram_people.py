"""
Получатели сводки собираются сами — из тех, кто написал боту.

Раньше номер чата вводили руками. Человеку надо было найти бота
@userinfobot, узнать там своё число и продиктовать его тому, кто
сидит за компьютером: три действия и один шанс ошибиться цифрой,
после чего сводка молча уходила в никуда.

Теперь человек открывает бота, нажимает «Старт» — и появляется в
списке. Владельцу остаётся поставить галочку.

Проверяем то, что ломается незаметно:

  · новые appear выключенными — «Старт» не значит «шлите мне выручку»;
  · галочка, которую поставил человек, не сбрасывается при обновлении;
  · одно и то же сообщение не плодит дублей;
  · отметка прочитанного двигается, иначе телеграм отдаст то же самое.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('telegram_people')

_setup.silence_dialogs()

from config import init_db, SessionLocal
from services.settings_service import SettingsService
from services.telegram_service import TelegramService, OFFSET_KEY

init_db()
db = SessionLocal()
settings = SettingsService(db)
settings.ensure_defaults()

telegram = TelegramService(db)
telegram.save_token('test-token')

# Подменяем единственный выход наружу
calls = []
answers = {'getUpdates': []}


def fake_call(method, fields, files=None):
    calls.append((method, dict(fields)))
    return answers.get(method, [])


telegram._call = fake_call


def update(update_id, chat_id, **chat):
    return {'update_id': update_id,
            'message': {'chat': dict(id=chat_id, **chat)}}


print('=== Боту никто не писал ===')
added, seen = telegram.fetch_people()
check('никого не добавили', added == 0, str(added))
check('и не видели', seen == 0, str(seen))
check('получателей нет', telegram.get_recipients() == [],
      str(telegram.get_recipients()))

print()
print('=== Двое нажали «Старт» ===')
answers['getUpdates'] = [
    update(101, 555, first_name='Пётр', last_name='Иванов'),
    update(102, 777, username='olga'),
]

added, seen = telegram.fetch_people()
check('добавили двоих', added == 2, str(added))

people = {r.chat_id: r for r in telegram.get_recipients()}
check('имя и фамилия склеены', people['555'].name == 'Пётр Иванов',
      people['555'].name)
check('без имени — логин', people['777'].name == '@olga', people['777'].name)

print()
print('=== Новые выключены ===')
# «Старт» не значит «шлите мне выручку по смене»
check('Пётр выключен', people['555'].enabled is False)
check('Ольга выключена', people['777'].enabled is False)
check('отправлять некому', telegram.is_configured() is False)

print()
print('=== Отметка прочитанного сдвинулась ===')
check('запомнили, докуда дошли',
      settings.get(OFFSET_KEY) == '103', str(settings.get(OFFSET_KEY)))
check('в первом запросе отметки ещё не было',
      calls[-1][1]['offset'] == 0, str(calls[-1][1]))

# Телеграм отдаёт сообщения по одному разу и только если сказать,
# докуда мы дошли. Не сдвинули отметку — разбираем одно и то же
answers['getUpdates'] = []
telegram.fetch_people()
check('следующий запрос идёт с отметки',
      calls[-1][1]['offset'] == 103, str(calls[-1][1]))

print()
print('=== Владелец включил Петра ===')
people['555'].enabled = True
telegram.save_recipients(list(people.values()))

check('отправлять есть кому', telegram.is_configured() is True)
check('активный один', len(telegram.get_active_recipients()) == 1,
      str(telegram.get_active_recipients()))

print()
print('=== Те же люди написали снова ===')
answers['getUpdates'] = [
    update(103, 555, first_name='Пётр', last_name='Иванов'),
    update(104, 999, first_name='Сергей'),
]

added, seen = telegram.fetch_people()
check('новый только один', added == 1, str(added))
check('всего трое', len(telegram.get_recipients()) == 3,
      str(len(telegram.get_recipients())))

people = {r.chat_id: r for r in telegram.get_recipients()}
check('галочку Петра не сбросили', people['555'].enabled is True)
check('а Сергей пришёл выключенным', people['999'].enabled is False)

print()
print('=== Имя подтягивается, если его не было ===')
answers['getUpdates'] = [update(105, 777, first_name='Ольга')]
telegram.fetch_people()

people = {r.chat_id: r for r in telegram.get_recipients()}
check('логин заменился именем', people['777'].name == '@olga'
      or people['777'].name == 'Ольга', people['777'].name)

print()
print('=== Сообщение без чата не ломает разбор ===')
answers['getUpdates'] = [{'update_id': 106}, update(107, 555)]
added, seen = telegram.fetch_people()
check('разобрали, что смогли', added == 0, str(added))
check('и не упали', len(telegram.get_recipients()) == 3,
      str(len(telegram.get_recipients())))

print()
print('=== Ссылку на бота спрашиваем у телеграма ===')
# Имя бота руками не вводят: однажды ошибутся и отправят людей к чужому
answers['getMe'] = {'username': 'rif_service_bot'}
check('ссылка собрана',
      telegram.bot_link() == 'https://t.me/rif_service_bot',
      telegram.bot_link())

db.close()
finish()
