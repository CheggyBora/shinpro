"""
Предварительная запись клиентов.

Приёмщик записывает клиента во время звонка; записи из приложения
клиента попадают в тот же список и помечаются источником.
Программа следит, чтобы на одно время не записали больше машин,
чем открыто постов.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('appointments')

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Appointment, Client
from services import AppointmentService, OrderService, EmployeeService, ClientService
from services.shift_service import ShiftService

init_db()
db = SessionLocal()

ShiftService(db).open_shift(open_posts=2)
emp = EmployeeService(db)
emp.register_employee(1)
emp.start_shift(1)

service = AppointmentService(db)
client_service = ClientService(db)
order_service = OrderService(db)

DAY = datetime.now().date() + timedelta(days=1)


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute)


print('=== Запись по телефонному звонку ===')
appointment = service.create(
    scheduled_at=at(10), duration_minutes=60,
    client_name='Андрей', client_phone='8 909 901-89-31',
    license_plate='a123bb777', services_note='переобувка, 4 колеса')

check('запись создана', appointment.id is not None)
check('телефон приведён к единому виду', appointment.client_phone == '79099018931',
      appointment.client_phone)
check('госномер приведён к единому виду', appointment.license_plate == 'А123ВВ777',
      appointment.license_plate)
check('источник — телефон', appointment.source == Appointment.SOURCE_PHONE)
check('источник читается по-человечески', appointment.source_title == 'По телефону')
check('статус — ожидается', appointment.status == Appointment.STATUS_SCHEDULED)
check('состояние читается по-человечески', appointment.status_title == 'Ожидается')

print('\n=== Запись привязывается к известному клиенту ===')
order = order_service.create_order('К900ОР99', 'R16', 'car',
                                   client_name='Сергей', client_phone='79161234567')
sergey = client_service.find_by_phone('79161234567')

linked = service.create(scheduled_at=at(12), duration_minutes=30,
                        client_phone='8 916 123-45-67', license_plate='К900ОР99')
check('клиент найден по телефону', linked.client_id == sergey.id,
      f'{linked.client_id} vs {sergey.id}')
check('машина найдена по госномеру', linked.car_id is not None)
check('имя подставлено из карточки', linked.client_name == 'Сергей', str(linked.client_name))

print('\n=== Новый клиент заводится прямо из записи ===')
before = db.query(Client).count()
walk_in = service.create(scheduled_at=at(13), duration_minutes=30,
                         client_name='Прохожий', client_phone='79995554433')
check('карточка клиента создана',
      db.query(Client).count() == before + 1,
      f'было {before}, стало {db.query(Client).count()}')
check('запись привязана к новому клиенту', walk_in.client_id is not None)

print('\n=== Запись из приложения карточку не заводит ===')
before = db.query(Client).count()
service.create(scheduled_at=at(13, 30), duration_minutes=30,
               client_name='Непроверенный', client_phone='79995551122',
               create_client=False)
check('непроверенные данные в базу клиентов не идут',
      db.query(Client).count() == before,
      f'было {before}, стало {db.query(Client).count()}')

print('\n=== Загрузка постов ===')
# По умолчанию под запись открыт один пост: пообещать больше,
# чем сделаешь, хуже, чем открыть ещё один пост в середине дня
free, busy, posts = service.check_capacity(at(10, 30), 30)
check('по умолчанию пост один', posts == 1, str(posts))
check('на 10:30 занят один пост', busy == 1, str(busy))
check('места нет при одном посте', free is False)

service.set_posts_for_day(DAY, 2)
free, busy, posts = service.check_capacity(at(10, 30), 30)
check('постов стало два', posts == 2, str(posts))
check('место появилось', free is True)

service.create(scheduled_at=at(10, 15), duration_minutes=60, license_plate='М777ММ199')
free, busy, posts = service.check_capacity(at(10, 30), 30)
check('теперь заняты оба поста', busy == 2, str(busy))
check('свободного места нет', free is False)

print('\n=== Непересекающееся время свободно ===')
free, busy, _ = service.check_capacity(at(16), 30)
check('на 16:00 свободно', free is True and busy == 0, f'занято {busy}')

print('\n=== Подсказка ближайшего свободного времени ===')
suggestion = service.suggest_free_time(DAY, 30)
check('время подсказано', suggestion is not None, str(suggestion))
check('подсказанное время действительно свободно',
      service.check_capacity(suggestion, 30)[0] is True, str(suggestion))

print('\n=== Список на день ===')
day_list = service.get_for_day(DAY)
# К этому моменту создано пять записей: 10:00, 10:15, 12:00, 13:00 и 13:30
check('записи за день собраны', len(day_list) == 5, str(len(day_list)))
check('отсортированы по времени',
      [a.scheduled_at for a in day_list] == sorted(a.scheduled_at for a in day_list))
check('на другой день пусто', len(service.get_for_day(DAY + timedelta(days=5))) == 0)

print('\n=== Запись из приложения клиента ===')
web = service.create(scheduled_at=at(15), duration_minutes=45,
                     client_phone='79031112233', license_plate='Т555ТТ77',
                     services_note='шиномонтаж',
                     source=Appointment.SOURCE_WEB)
check('источник — приложение', web.source == Appointment.SOURCE_WEB)
check('видно, что запись из приложения', web.source_title == 'Из приложения')

from_web = [a for a in service.get_for_day(DAY) if a.source == Appointment.SOURCE_WEB]
check('запись из приложения в общем списке дня', len(from_web) == 1, str(len(from_web)))

print('\n=== Клиент приехал ===')
service.mark_arrived(appointment.id)
check('статус — приехал', service.get(appointment.id).status == Appointment.STATUS_ARRIVED)

arrived_order = order_service.create_order('А123ВВ777', 'R16', 'car')
service.mark_arrived(appointment.id, work_order_id=arrived_order.id)
check('наряд связан с записью',
      service.get(appointment.id).work_order_id == arrived_order.id)

print('\n=== Отмена и неявка ===')
service.cancel(linked.id, reason='клиент передумал')
check('запись отменена', service.get(linked.id).status == Appointment.STATUS_CANCELLED)
check('причина сохранена', 'передумал' in (service.get(linked.id).comment or ''),
      str(service.get(linked.id).comment))

check('отменённая не занимает пост',
      service.count_overlapping(at(12), 30) == 0,
      str(service.count_overlapping(at(12), 30)))

service.mark_no_show(web.id)
check('отмечена неявка', service.get(web.id).status == Appointment.STATUS_NO_SHOW)

print('\n=== Правка записи ===')
service.update(appointment.id, scheduled_at=at(11), duration_minutes=90,
               services_note='переобувка и правка диска')
updated = service.get(appointment.id)
check('время изменено', updated.scheduled_at.hour == 11, str(updated.scheduled_at))
check('длительность изменена', updated.duration_minutes == 90)
check('работы изменены', 'правка' in updated.services_note)

print('\n=== Проверка входных данных ===')
for bad, title in [({'scheduled_at': None, 'duration_minutes': 30}, 'без времени'),
                   ({'scheduled_at': at(9), 'duration_minutes': 0}, 'нулевая длительность')]:
    try:
        service.create(**bad, license_plate='Х111ХХ77')
        check(f'отклонено: {title}', False, 'принято')
    except ValueError as e:
        check(f'отклонено: {title}', True, str(e))

print('\n=== Поиск записей клиента по телефону ===')
found = service.search_by_phone('8 909 901-89-31')
check('записи клиента находятся', len(found) >= 1, str(len(found)))

db.close()
finish()
