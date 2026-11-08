"""
Поиск «что помню» в нарядах и хранении (решение владельца 08.11.2026).

  · кусок номера в любом написании, последние цифры телефона, имя,
    номер наряда или комплекта, марка шин;
  · совпадения складываются;
  · «Выдать с хранения» в наряде — только у машины, у которой что-то
    лежит.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('search')
shown = _setup.silence_dialogs()

import tkinter as tk

from config import init_db, SessionLocal
from models import Service, TireStorage, WorkOrder
from services import OrderService, SalaryService, EmployeeService, search_service
from services.shift_service import ShiftService
from services.tire_storage_service import TireStorageService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
ShiftService(db).open_shift(cash_start='0')
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)

orders = OrderService(db)


def paid(plate, name=None, phone=None):
    order = orders.create_order(plate, 'R16', 'car', client_name=name, client_phone=phone,
                                create_client=bool(name or phone))
    orders.add_service_to_order(order.id, 1)
    SalaryService(db).process_payment(order.id, 'cash', orders.calculate_total(order.id))
    return order


first = paid('А123ВВ777', 'Андрей Петров', '+7 909 901-89-31')
second = paid('Е555КХ199', 'Мария', '+7 916 000-12-12')
third = paid('Х123ХХ50')

print('=== Поиск ===')
found = search_service.find(db, '123')
check('кусок номера — обе машины с 123', found['car_ids'] == {first.car_id, third.car_id},
      str(found))
check('латиницей и строчными', search_service.find(db, 'a123bb')['car_ids'] == {first.car_id})
check('последние цифры телефона', search_service.find(db, '8931')['client_ids'] == {first.client_id})
check('имя без учёта регистра', search_service.find(db, 'андр')['client_ids'] == {first.client_id})
check('номер наряда', search_service.find(db, f'№{second.id}')['number'] == second.id)
check('пусто — пусто', search_service.find(db, ' ')['car_ids'] == set())

print('\n=== Наряды ===')
root = tk.Tk()
root.geometry('+-3000+0')
import styles
styles.apply_modern_styles(root)
from ui.history_tab import HistoryTab
holder = tk.Frame(root)
tab = HistoryTab(holder, db)


def shown_ids():
    return {int(tab.history_tree.item(i)['tags'][0]) for i in tab.history_tree.get_children()}


for text, expected, name in (('123', {first.id, third.id}, 'кусок номера'),
                             ('андрей', {first.id}, 'имя'),
                             ('1212', {second.id}, 'телефон'),
                             (str(second.id), {second.id}, 'номер наряда')):
    tab.license_entry.delete(0, 'end')
    tab.license_entry.insert(0, text)
    tab.search_history()
    check(f'наряды: {name}', expected <= shown_ids(), f'{text}: {shown_ids()}')
tab.license_entry.delete(0, 'end')
tab.license_entry.insert(0, 'нетакого')
shown.clear()
tab.search_history()
check('ничего — так и сказано', shown and 'ничего не найдено' in shown[-1][2])

print('\n=== Хранение ===')
storage = TireStorageService(db)
for plate, name, phone, brand in (('А123ВВ777', 'Андрей Петров', '+79099018931', 'Nokian'),
                                  ('Е555КХ199', None, None, 'Michelin')):
    db.add(TireStorage(car_number=plate, client_name=name, client_phone=phone,
                       storage_type='Шины', diameter='R16', brand=brand, price=1000,
                       status='stored'))
db.commit()
sets = {row.car_number: row for row in db.query(TireStorage).all()}


def plates(text):
    return {row.car_number for row in storage.search(text)}


check('хранение: кусок номера', plates('a123') == {'А123ВВ777'})
check('хранение: телефон', plates('8931') == {'А123ВВ777'})
check('хранение: имя', plates('петров') == {'А123ВВ777'})
check('хранение: марка без учёта регистра', plates('мишлен') == set() and plates('michel') == {'Е555КХ199'})
check('хранение: по клиенту наряда', plates('мария') == {'Е555КХ199'})
check('хранение: № комплекта', plates(f'№{sets["Е555КХ199"].id}') >= {'Е555КХ199'})
check('хранение: пусто — все', len(storage.search('')) == 2)

print('\n=== «Выдать с хранения» в наряде ===')
from ui.order_screen import blocks


class FakeMenu:
    items = []

    def __init__(self, *a, **k):
        FakeMenu.items = []

    def add_command(self, label=None, **k):
        FakeMenu.items.append(label)

    def add_separator(self):
        pass

    def tk_popup(self, *a):
        pass

    def grab_release(self):
        pass


blocks.tk.Menu = FakeMenu
from ui.order_screen.widget import OrderWidget  # noqa: E402


def menu_for(order):
    widget = OrderWidget.__new__(OrderWidget)
    widget.db, widget.order, widget.frame = db, order, holder
    widget.more_button = tk.Button(holder)
    widget.ready_button = tk.Button(holder)
    widget.show_more_menu()
    return FakeMenu.items


fresh = orders.create_order('Т100ТТ77', 'R16', 'car', create_client=False)
check('машина без комплектов — пунктов выдачи нет',
      not any('Выдать' in i or 'Заказать со склада' in i for i in menu_for(fresh)), str(FakeMenu.items))
with_set = orders.create_order('А123ВВ777', 'R16', 'car', create_client=False)
check('с комплектом — «Выдать с хранения №…»',
      any(i.startswith('Выдать с хранения  №') for i in menu_for(with_set)), str(FakeMenu.items))
root.destroy()
db.close()
finish()
