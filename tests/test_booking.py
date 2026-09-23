"""
Раздел «Запись»: посты по дням, заведение клиента из записи
и раскладка карточек по ленте времени.

Записывают по телефону, пока клиент ждёт на линии, поэтому проверяем
именно короткий путь: ввели номер машины — всё остальное подтянулось
или завелось само.
"""
import _setup
from _setup import use_temp_db, check, finish, silence_dialogs

use_temp_db('booking')

from datetime import datetime, timedelta

from config import init_db, SessionLocal
from models import Appointment, Client, Car, BookingPosts
from services import AppointmentService, ClientService
from services.appointment_service import MIN_POSTS, MAX_POSTS, DEFAULT_POSTS
from services.settings_service import SettingsService

init_db()
db = SessionLocal()
SettingsService(db).ensure_defaults()

service = AppointmentService(db)
clients = ClientService(db)

DAY = datetime(2026, 9, 14).date()          # понедельник
OTHER_DAY = DAY + timedelta(days=3)


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute)


print('=== По умолчанию под запись открыт один пост ===')
check('пост один', service.get_posts_for_day(DAY) == 1,
      str(service.get_posts_for_day(DAY)))
check('и это записано в самих правилах', DEFAULT_POSTS == 1)
check('в базе при этом ничего не заведено',
      db.query(BookingPosts).count() == 0)

print('\n=== Посты задаются на день ===')
service.set_posts_for_day(DAY, 3)
check('на этот день три', service.get_posts_for_day(DAY) == 3)
check('на соседний по-прежнему один', service.get_posts_for_day(OTHER_DAY) == 1)

print('\n=== Повторная настройка меняет, а не плодит записи ===')
service.set_posts_for_day(DAY, 2)
check('стало два', service.get_posts_for_day(DAY) == 2)
check('строка в базе одна', db.query(BookingPosts).count() == 1,
      str(db.query(BookingPosts).count()))

print('\n=== Больше трёх и меньше одного не бывает ===')
check('ноль превращается в один', service.clamp_posts(0) == MIN_POSTS)
check('десять превращается в три', service.clamp_posts(10) == MAX_POSTS)
check('мусор даёт значение по умолчанию', service.clamp_posts('абв') == DEFAULT_POSTS)
service.set_posts_for_day(OTHER_DAY, 99)
check('в базу тоже кладём не больше трёх',
      service.get_posts_for_day(OTHER_DAY) == 3)

print('\n=== Посты на неделю вперёд одним действием ===')
service.set_posts_for_days(DAY, 7, 2)
posts_map = service.get_posts_map(DAY, 9)
week = [posts_map[DAY + timedelta(days=i)] for i in range(7)]
check('вся неделя по два', week == [2] * 7, str(week))
check('восьмой день не тронут',
      posts_map[DAY + timedelta(days=7)] == 1,
      str(posts_map[DAY + timedelta(days=7)]))

print('\n=== Время записи считается по колёсам ===')
assembled = service.duration_for_wheels(True)
tires = service.duration_for_wheels(False)
unknown = service.duration_for_wheels(None)
check('в сборе быстрее, чем россыпью', assembled < tires,
      f'{assembled} против {tires}')
check('неизвестное — между ними', assembled <= unknown <= tires,
      f'{assembled} / {unknown} / {tires}')

print('\n=== Новый номер заводит и машину, и клиента ===')
appointment = service.create(
    scheduled_at=at(10), license_plate='а123вв777',
    client_name='Андрей', client_phone='8 909 901-89-31',
    wheels_assembled=True, duration_minutes=assembled)

check('машина заведена', appointment.car_id is not None)
check('номер нормализован', appointment.license_plate == 'А123ВВ777',
      appointment.license_plate)
check('клиент заведён', appointment.client_id is not None)
check('телефон нормализован', appointment.client_phone == '79099018931',
      str(appointment.client_phone))

car = clients.get_car('А123ВВ777')
check('машина привязана к клиенту', car.client_id == appointment.client_id)
check('колёса записаны в карточку машины', car.wheels_assembled is True)

