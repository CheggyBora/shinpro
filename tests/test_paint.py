"""
Калькулятор покраски дисков.

Считает он просто, но ошибиться есть где: дополнения бывают за колесо
и за заказ, и спутать их — значит назвать клиенту цену суппортов,
умноженную на четыре.

Главное, что проверяем:

  · базовая цена зависит от размера и берётся из настроек;
  · «за колесо» умножается на число колёс, «за заказ» — нет;
  · снятое с показа дополнение в счёт не попадает;
  · счёт расписан строками, а не одним числом;
  · цех и кабинет считают одним кодом — значит, одинаково.
"""
import sys

import _setup  # noqa: F401
from _setup import use_temp_db, check, finish

use_temp_db('paint')

from config import init_db, SessionLocal
from services.paint_service import PaintService

init_db()
db = SessionLocal()
service = PaintService(db)

print('=== Дополнения заводятся при первом запуске ===')
options = service.options()
check('список не пуст', len(options) >= 6, str(len(options)))
check('есть проточка',
      any('проточка' in row.name.lower() for row in options),
      str([row.name for row in options]))
check('повторный запуск ничего не добавляет',
      service.ensure_defaults() == 0)

by_name = {row.name: row for row in options}
turning = by_name['Алмазная проточка']
calipers = by_name['Покраска суппортов']

check('проточка считается за колесо', turning.per_wheel is True)
check('суппорты — за заказ', calipers.per_wheel is False)

print('\n=== Базовая цена зависит от размера ===')
small = service.base_price(13)
big = service.base_price(22)
check('большой диск дороже', big > small, f'R13 {small}, R22 {big}')
check('неизвестный размер не выдумывается',
      service.base_price(31) == 0.0, str(service.base_price(31)))
check('размер понимается и с буквой',
      service.base_price('R17') == service.base_price(17))

print('\n=== Цену можно поменять, и она запоминается ===')
service.set_base_price(17, 4200)
check('новая цена встала', service.base_price(17) == 4200.0,
      str(service.base_price(17)))

print('\n=== Голый счёт: только базовая покраска ===')
quote = service.quote(17, wheels=4)
check('одна строка', len(quote['lines']) == 1, str(len(quote['lines'])))
check('умножено на четыре колеса', quote['total'] == 4200 * 4,
      str(quote['total']))

print('\n=== Дополнение за колесо умножается ===')
quote = service.quote(17, wheels=4, option_ids=[turning.id])
check('строк стало две', len(quote['lines']) == 2, str(len(quote['lines'])))
check('проточка умножена на колёса',
      quote['total'] == 4200 * 4 + turning.price * 4, str(quote['total']))

print('\n=== Дополнение за заказ не умножается ===')
quote = service.quote(17, wheels=4, option_ids=[calipers.id])
line = [row for row in quote['lines'] if row.get('id') == calipers.id][0]
check('количество равно одному', line['quantity'] == 1, str(line['quantity']))
check('в счёт попала цена как есть', line['total'] == calipers.price,
      str(line['total']))
check('итог сложился верно', quote['total'] == 4200 * 4 + calipers.price,
      str(quote['total']))

print('\n=== Одно колесо вместо комплекта ===')
quote = service.quote(17, wheels=1, option_ids=[turning.id, calipers.id])
check('база за одно колесо',
      quote['lines'][0]['total'] == 4200, str(quote['lines'][0]['total']))
check('итог: база + проточка + суппорты',
      quote['total'] == 4200 + turning.price + calipers.price,
      str(quote['total']))

print('\n=== Меньше одного колеса не бывает ===')
check('ноль колёс считается как одно',
      service.quote(17, wheels=0)['wheels'] == 1,
      str(service.quote(17, wheels=0)['wheels']))

print('\n=== Снятое с показа дополнение в счёт не идёт ===')
service.save_option(turning.id, is_active=False)
quote = service.quote(17, wheels=4, option_ids=[turning.id])
check('строка одна, проточки нет', len(quote['lines']) == 1,
      str([row['name'] for row in quote['lines']]))
check('и в итоге её нет', quote['total'] == 4200 * 4, str(quote['total']))

check('но из списка настроек не пропала',
      any(row.id == turning.id
          for row in service.options(only_active=False)))
service.save_option(turning.id, is_active=True)

print('\n=== Счёт расписан строками ===')
quote = service.quote(17, wheels=4, option_ids=[turning.id, calipers.id])
check('три строки', len(quote['lines']) == 3, str(len(quote['lines'])))
check('сумма строк равна итогу',
      abs(sum(row['total'] for row in quote['lines']) - quote['total']) < 0.01,
      str(quote['total']))
check('в первой строке виден размер',
      'R17' in quote['lines'][0]['name'], quote['lines'][0]['name'])

print('\n=== Для кабинета уезжает тот же состав ===')
config = service.config()
check('размеры на месте', len(config['sizes']) == 12, str(len(config['sizes'])))
check('цена R17 совпадает с расчётом',
      [row for row in config['sizes'] if row['diameter'] == 17][0]['price']
      == service.base_price(17))
check('дополнения перечислены', len(config['options']) == len(service.options()),
      f"{len(config['options'])} против {len(service.options())}")
check('у дополнения сказано, как считается',
      all('per_wheel' in row for row in config['options']))
check('снятые с показа не уезжают',
      all(row['id'] != 0 for row in config['options']))

db.close()
finish()
