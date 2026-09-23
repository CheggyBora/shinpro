"""
Страница записи по ссылке.

Человек открывает её в браузере телефона, без установки и без входа.
Значит, ошибиться он может как угодно: набрать номер латиницей,
выбрать время, которое только что заняли, нажать кнопку дважды.
Всё это проверяем здесь.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_public_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-public'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-public'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from datetime import datetime, timedelta, date

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.utils import now as shop_now
from app.models import BookingDay, Appointment, Client, Car
from app.api import public
from app.services import shop_settings

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


TOMORROW = date.today() + timedelta(days=1)


def at(hour, minute=0):
    return datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, hour, minute)


def relax():
    """Сбросить счётчик частых обращений: он общий на весь прогон."""
    public._recent.clear()


with TestClient(app) as client:
    db = SessionLocal()
    shop_settings.set_value(db, 'shop_name', 'Шиномонтаж «РИФ»', commit=False)
    shop_settings.set_value(db, 'shop_phone', '+7 909 901-89-31')
    db.add(BookingDay(day=TOMORROW, posts=1,
                      opens_at='09:00', closes_at='18:00'))
    db.add(BookingDay(day=TOMORROW + timedelta(days=1), posts=1, is_closed=True))
    db.commit()
    db.close()

    print('=== Страница открывается ===')
    page = client.get('/z')
    check('страница отдаётся', page.status_code == 200, str(page.status_code))
    check('это HTML', 'text/html' in page.headers['content-type'])
    check('заголовок на месте', 'Запись на шиномонтаж' in page.text)
    check('внешних загрузок нет',
          'http://' not in page.text.replace('http://www.w3.org', ''),
          'страница должна работать на плохой связи')

    print('\n=== Логотип ===')
    logo = client.get('/z/logo.jpg')
    check('логотип отдаётся', logo.status_code == 200, str(logo.status_code))
    check('это картинка', logo.headers['content-type'] == 'image/jpeg')

    print('\n=== Сведения о шиномонтаже ===')
    info = client.get('/public/info').json()
    check('название на месте', info['shop_name'] == 'Шиномонтаж «РИФ»',
          info['shop_name'])
    check('телефон на месте', '909' in (info['shop_phone'] or ''))
    check('время под колёса в сборе меньше',
          info['minutes_assembled'] < info['minutes_tires'],
          f"{info['minutes_assembled']} / {info['minutes_tires']}")

    print('\n=== Свободные окна видны без всякого входа ===')
    days = client.get('/public/days').json()
    check('дни отданы', len(days) > 0, str(len(days)))

    tomorrow = [d for d in days if d['day'] == TOMORROW.isoformat()][0]
    check('окна есть', len(tomorrow['slots']) > 0, str(len(tomorrow['slots'])))
    check('первое окно не раньше открытия',
          tomorrow['slots'][0]['at'].endswith('09:00:00'),
          tomorrow['slots'][0]['at'])

    closed = [d for d in days
              if d['day'] == (TOMORROW + timedelta(days=1)).isoformat()][0]
    check('в выходной окон нет', closed['slots'] == [] and closed['is_closed'])

    print('\n=== Под россыпь окон меньше, чем под колёса в сборе ===')
    assembled = client.get('/public/days?wheels_assembled=true').json()
    tires = client.get('/public/days?wheels_assembled=false').json()
    a_count = len([d for d in assembled
                   if d['day'] == TOMORROW.isoformat()][0]['slots'])
    t_count = len([d for d in tires
                   if d['day'] == TOMORROW.isoformat()][0]['slots'])
    check('под россыпь окон не больше, чем под перекидку', a_count >= t_count,
          f'{a_count} против {t_count}')
    check('перекидка короче разбортовки',
          info['minutes_assembled'] < info['minutes_tires'],
          f"{info['minutes_assembled']} против {info['minutes_tires']}")

    print('\n=== Запись без установки приложения ===')
    relax()
    booked = client.post('/public/book', json={
        'at': at(10).isoformat(),
        'license_plate': 'a123bb777',
        'client_phone': '8 909 901-89-31',
        'client_name': 'Андрей',
        'wheels_assembled': True})

    check('записались', booked.status_code == 200, str(booked.json()))
    answer = booked.json()
    check('время работ по колёсам в сборе',
          answer['duration_minutes'] == info['minutes_assembled'],
          str(answer['duration_minutes']))
    check('сказано, когда приезжать', '10:00' in answer['message'],
          answer['message'])
    check('дан телефон для связи', bool(answer['shop_phone']))

    print('\n=== Что легло в базу ===')
    db = SessionLocal()
    row = db.query(Appointment).filter(
        Appointment.license_plate == 'А123ВВ777').first()
    check('номер приведён к кириллице', row is not None)
    check('источник — ссылка', row.source == 'link', row.source)
    check('видно, что ждём клиента', row.status == 'scheduled')

    person = db.query(Client).filter(Client.phone == '79099018931').first()
    check('клиент заведён', person is not None)
    check('имя сохранено', person.name == 'Андрей', str(person.name))

    car = db.query(Car).filter(Car.license_plate == 'А123ВВ777').first()
    check('машина заведена', car is not None)
    check('колёса запомнились', car.wheels_assembled is True)
    check('машина привязана к клиенту', car.client_id == person.id)
    db.close()

    print('\n=== Занятое окно пропало из списка ===')
    days = client.get('/public/days').json()
    tomorrow = [d for d in days if d['day'] == TOMORROW.isoformat()][0]
    taken = [s for s in tomorrow['slots'] if s['at'].endswith('10:00:00')]
    check('десяти часов в списке больше нет', taken == [], str(taken))

    print('\n=== Второй раз на то же время не записаться ===')
    relax()
    again = client.post('/public/book', json={
        'at': at(10).isoformat(),
        'license_plate': 'К900ОР99',
        'client_phone': '79161234567'})
    check('время занято', again.status_code == 409, str(again.json()))
    check('предложено выбрать другое',
          'другое' in again.json()['detail'].lower(), again.json()['detail'])

    print('\n=== Кривой ввод не проходит ===')
    relax()
    no_plate = client.post('/public/book', json={
        'at': at(12).isoformat(), 'license_plate': '  ',
        'client_phone': '79161234567'})
    check('без номера машины не пускает', no_plate.status_code == 400,
          str(no_plate.json()))

    relax()
    short_phone = client.post('/public/book', json={
        'at': at(12).isoformat(), 'license_plate': 'К900ОР99',
        'client_phone': '12345'})
    check('короткий телефон не пускает', short_phone.status_code == 400,
          str(short_phone.json()))

    relax()
    past = client.post('/public/book', json={
        'at': (shop_now() - timedelta(hours=1)).isoformat(),
        'license_plate': 'К900ОР99', 'client_phone': '79161234567'})
    check('в прошлое не записаться', past.status_code == 400, str(past.json()))

    relax()
    far = client.post('/public/book', json={
        'at': (shop_now() + timedelta(days=90)).isoformat(),
        'license_plate': 'К900ОР99', 'client_phone': '79161234567'})
    check('слишком далеко не записаться', far.status_code == 400,
          str(far.json()))

    print('\n=== В выходной не записаться ===')
    relax()
    holiday = client.post('/public/book', json={
        'at': (datetime.combine(TOMORROW + timedelta(days=1),
                                datetime.min.time())
               + timedelta(hours=12)).isoformat(),
        'license_plate': 'К900ОР99', 'client_phone': '79161234567'})
    check('выходной отклонён', holiday.status_code == 400, str(holiday.json()))
    check('сказано, что не работаем',
          'не работает' in holiday.json()['detail'].lower(),
          holiday.json()['detail'])

    print('\n=== Много записей на один телефон не набить ===')
    relax()
    made = 0
    for hour in (11, 12, 13, 14):
        relax()
        answer = client.post('/public/book', json={
            'at': at(hour).isoformat(),
            'license_plate': 'К900ОР99',
            'client_phone': '79161234567'})
        if answer.status_code == 200:
            made += 1
        else:
            last = answer
            break

    check('больше трёх записей на телефон не даёт', made == 3, str(made))
    check('объяснено почему',
          'уже есть' in last.json()['detail'].lower(), last.json()['detail'])

    print('\n=== Частые обращения с одного адреса отсекаются ===')
    public._recent.clear()
    blocked = None
    for hour in range(9, 18):
        answer = client.post('/public/book', json={
            'at': at(hour, 30).isoformat(),
            'license_plate': f'М{hour:03d}ММ77',
            'client_phone': f'7916000{hour:04d}'})
        if answer.status_code == 429:
            blocked = answer
            break

    check('поток записей подряд остановлен', blocked is not None,
          'ожидался отказ 429')
    if blocked is not None:
        check('предложено позвонить',
              'позвоните' in blocked.json()['detail'].lower(),
              blocked.json()['detail'])

finish()
