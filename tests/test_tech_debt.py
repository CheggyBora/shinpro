"""
Реквизиты, кнопки услуг, журнал работы и получатели Telegram.

Всё это раньше было вписано в код: чтобы поменять телефон в чеке или
добавить кнопку услуги, программу приходилось пересобирать.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('tech_debt')

import json
import os
import tempfile

from config import init_db, SessionLocal
from models import Service
from services import TelegramService, TelegramError, Recipient
from services.settings_service import SettingsService
from services.company_service import get_company, COMPANY_DEFAULTS, CompanyInfo
from services.service_layout import (build_columns, save_layout, reset_layout,
                                     DEFAULT_LAYOUT, COLUMN_COUNT, LAYOUT_KEY)

init_db()
db = SessionLocal()
settings = SettingsService(db)
settings.ensure_defaults()

print('=== Реквизиты заводятся со значениями по умолчанию ===')
check('реквизиты попали в настройки',
      settings.get('company_inn') == COMPANY_DEFAULTS['company_inn'],
      settings.get('company_inn'))

company = get_company(db)
check('название читается', company.name == 'Шиномонтаж «РИФ»', company.name)
check('ИНН попадает в шапку', 'ИНН 770208926387' in company.header_lines())
check('телефон попадает в шапку',
      any('Телефон' in line for line in company.header_lines()))

print('\n=== Длинный адрес разбивается на две строки ===')
lines = company.header_lines()
check('адрес не одной длинной строкой', '115280, г. Москва,' in lines, str(lines))
check('вторая часть адреса на месте',
      'ул. Автозаводская, д. 24 стр. 1' in lines, str(lines))

short = CompanyInfo({'company_address': 'г. Тула, ул. Мира, 1'})
check('короткий адрес не режем',
      'г. Тула, ул. Мира, 1' in short.header_lines())

no_comma = CompanyInfo({'company_address': 'очень длинный адрес без запятых совсем нигде'})
check('адрес без запятых остаётся одной строкой',
      'очень длинный адрес без запятых совсем нигде' in no_comma.header_lines())

print('\n=== Реквизиты меняются без пересборки ===')
settings.set('company_name', 'Шиномонтаж «Колесо»')
settings.set('company_inn', '123456789012')
settings.set('company_phone', '+7 495 000-11-22')
changed = get_company(db)
check('название сменилось', changed.name == 'Шиномонтаж «Колесо»', changed.name)
check('ИНН сменился', 'ИНН 123456789012' in changed.header_lines())

print('\n=== Пустое поле не печатается ===')
settings.set('company_email', '')
settings.set('company_slogan', '')
empty = get_company(db)
check('пустая почта пропала из шапки',
      not any('email' in line for line in empty.header_lines()),
      str(empty.header_lines()))
check('пустой подзаголовок остаётся пустым', empty.slogan == '')
check('заполненные поля на месте', 'ИНН 123456789012' in empty.header_lines())

print('\n=== Чек печатается с новыми реквизитами ===')
from services import PrintService, OrderService, SalaryService, EmployeeService
from services.shift_service import ShiftService

ShiftService(db).open_shift(open_posts=1)
employees = EmployeeService(db)
employees.register_employee(1)
employees.start_shift(1)

db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=1000.0))
db.add(Service(name='Балансировка', vehicle_type='car', price_r16=500.0))
db.commit()

orders = OrderService(db)
order = orders.create_order('А111АА777', 'R16', 'car', client_name='Пётр')
orders.add_service_to_order(order.id, db.query(Service).first().id)
SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))

printer = PrintService(db)
printer.receipts_dir = os.path.join(tempfile.gettempdir(), 'tire_shop_tech_debt')
os.makedirs(printer.receipts_dir, exist_ok=True)

items = orders.get_order_items(order.id)
total = orders.calculate_total(order.id)
receipt = printer.generate_receipt(order, items, total)
check('чек A4 создан', os.path.exists(receipt), receipt)
check('реквизиты взяты из настроек',
      printer.company().name == 'Шиномонтаж «Колесо»', printer.company().name)

print('\n=== База недоступна — печатаем с исходными реквизитами ===')


class BrokenSession:
    def query(self, *args, **kwargs):
        raise RuntimeError('база недоступна')


fallback = get_company(BrokenSession())
check('печать не падает без базы', fallback.name == COMPANY_DEFAULTS['company_name'],
      fallback.name)

# --------------------------------------------------------------------
print('\n=== Кнопки услуг строятся из прайс-листа ===')

names = ['Шиномонтаж', 'Балансировка']
columns = build_columns(db, names)
check('колонок ровно четыре', len(columns) == COLUMN_COUNT, str(len(columns)))
check('услуга из прайса получила место',
      'Шиномонтаж' in columns[0], str(columns[0]))
check('услуг не больше, чем в прайсе',
      sum(len(c) for c in columns) == len(names),
      str(sum(len(c) for c in columns)))

print('\n=== Новая услуга получает кнопку сама ===')
db.add(Service(name='Ремонт бескамерки', vehicle_type='car', price_r16=700.0))
db.commit()
columns = build_columns(db, names + ['Ремонт бескамерки'])
placed = [name for column in columns for name in column]
check('новая услуга появилась среди кнопок', 'Ремонт бескамерки' in placed,
      str(placed))

print('\n=== Новая услуга уходит в самую короткую колонку ===')
columns = build_columns(db, ['Шиномонтаж', 'Балансировка', 'Совсем новая'])
where = [i for i, column in enumerate(columns) if 'Совсем новая' in column][0]
check('не свалилась в первую колонку вместе с остальными', where != 0, str(where))

print('\n=== Услуга, убранная из прайса, теряет кнопку ===')
columns = build_columns(db, ['Балансировка'])
placed = [name for column in columns for name in column]
check('удалённой услуги нет среди кнопок', 'Шиномонтаж' not in placed, str(placed))

print('\n=== Свой порядок сохраняется и возвращается ===')
save_layout(db, [['Балансировка'], ['Шиномонтаж'], [], []])
columns = build_columns(db, ['Шиномонтаж', 'Балансировка'])
check('первая колонка — как задали', columns[0] == ['Балансировка'], str(columns[0]))
check('вторая колонка — как задали', columns[1] == ['Шиномонтаж'], str(columns[1]))

print('\n=== Сброс возвращает порядок по умолчанию ===')
reset_layout(db)
columns = build_columns(db, ['Шиномонтаж', 'Балансировка'])
check('вернулись к раскладке по умолчанию',
      columns[0] == ['Шиномонтаж', 'Балансировка'], str(columns[0]))
check('услуги идут в порядке по умолчанию',
      DEFAULT_LAYOUT[0].index('Шиномонтаж') < DEFAULT_LAYOUT[0].index('Балансировка'))

print('\n=== Испорченная раскладка не ломает наряды ===')
settings.set(LAYOUT_KEY, 'это не json')
columns = build_columns(db, ['Шиномонтаж', 'Балансировка'])
check('кнопки всё равно построились', 'Шиномонтаж' in columns[0], str(columns[0]))
settings.set(LAYOUT_KEY, json.dumps({'не': 'список'}))
columns = build_columns(db, ['Шиномонтаж'])
check('чужая структура не ломает', 'Шиномонтаж' in columns[0], str(columns[0]))
reset_layout(db)

# --------------------------------------------------------------------
print('\n=== Получатели Telegram ===')
telegram = TelegramService(db)
check('пока получателей нет', telegram.get_recipients() == [])
check('и отправка не настроена', telegram.is_configured() is False)

print('\n=== Старая настройка с одним чатом продолжает работать ===')
settings.set('telegram_bot_token', '123:ABC')
settings.set('telegram_chat_id', '-100500')
legacy = telegram.get_recipients()
check('старый чат виден как получатель', len(legacy) == 1, str(len(legacy)))
check('номер чата тот же', legacy[0].chat_id == '-100500', legacy[0].chat_id)
check('считается настроенным', telegram.is_configured() is True)

print('\n=== Несколько получателей ===')
telegram.save_recipients([
    Recipient('-100500', 'Владелец'),
    Recipient('-100600', 'Бухгалтер'),
    Recipient('-100700', 'Управляющий', enabled=False),
])
recipients = telegram.get_recipients()
check('сохранились все трое', len(recipients) == 3, str(len(recipients)))
check('имена сохранились', recipients[1].name == 'Бухгалтер', recipients[1].name)
check('выключенный не в рассылке', len(telegram.get_active_recipients()) == 2,
      str(len(telegram.get_active_recipients())))
check('одиночный чат синхронизирован с первым включённым',
      settings.get('telegram_chat_id') == '-100500',
      settings.get('telegram_chat_id'))

print('\n=== Сбой у одного не срывает отправку остальным ===')
sent = []


def fake_call(method, fields, files=None):
    chat = fields.get('chat_id')
    if chat == '-100600':
        raise TelegramError('бот заблокирован пользователем')
    sent.append((method, chat))
    return {'ok': True}


telegram._call = fake_call
result = telegram.send_message('сводка по смене')
check('владелец получил', ('sendMessage', '-100500') in sent, str(sent))
check('бухгалтеру не дошло', len(result.failed) == 1, str(result.failed))
check('доставлен один', len(result.delivered) == 1, str(len(result.delivered)))
check('в итоге видно, кому не дошло', 'Бухгалтер' in result.summary(),
      result.summary())
check('но отправка не считается полностью успешной',
      result.all_delivered is False)

print('\n=== Выключенному получателю не отправляем ===')
check('выключенный не получил сообщение',
      all(chat != '-100700' for _, chat in sent), str(sent))

print('\n=== Не дошло никому — это уже ошибка ===')


def all_fail(method, fields, files=None):
    raise TelegramError('нет связи')


telegram._call = all_fail
failed_all = False
try:
    telegram.send_message('сводка')
except TelegramError:
    failed_all = True
check('поднялась ошибка', failed_all)

print('\n=== Без получателей отправка не начинается ===')
telegram.save_recipients([])
check('список пуст', telegram.get_recipients() == [])
check('и не настроено', telegram.is_configured() is False)

no_recipients = False
try:
    telegram.send_message('сводка')
except TelegramError as e:
    no_recipients = 'не настроен' in str(e)
check('сказано, что не настроено', no_recipients)

# --------------------------------------------------------------------
print('\n=== Журнал работы ===')
import logging
from logger import log, get_log_path, get_logs_dir, cleanup_old_logs, LOG_FILE_NAME

log.info('проверка записи в журнал')
for handler in log.handlers:
    handler.flush()

path = get_log_path()
check('файл журнала создан', os.path.exists(path), path)

content = open(path, encoding='utf-8').read()
check('запись попала в файл', 'проверка записи в журнал' in content)
check('в записи есть время и уровень', 'INFO' in content)

log.debug('пошаговая отладка не нужна в журнале')
for handler in log.handlers:
    handler.flush()
content = open(path, encoding='utf-8').read()
check('отладочные записи не засоряют журнал',
      'пошаговая отладка' not in content)

log.error('пример ошибки')
for handler in log.handlers:
    handler.flush()
content = open(path, encoding='utf-8').read()
check('ошибка записана', 'пример ошибки' in content and 'ERROR' in content)

print('\n=== Журнал уходит в свою папку ===')
check('папка журнала отдельная от программы',
      get_logs_dir() != _setup.PROJECT_DIR, get_logs_dir())

print('\n=== Уборка старых файлов журнала ===')
old = os.path.join(get_logs_dir(), LOG_FILE_NAME + '.9')
open(old, 'w', encoding='utf-8').write('старое')
os.utime(old, (0, 0))
removed = cleanup_old_logs(days=1)
check('старый файл удалён', removed >= 1 and not os.path.exists(old), str(removed))
check('текущий журнал на месте', os.path.exists(path))

db.close()
finish()
