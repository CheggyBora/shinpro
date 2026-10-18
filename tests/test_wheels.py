"""
Выбор колеса для ремонта и правки.

Пробили «Ремонт жгутом» — открывается схема машины, приёмщик отмечает
колёса. Проверяем:

  · сколько колёс отмечено, столько выполнений в наряде;
  · повтор услуги дописывает колёса, два жгута в одно колесо — «ПЛ×2»;
  · «Пропустить» — услуга без колеса, «Отмена» — услуги нет;
  · у услуг не из списка схема не открывается, выключили — ни у кого;
  · колёса видны в строке наряда и в истории;
  · список услуг правится в настройках, добавляется из прайса.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('wheels')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Service, WorkOrderItem
from services import OrderService, EmployeeService
from services.shift_service import ShiftService
from services.wheel_service import (WheelSettings, DEFAULT_SERVICES, describe,
                                    item_title, wheels_for)

init_db()
initialize_data()
db = SessionLocal()
ShiftService(db).open_shift(open_posts=2)
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)

settings = WheelSettings(db)
orders = OrderService(db)


def service(name, vehicle='car'):
    # Ремонт и правка в прайсе общие для всех типов машин
    from sqlalchemy import or_
    return db.query(Service).filter(
        Service.name == name,
        or_(Service.vehicle_type == vehicle,
            Service.vehicle_type == 'all')).first()


print('=== Услуги по умолчанию ===')
check('ремонт и правка в списке', settings.names() == DEFAULT_SERVICES,
      str(settings.names()))
for name in DEFAULT_SERVICES:
    check(f'«{name}» есть в прайсе', service(name) is not None)
check('шиномонтаж колесо не спрашивает', not settings.asks('Шиномонтаж'))
check('ремонт жгутом спрашивает', settings.asks('Ремонт жгутом'))

print()
print('=== Схема: колёса по типу машины ===')
car = [code for code, _ in wheels_for('car')]
truck = [code for code, _ in wheels_for('truck')]
check('у легковой 4 колеса и запаска', car == ['ПЛ', 'ПП', 'ЗЛ', 'ЗП', 'Зап'],
      str(car))
check('у грузовой сзади по два', truck == ['ПЛ', 'ПП', 'ЗЛн', 'ЗЛв', 'ЗПв',
                                          'ЗПн', 'Зап'], str(truck))

print()
print('=== В наряд с колёсами ===')
order = orders.create_order('А123ВВ777', 'R16', 'car', create_client=False)
repair = service('Ремонт жгутом')
item = orders.add_service_to_order(order.id, repair.id, wheels=['ПЛ', 'ЗП'])
check('два колеса — два ремонта', item.quantity == 2, str(item.quantity))
check('колёса записаны', item.wheels == 'ПЛ,ЗП', str(item.wheels))
check('в названии — колёса', item_title(item) == 'Ремонт жгутом (ПЛ, ЗП)',
      item_title(item))

item = orders.add_service_to_order(order.id, repair.id, wheels=['ПЛ'])
check('повтор дописал в ту же строку', item.quantity == 3, str(item.quantity))
check('второй жгут в то же колесо — ПЛ×2', describe(item.wheels) == 'ПЛ×2, ЗП',
      describe(item.wheels))

item = orders.add_service_to_order(order.id, repair.id, wheels=[])
check('пропустили колесо — просто +1', item.quantity == 4, str(item.quantity))
check('колёса не тронуты', item.wheels == 'ПЛ,ЗП,ПЛ', str(item.wheels))

print()
print('=== Ошиблись колесом — отметили заново ===')
orders.set_item_wheels(item.id, ['ПП'])
db.refresh(item)
check('теперь одно колесо', item.wheels == 'ПП' and item.quantity == 1,
      f'{item.wheels} {item.quantity}')
orders.set_item_wheels(item.id, [])
db.refresh(item)
check('«не знаем» — отметки сняли', item.wheels is None)
check('количество осталось', item.quantity == 1, str(item.quantity))
check('без колёс — просто название', item_title(item) == 'Ремонт жгутом')

print()
print('=== Обычная услуга — как раньше ===')
plain = orders.add_service_to_order(order.id, service('Шиномонтаж').id)
check('без колёс', plain.wheels is None and plain.quantity == 1)

print()
print('=== Настройка ===')
settings.remove('Ремонт грибком')
check('убрали грибок', not settings.asks('Ремонт грибком'))
settings.add('Шиномонтаж')
check('добавили шиномонтаж', settings.asks('Шиномонтаж'))
settings.set_names([])
check('пустой список — пустой, а не «по умолчанию»', settings.names() == [],
      str(settings.names()))
settings.set_names(DEFAULT_SERVICES)
settings.set_enabled(False)
check('выключили — никто не спрашивает', not settings.asks('Ремонт жгутом'))
check('а список сохранился', settings.names() == DEFAULT_SERVICES)
settings.set_enabled(True)
db.close()

print()
print('=== Экран наряда ===')
import tkinter as tk
import ui.orders_tab
import ui.wheel_picker as picker_module
import ui.wheel_services_editor as editor_module

_setup.silence_dialogs(ui.orders_tab, editor_module)
from ui import MainWindow

root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
tab = app.orders_tab
ui_db = tab.db

asked = []
answer = {'value': ['ПЛ']}


def fake_pick(parent, vehicle_type, service_name, initial=None, already=None):
    asked.append((vehicle_type, service_name, initial, already))
    return answer['value']


picker_module.pick_wheels = fake_pick

jeep = OrderService(ui_db).create_order('К900ОР99', 'R17', 'suv',
                                        create_client=False)
tab.open_order_tab(jeep)
root.update()
widget = tab.active_orders[jeep.id]


def lines():
    return [widget.items_tree.item(r)['values']
            for r in widget.items_tree.get_children()]


widget.add_service_by_name('Правка литого диска')
root.update()
check('схему спросили', len(asked) == 1, str(asked))
check('для джипа', asked[0][0] == 'suv', str(asked[0]))
check('в строке наряда колесо', lines()[0][0] == 'Правка литого диска (ПЛ)',
      str(lines()))

answer['value'] = None
widget.add_service_by_name('Ремонт жгутом')
root.update()
check('«Отмена» — услуги нет', len(lines()) == 1, str(lines()))

answer['value'] = []
widget.add_service_by_name('Ремонт жгутом')
root.update()
check('«Пропустить» — услуга без колеса',
      any(str(l[0]) == 'Ремонт жгутом' for l in lines()), str(lines()))

answer['value'] = ['ЗП']
widget.add_service_by_name('Правка литого диска')
root.update()
check('при повторе показали, что уже в наряде', asked[-1][3] == ['ПЛ'],
      str(asked[-1]))
check('дописали', lines()[0][0] == 'Правка литого диска (ПЛ, ЗП)', str(lines()))
check('и количество 2', str(lines()[0][1]) == '2', str(lines()[0]))

before = len(asked)
widget.add_service_by_name('Шиномонтаж')
root.update()
check('у шиномонтажа схема не открылась', len(asked) == before)

print()
print('=== Двойной клик по названию — переотметить ===')
first = widget.items_tree.get_children()[0]
answer['value'] = ['ПП']
widget.edit_wheels(first)
root.update()
check('открыли с уже отмеченными', asked[-1][2] == ['ПЛ', 'ЗП'], str(asked[-1]))
check('теперь ПП и одна правка', lines()[0][0] == 'Правка литого диска (ПП)'
      and str(lines()[0][1]) == '1', str(lines()[0]))

print()
print('=== Схема сама по себе ===')
real = picker_module.WheelPicker(root, 'truck', 'Правка литого диска')
check('без отметок «Готово» не нажать',
      'disabled' in real.done_button.state())
real.toggle('ЗЛн')
real.toggle('ПЛ')
real.confirm()
check('порядок — как на машине', real.result == ['ПЛ', 'ЗЛн'], str(real.result))
real = picker_module.WheelPicker(root, 'car', 'Ремонт жгутом')
real.skip()
check('«Пропустить» — пустой список', real.result == [])
real = picker_module.WheelPicker(root, 'car', 'Ремонт жгутом')
real.toggle('ПЛ')
real.cancel()
check('«Отмена» — ничего', real.result is None)

print()
print('=== Раздел настроек ===')
holder = tk.Toplevel(root)
editor = editor_module.WheelServicesEditor(holder, ui_db, holder)
shown = list(editor.listbox.get(0, 'end'))
check('список услуг показан', shown == DEFAULT_SERVICES, str(shown))
check('в «добавить» — только чего нет в списке',
      'Ремонт жгутом' not in editor.price_names()
      and 'Балансировка' in editor.price_names())
check('товаров среди них нет', 'Вентиль черный' not in editor.price_names()
      or not ui_db.query(Service).filter(Service.name == 'Вентиль черный',
                                         Service.is_goods.is_(True)).count())

dialog = editor.add()
names = list(dialog.listbox.get(0, 'end'))
dialog.listbox.selection_set(names.index('Балансировка'))
dialog.save()
check('добавили из прайса', 'Балансировка' in editor.listbox.get(0, 'end'))

editor.listbox.selection_clear(0, 'end')
editor.listbox.selection_set(list(editor.listbox.get(0, 'end')).index('Балансировка'))
editor.remove()
check('убрали', 'Балансировка' not in editor.listbox.get(0, 'end'))

editor.enabled_var.set(False)
editor.save_enabled()
check('выключатель сохраняется сразу', not WheelSettings(ui_db).enabled())

holder.destroy()
root.destroy()
finish()
