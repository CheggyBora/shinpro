"""
Один клиент вместо дублей, несколько машин на клиента, поиск.

Раньше на каждый наряд заводилась новая запись клиента, поэтому база
заполнялась дублями, а история клиента не собиралась.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('clients')

from config import init_db, SessionLocal
from models import Client, Car, Service, WorkOrder
from services import OrderService, ClientService, EmployeeService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()

order_service = OrderService(db)
client_service = ClientService(db)

ShiftService(db).open_shift()
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=400.0, price_r17=450.0))
db.commit()

print('=== Повторные визиты не плодят клиентов ===')
order_service.create_order('А123ВВ777', 'R16', 'car', client_name='Андрей', client_phone='+7 (909) 901-89-31')
order_service.create_order('а123вв777', 'R16', 'car', client_name='Андрей', client_phone='8 909 901 89 31')
order_service.create_order('A123BB777', 'R16', 'car', client_name='Андрей', client_phone='9099018931')

check('три визита — один клиент', db.query(Client).count() == 1,
      f'клиентов: {db.query(Client).count()}')
check('три написания номера — одна машина', db.query(Car).count() == 1,
      f'машин: {[c.license_plate for c in db.query(Car).all()]}')
check('все три наряда сохранены', db.query(WorkOrder).count() == 3)

print('\n=== Один клиент — несколько машин ===')
andrey = db.query(Client).first()
order_service.create_order('К900ОР99', 'R17', 'suv', client_id=andrey.id)
order_service.create_order('О001ОО77', 'R17', 'car', client_phone='79099018931')
client_service.attach_car('м777мм199', andrey.id)

plates = [c.license_plate for c in client_service.get_client_cars(andrey.id)]
check('за клиентом закреплены 4 машины', len(plates) == 4, str(plates))
check('номера сохранены в едином виде', 'М777ММ199' in plates, str(plates))
check('клиент по-прежнему один', db.query(Client).count() == 1)

print('\n=== Поиск клиента ===')
check('по телефону целиком', client_service.find_by_phone('+7 909 901-89-31') is not None)
check('по телефону, набранному с восьмёрки',
      client_service.find_by_phone('89099018931') is not None)
check('по телефону целиком через общий поиск',
      len(client_service.search('8 909 901-89-31')) == 1,
      f'найдено {len(client_service.search("8 909 901-89-31"))}')
check('по последним цифрам телефона', len(client_service.search('8931')) == 1)
check('по имени в нижнем регистре', len(client_service.search('андрей')) == 1)
check('по госномеру машины', client_service.find_by_plate('к900ор99') is not None)
check('по госномеру латиницей', len(client_service.search('K900OP99')) == 1)
check('несуществующий телефон не находится',
      client_service.find_by_phone('79001112233') is None)

print('\n=== Клиенты не смешиваются ===')
order_service.create_order('Н555НН50', 'R16', 'car', client_name='Пётр', client_phone='79161234567')
check('клиентов стало два', db.query(Client).count() == 2)
petr = client_service.find_by_phone('79161234567')
check('у Петра одна машина', len(client_service.get_client_cars(petr.id)) == 1)
check('у Андрея по-прежнему четыре', len(client_service.get_client_cars(andrey.id)) == 4)

print('\n=== Сводка по клиенту ===')
summary = client_service.get_client_summary(andrey.id)
check('телефон показан по-человечески', summary['phone_display'] == '+7 (909) 901-89-31',
      summary['phone_display'])
check('история собрана по всем машинам клиента',
      len(client_service.get_client_orders(andrey.id)) == 5,
      f'нарядов: {len(client_service.get_client_orders(andrey.id))}')

print('\n=== Хранение шин не создаёт служебных клиентов ===')
before = db.query(Client).count()
order_service.create_order('Т111ТТ77', 'R16', 'car', create_client=False)
check('число клиентов не изменилось', db.query(Client).count() == before,
      f'было {before}, стало {db.query(Client).count()}')

print('\n=== Автоскидка ===')
full = order_service.create_order('У222УУ77', 'R16', 'car',
                                  client_name='Иван', client_phone='79031112233')
check('есть имя и телефон — автоскидка есть', full.auto_discount is True)
partial = order_service.create_order('Е333ЕЕ77', 'R16', 'car', client_phone='79034445566')
check('только телефон — автоскидки нет', partial.auto_discount is False)

print('\n=== Телефон нельзя отдать чужому клиенту ===')
try:
    client_service.update_client(petr.id, phone='79099018931')  # телефон Андрея
    check('занятый телефон отклонён', False, 'изменение прошло')
except ValueError as e:
    check('занятый телефон отклонён', True, str(e))

db.close()
finish()
