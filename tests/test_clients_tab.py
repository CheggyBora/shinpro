"""
Вкладка «Клиенты» и карточка клиента.

Карточка открывается из наряда и из вкладки, позволяет править имя,
телефон и данные автомобилей, добавлять и откреплять машины.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('clients_tab')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Service, Client, Car
from services import OrderService, SalaryService, EmployeeService, ClientService
from services.shift_service import ShiftService

init_db()
initialize_data()

db = SessionLocal()
ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

service = db.query(Service).filter(Service.name == 'Шиномонтаж').first()
order_service = OrderService(db)
order = order_service.create_order('А123ВВ777', 'R16', 'car',
                                   client_name='Андрей', client_phone='79099018931')
order_service.add_service_to_order(order.id, service.id)
SalaryService(db).process_payment(order.id, 'cash', order_service.calculate_total(order.id))
order_service.create_order('К900ОР99', 'R17', 'suv', client_phone='79099018931')
db.close()

import tkinter as tk
from tkinter import ttk
import ui.clients_tab
import ui.client_card
import ui.history_tab

popups = _setup.silence_dialogs(ui.clients_tab, ui.client_card, ui.history_tab)
from ui import MainWindow

root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()

clients_tab = app.clients_tab
client_service = ClientService(clients_tab.db)


def rows(tree):
    return [tree.item(r)['values'] for r in tree.get_children()]


print('=== Вкладка «Клиенты» на месте ===')
titles = app.nav.titles()
check('вкладка «Клиенты» есть', any('Клиенты' in t for t in titles), str(titles))
check('вкладки «История автомобиля» больше нет',
      not any('История автомобиля' in t for t in titles), str(titles))

sub_titles = clients_tab.nav.titles()
check('подвкладка поиска клиентов', any('Клиенты' in t for t in sub_titles), str(sub_titles))
check('подвкладка истории нарядов', any('История' in t for t in sub_titles), str(sub_titles))
check('удаление нарядов сохранилось',
      hasattr(app.history_tab, 'delete_selected_order'))

print('\n=== Список клиентов ===')
clients_tab.show_all()
root.update()
check('клиент показан', len(rows(clients_tab.tree)) == 1, str(rows(clients_tab.tree)))
row = rows(clients_tab.tree)[0]
check('имя в списке', row[0] == 'Андрей', str(row))
check('телефон отформатирован', row[1] == '+7 (909) 901-89-31', str(row))
check('обе машины перечислены',
      'А123ВВ777' in str(row[2]) and 'К900ОР99' in str(row[2]), str(row))
check('визиты посчитаны', row[3] == 1, str(row))

print('\n=== Поиск ===')
for query, title in [('8931', 'по цифрам телефона'), ('андрей', 'по имени'),
                     ('k900op99', 'по госномеру латиницей')]:
    clients_tab.query_entry.delete(0, tk.END)
    clients_tab.query_entry.insert(0, query)
    clients_tab.search()
    root.update()
    check(f'найден {title}', len(rows(clients_tab.tree)) == 1,
          f'{query} -> {len(rows(clients_tab.tree))}')

clients_tab.query_entry.delete(0, tk.END)
clients_tab.query_entry.insert(0, 'нетакого')
clients_tab.search()
root.update()
check('несуществующий не находится', len(rows(clients_tab.tree)) == 0)

print('\n=== Карточка клиента ===')
client = client_service.find_by_phone('79099018931')
card = ui.client_card.ClientCard(clients_tab.frame, clients_tab.db, client.id)
root.update()

check('имя подставлено', card.name_entry.get() == 'Андрей', card.name_entry.get())
check('телефон подставлен', card.phone_entry.get() == '+7 (909) 901-89-31',
      card.phone_entry.get())
check('машины показаны', len(rows(card.cars_tree)) == 2, str(rows(card.cars_tree)))
check('история визитов показана', len(rows(card.orders_tree)) == 1,
      str(rows(card.orders_tree)))
check('в сводке есть визиты', 'Визитов' in card.summary_label.cget('text'),
      card.summary_label.cget('text'))

print('\n=== Правка имени и телефона ===')
card.name_entry.delete(0, tk.END)
card.name_entry.insert(0, 'Андрей Дюпин')
card.phone_entry.delete(0, tk.END)
card.phone_entry.insert(0, '8 916 123-45-67')
card.save_client()
root.update()

client = clients_tab.db.query(Client).filter(Client.id == client.id).first()
check('имя сохранено', client.name == 'Андрей Дюпин', client.name)
check('телефон сохранён в едином виде', client.phone == '79161234567', client.phone)

print('\n=== Правка данных автомобиля ===')
client_service.update_car('А123ВВ777', vehicle_type='suv', wheel_diameter='R18',
                          wheels_assembled=True)
car = client_service.get_car('А123ВВ777')
check('тип транспорта изменён', car.vehicle_type == 'suv', car.vehicle_type)
check('диаметр изменён', car.wheel_diameter == 'R18', car.wheel_diameter)
check('колёса в сборе отмечены', car.wheels_assembled is True)

print('\n=== Добавление автомобиля ===')
client_service.attach_car('м777мм199', client.id)
plates = [c.license_plate for c in client_service.get_client_cars(client.id)]
check('машина добавлена и нормализована', 'М777ММ199' in plates, str(plates))
check('теперь три машины', len(plates) == 3, str(plates))

print('\n=== Удаление и открепление ===')
client_service.delete_car('М777ММ199')
check('машина без нарядов удаляется',
      len(client_service.get_client_cars(client.id)) == 2)

try:
    client_service.delete_car('А123ВВ777')  # по ней есть наряд
    check('машину с историей удалить нельзя', False, 'удалилась')
except ValueError as e:
    check('машину с историей удалить нельзя', True, str(e))

check('количество нарядов по машине видно',
      client_service.count_car_orders('А123ВВ777') == 1,
      str(client_service.count_car_orders('А123ВВ777')))

client_service.detach_car('К900ОР99')
check('открепление оставляет машину в базе',
      client_service.get_car('К900ОР99') is not None)
check('у клиента осталась одна машина',
      len(client_service.get_client_cars(client.id)) == 1,
      str([c.license_plate for c in client_service.get_client_cars(client.id)]))

card.dialog.destroy()
root.destroy()
finish()
