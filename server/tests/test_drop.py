"""
Удаление тестовой точки и заказчика.

Проверку обмена делают на отдельной точке: заводят, гоняют на ней
данные, убирают. Без удаления она остаётся висеть в выборе точек и
путает того, кто смотрит в дашборд.

Команда опасная, и проверяем мы здесь ровно две вещи:

  · убрано всё, что относится к точке, — ничего не осталось висеть
    на несуществующем;
  · **соседнюю точку не задело.** Это главное: удаление по ошибке
    чужих нарядов не откатишь.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_drop_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-drop'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''

from datetime import timedelta

from app.database import init_db, SessionLocal
from app.models import (Account, Appointment, Client, Notice, PushSubscription,
                        SalaryAccrual, Shop, ShopEmployee, StaffUser,
                        StoredSet, Visit, VisitItem, KIND_BOOKED)
from app.services import tenancy
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" +
          (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


def finish():
    print('-' * 60)
    if _failures:
        print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
        for item in _failures:
            print(f'  - {item}')
        sys.exit(1)
    print('Все проверки пройдены')
    sys.exit(0)


init_db()
db = SessionLocal()


def fill(shop, client, plate):
    """Набить точку данными: наряд с позициями, запись, комплект, мастер."""
    visit = Visit(shop_id=shop.id, local_id=1, client_id=client.id,
                  license_plate=plate, visited_at=shop_now(),
                  total_amount=3000.0)
    db.add(visit)
    db.flush()

    db.add(VisitItem(visit_id=visit.id, service_name='Шиномонтаж',
                     quantity=4, unit_price=750.0, total=3000.0))
    db.add(SalaryAccrual(visit_id=visit.id, employee_local_id=1,
                         amount=1200.0, accrued_at=shop_now()))
    db.add(Appointment(shop_id=shop.id, client_id=client.id,
                       scheduled_at=shop_now() + timedelta(days=1),
                       duration_minutes=60, license_plate=plate,
                       status='scheduled'))
    db.add(StoredSet(shop_id=shop.id, local_id=1, client_id=client.id,
                     license_plate=plate, status='stored'))
    db.add(ShopEmployee(shop_id=shop.id, local_id=1, name='Игорь'))
    db.commit()


account, real, _key = tenancy.create_account(db, 'Шиномонтаж «РИФ»')
test_shop, _test_key = tenancy.add_shop(db, account, 'Тестовая точка')

person = Client(account_id=account.id, phone='79099018931', name='Андрей')
db.add(person)
db.commit()

fill(real, person, 'А123ВВ777')
fill(test_shop, person, 'Т777ТТ777')

real_id, test_id = real.id, test_shop.id

print('=== Две точки, в обеих данные ===')
check('наряды есть у обеих',
      db.query(Visit).filter(Visit.shop_id == real_id).count() == 1
      and db.query(Visit).filter(Visit.shop_id == test_id).count() == 1)
check('позиции и начисления на месте',
      db.query(VisitItem).count() == 2 and db.query(SalaryAccrual).count() == 2,
      f'{db.query(VisitItem).count()} и {db.query(SalaryAccrual).count()}')

print()
print('=== Что покажет команда перед удалением ===')
counts = tenancy.shop_contents(db, db.query(Shop).get(test_id))
check('наряд посчитан', counts['нарядов'] == 1, str(counts['нарядов']))
check('комплект посчитан', counts['комплектов'] == 1, str(counts['комплектов']))
check('запись посчитана', counts['записей'] == 1, str(counts['записей']))

print()
print('=== Убираем тестовую точку ===')
tenancy.drop_shop(db, db.query(Shop).get(test_id))

check('точки больше нет', db.query(Shop).get(test_id) is None)
check('её нарядов нет',
      db.query(Visit).filter(Visit.shop_id == test_id).count() == 0)
check('её записей нет',
      db.query(Appointment).filter(Appointment.shop_id == test_id).count() == 0)
check('её комплектов нет',
      db.query(StoredSet).filter(StoredSet.shop_id == test_id).count() == 0)
check('её мастеров нет',
      db.query(ShopEmployee).filter(
          ShopEmployee.shop_id == test_id).count() == 0)

print()
print('=== Соседнюю точку не задело ===')
check('наряд на месте',
      db.query(Visit).filter(Visit.shop_id == real_id).count() == 1)
check('позиции не осиротели и не пропали',
      db.query(VisitItem).count() == 1, str(db.query(VisitItem).count()))
check('начисления тоже',
      db.query(SalaryAccrual).count() == 1,
      str(db.query(SalaryAccrual).count()))
check('комплект на месте',
      db.query(StoredSet).filter(StoredSet.shop_id == real_id).count() == 1)
check('клиент остался: он принадлежит заказчику, а не точке',
      db.query(Client).count() == 1, str(db.query(Client).count()))

print()
print('=== Убираем заказчика целиком ===')
db.add(PushSubscription(account_id=account.id, client_id=person.id,
                        endpoint='https://пример/подписка',
                        p256dh='ключ', auth='подпись'))
db.add(Notice(account_id=account.id, client_id=person.id, kind=KIND_BOOKED,
              text='Записали вас'))
db.add(StaffUser(account_id=account.id, phone='79161112233', role='owner'))
db.commit()

tenancy.drop_account(db, db.query(Account).get(account.id))

check('заказчика нет', db.query(Account).count() == 0)
check('точек не осталось', db.query(Shop).count() == 0,
      str(db.query(Shop).count()))
check('клиентов не осталось', db.query(Client).count() == 0,
      str(db.query(Client).count()))
check('нарядов не осталось', db.query(Visit).count() == 0,
      str(db.query(Visit).count()))
check('позиций не осталось', db.query(VisitItem).count() == 0,
      str(db.query(VisitItem).count()))
check('подписок не осталось', db.query(PushSubscription).count() == 0)
check('уведомлений не осталось', db.query(Notice).count() == 0)
check('персонала не осталось', db.query(StaffUser).count() == 0)

db.close()
finish()
