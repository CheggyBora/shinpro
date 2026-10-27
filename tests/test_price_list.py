"""
Прайс-лист: добавить услугу и товар, переименовать, скрыть, свойства
сразу у всех типов машин (решение владельца 28.10.2026).
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('price_list')

import json

from config import init_db, SessionLocal
from models import Service
from models.employee_role import EmployeeRole
from services.settings_service import SettingsService
from services.price_list_service import (
    PriceListService, PriceError, merge_duplicates, FLAT, EDITABLE, BY_RADIUS)
from services.service_layout import save_layout, build_columns
from services.wheel_service import WheelSettings

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()
prices = PriceListService(db)


def raises(action):
    try:
        action()
    except PriceError as error:
        return str(error)
    return None


print('=== + Услуга по радиусам ===')
rows = prices.add_service('Чистка ступицы', mode=BY_RADIUS,
                          prices={'car': {13: 150, 16: 200}}, minutes=15, is_extra=True)
check('джип и кат. С не трогали — одна строка «для любых»',
      len(rows) == 1 and rows[0].vehicle_type == 'all', str([r.vehicle_type for r in rows]))
check('цены и свойства записаны', rows[0].price_r16 == 200 and rows[0].duration_minutes == 15
      and rows[0].is_extra and rows[0].direction == 'tire')

rows = prices.add_service('Перебортовка низкого профиля', mode=BY_RADIUS,
                          prices={'car': {17: 600, 18: 700}, 'truck': {17: 1500}},
                          is_extra=False, minutes=30)
check('есть своя цена у кат. С — три строки', [r.vehicle_type for r in rows] == ['car', 'suv', 'truck'])
check('у джипа — как у легкового', rows[1].price_r18 == 700)
check('у кат. С своя на R17, остальное — как у легкового',
      rows[2].price_r17 == 1500 and rows[2].price_r18 == 700)
check('пустая таблица цен — ошибка', raises(lambda: prices.add_service('Пусто', prices={})))
check('такое имя уже есть — ошибка',
      'уже есть' in (raises(lambda: prices.add_service('Чистка ступицы', mode=FLAT,
                                                       flat_price=100)) or ''))

flat = prices.add_service('Азот в колёса', mode=FLAT, flat_price=200)[0]
check('одна цена — flat_price, строка для любых', flat.flat_price == 200 and flat.vehicle_type == 'all')
editable = prices.add_service('Слесарка разная', mode=EDITABLE)[0]
check('«вводят в наряде» — editable_price', editable.editable_price is True)

print('\n=== + Товар ===')
goods = prices.add_goods('Вентиль металлический', '250', '90')
check('товар: одна цена, закупка, не работа',
      goods.is_goods and goods.flat_price == 250 and goods.purchase_price == 90)
check('цена продажи обязательна', raises(lambda: prices.add_goods('Грузик', '', None)))

print('\n=== Кнопка наряда появляется сама ===')
names = list(dict.fromkeys(s.name for s in db.query(Service).filter(Service.is_active.isnot(False))))
placed = {n for column in build_columns(db, names) for n in column}
check('новые позиции есть в раскладке кнопок',
      {'Чистка ступицы', 'Вентиль металлический', 'Азот в колёса'} <= placed)

print('\n=== Переименовать ===')
save_layout(db, [['Чистка ступицы', 'Азот в колёса'], [], [], []])
WheelSettings(db).set_names(['Чистка ступицы'])
role = EmployeeRole(title='Ученик')
role.set_excluded(['Чистка ступицы'])
db.add(role)
db.commit()
prices.rename('Чистка ступицы', 'Чистка ступицы и диска')
check('строки переименованы', prices.exists('Чистка ступицы и диска', 'tire')
      and not prices.exists('Чистка ступицы', 'tire'))
layout = json.loads(SettingsService(db).get('service_button_layout'))
check('место кнопки сохранилось', layout[0][0] == 'Чистка ступицы и диска', str(layout))
check('вопрос про колесо — по новому имени', 'Чистка ступицы и диска' in WheelSettings(db).names())
db.refresh(role)
check('категория мастера — по новому имени', 'Чистка ступицы и диска' in role.excluded)
check('переименовать в занятое имя нельзя',
      raises(lambda: prices.rename('Азот в колёса', 'Вентиль металлический')))

print('\n=== Скрыть и вернуть ===')
check('скрыли все строки позиции', prices.hide('Перебортовка низкого профиля') == 3)
check('в списке скрытых', 'Перебортовка низкого профиля' in prices.hidden())
check('с тем же именем новую не завести — подсказка вернуть',
      'Скрытые' in (raises(lambda: prices.add_service('Перебортовка низкого профиля',
                                                      mode=FLAT, flat_price=1)) or ''))
check('вернули', prices.restore('Перебортовка низкого профиля') == 3
      and 'Перебортовка низкого профиля' not in prices.hidden())

print('\n=== Свойства — сразу у всех типов ===')
rows = prices.rows('Перебортовка низкого профиля', 'tire')
changed = prices.set_values(rows, 'duration_minutes', 40)
check('время у всех трёх одним действием',
      len(changed) == 3 and {r.duration_minutes for r in rows} == {40})
prices.set_values(rows, 'duration_minutes', {rows[0].id: 30, rows[1].id: 35, rows[2].id: 60})
check('«разное» — по типам', [r.duration_minutes for r in rows] == [30, 35, 60])
prices.set_values(rows, 'cost', 25)
check('себестоимость работы — расходник', {r.consumable_cost for r in rows} == {25})
prices.set_values([goods], 'cost', 95)
check('себестоимость товара — закупка', goods.purchase_price == 95)
groups = {name: rows for _d, name, rows in prices.groups('tire')}
check('в свойствах одна строка на позицию', len(groups['Перебортовка низкого профиля']) == 3)

print('\n=== Второй «Шиномонтаж» у легкового ===')
main = Service(name='Шиномонтаж Т', vehicle_type='car', price_r13=300, price_r14=300,
               price_r15=350, price_r16=400, is_active=True)
stray = Service(name='Шиномонтаж Т', vehicle_type='car', price_r16=1000, is_active=True)
db.add_all([main, stray])
db.commit()
hidden = merge_duplicates(db)
db.commit()
check('скрыта строка, где цен меньше', stray in hidden and main not in hidden
      and stray.is_active is False and main.is_active)
check('разные типы машин дублями не считаются', all(r.is_active for r in rows))

db.close()
finish()