print('\n=== Знакомый номер подтягивает клиента ===')
before_clients = db.query(Client).count()
before_cars = db.query(Car).count()
again = service.create(scheduled_at=at(11), license_plate='А123ВВ777')
check('клиент тот же', again.client_id == appointment.client_id)
check('имя подставлено', again.client_name == 'Андрей', str(again.client_name))
check('телефон подставлен', again.client_phone == '79099018931',
      str(again.client_phone))
check('новых клиентов не появилось', db.query(Client).count() == before_clients)
check('новых машин не появилось', db.query(Car).count() == before_cars)

print('\n=== Запись не переписывает то, что мастер видел сам ===')
service.create(scheduled_at=at(12), license_plate='А123ВВ777',
               wheels_assembled=False)
check('колёса в карточке остались прежними',
      clients.get_car('А123ВВ777').wheels_assembled is True)

print('\n=== Машина без владельца достаётся тому, кто записался ===')
db.add(Car(license_plate='К900ОР99'))
db.commit()
orphan = service.create(scheduled_at=at(13), license_plate='К900ОР99',
                        client_name='Сергей', client_phone='79161234567')
check('владелец назначен',
      clients.get_car('К900ОР99').client_id == orphan.client_id)

print('\n=== Запись без контактов клиента не создаёт ===')
before_clients = db.query(Client).count()
service.create(scheduled_at=at(14), license_plate='М777ММ199')
check('пустой карточки клиента не появилось',
      db.query(Client).count() == before_clients,
      str(db.query(Client).count()))
check('машина при этом заведена', clients.get_car('М777ММ199') is not None)

# --------------------------------------------------------------------
print('\n=== Раскладка по колонкам ===')
use_day = DAY + timedelta(days=20)


def on(hour, minute=0):
    return datetime(use_day.year, use_day.month, use_day.day, hour, minute)


service.set_posts_for_day(use_day, 2)
first = service.create(scheduled_at=on(9), duration_minutes=60,
                       license_plate='А001АА777')
second = service.create(scheduled_at=on(11), duration_minutes=60,
                        license_plate='А002АА777')

placed = service.layout_day(use_day)
columns = {a.id: column for a, column in placed}
check('непересекающиеся записи идут одной колонкой',
      columns[first.id] == 0 and columns[second.id] == 0, str(columns))

print('\n=== Пересечение занимает соседний пост ===')
overlap = service.create(scheduled_at=on(9, 30), duration_minutes=60,
                         license_plate='А003АА777')
columns = {a.id: column for a, column in service.layout_day(use_day)}
check('вторая машина встала во второй пост', columns[overlap.id] == 1,
      str(columns))

print('\n=== Когда постов не хватает, запись всё равно видна ===')
extra = service.create(scheduled_at=on(9, 45), duration_minutes=60,
                       license_plate='А004АА777')
placed = service.layout_day(use_day)
columns = {a.id: column for a, column in placed}
check('лишняя запись вынесена за сетку постов', columns[extra.id] == 2,
      str(columns))
check('все записи дня на месте', len(placed) == 4, str(len(placed)))

print('\n=== Отменённая запись из ленты пропадает ===')
service.cancel(extra.id)
placed = service.layout_day(use_day)
check('отменённой в ленте нет', len(placed) == 3, str(len(placed)))
check('но по запросу она видна',
      len(service.layout_day(use_day, include_cancelled=True)) == 4)

print('\n=== Занятость считается по постам этого дня ===')
free, busy, posts = service.check_capacity(on(9, 15), 30)
check('постов два', posts == 2, str(posts))
check('оба заняты', busy == 2, str(busy))
check('свободного места нет', free is False)

service.set_posts_for_day(use_day, 3)
free, busy, posts = service.check_capacity(on(9, 15), 30)
check('добавили пост — место появилось', free is True and posts == 3,
      f'{free} / {posts}')

db.close()
finish()
