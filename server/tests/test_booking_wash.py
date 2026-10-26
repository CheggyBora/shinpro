"""
Запись на мойку (docs/booking_wash.md).

  · у мойки свои посты, часы, шаг и длительность — из её настроек;
  · занятость раздельная: мойка не занимает пост шиномонтажа и наоборот;
  · запись на мойку закрыта, пока цех её не включил;
  · без класса машины на мойку не записываем; колёса, диаметр и склад
    у мойки не спрашиваются и в запись не попадают;
  · «Мои записи» говорят, мойка это или шиномонтаж; «Я на месте» у
    мойки нет;
  · напоминания: «подъезжайте» без строки про «Я на месте», «опоздали»
    у мойки не отправляется;
  · обмен с цехом: GET /sync/appointments по умолчанию — шиномонтаж,
    с direction=wash — мойка и её посты; POST принимает направление.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, date

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_booking_wash_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-wash'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-wash'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (Appointment, Client, Notice, Shop, KIND_ARRIVE,
                        KIND_LATE, WAITING)
from app.security import create_token
from app.services import notices, shop_settings
from app.services.booking_service import to_public, can_check_in
from app.utils import now as shop_now
from app.api import public

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


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
TOMORROW = shop_now().date() + timedelta(days=1)
LATER = TOMORROW + timedelta(days=1)


def at(hour, minute=0, day=TOMORROW):
    return datetime(day.year, day.month, day.day, hour, minute)


def iso(moment):
    return moment.isoformat()


def slots_of(answer, day=TOMORROW):
    for item in answer:
        if item['day'] == day.isoformat():
            return [slot['at'][11:16] for slot in item['slots']], item
    return [], None


def setting(key, value):
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_settings.set_value(db, key, value, shop=shop)
    db.close()


def relax():
    """Счётчик частых записей общий на весь прогон — сбрасываем."""
    public._recent.clear()


with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop.last_sync_at = shop_now()
    slug, shop_id, account_id = shop.slug, shop.id, shop.account_id
    db.commit()

    owner = Client(account_id=account_id, phone='79160000101', name='Ольга',
                   telegram_chat_id='777')
    db.add(owner)
    db.commit()
    token = create_token(owner.id)
    owner_id = owner.id
    db.close()

    q = f'?shop={slug}'
    auth = {'Authorization': f'Bearer {token}'}

    # Мойка на объекте есть, но запись на неё ещё не включили
    setting('direction_wash', '1')

    print('=== Запись на мойку выключена ===')
    info = http.get('/public/info' + q).json()
    check('кабинет знает: шиномонтаж записывают', info.get('tire_booking') is True,
          str(info))
    check('кабинет знает: мойку — нет', info.get('wash_booking') is False)

    refused = http.get('/public/days' + q + '&direction=wash')
    check('окна мойки не отдаём', refused.status_code == 400, refused.text)
    refused = http.get('/booking/days' + q + '&direction=wash', headers=auth)
    check('и в кабинете тоже', refused.status_code == 400, refused.text)
    refused = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(10)), 'license_plate': 'А100АА77',
        'direction': 'wash', 'wash_class': 'sedan'})
    check('записаться на мойку нельзя', refused.status_code == 400
          and 'мойку' in refused.json()['detail'], refused.text)
    bogus = http.get('/public/days' + q + '&direction=space')
    check('непонятное направление — ошибка, а не шиномонтаж',
          bogus.status_code == 400, bogus.text)

    # Мойка без direction_wash не записывается, даже если галочка стоит
    setting('direction_wash', '0')
    setting('wash_booking_enabled', '1')
    info = http.get('/public/info' + q).json()
    check('без мойки на объекте запись на неё закрыта',
          info['wash_booking'] is False, str(info))

    print()
    print('=== Свои посты, часы, шаг и длительность ===')
    setting('direction_wash', '1')
    setting('wash_booking_posts', '1')
    setting('wash_booking_opens_at', '10:00')
    setting('wash_booking_closes_at', '12:00')
    setting('wash_booking_slot_step', '30')
    setting('wash_booking_minutes', '45')

    info = http.get('/public/info' + q).json()
    check('теперь мойку записывают', info['wash_booking'] is True, str(info))
    check('и сказано, сколько она займёт', info['wash_minutes'] == 45)

    wash_days = http.get('/public/days' + q + '&direction=wash&wash_class=sedan').json()
    wash_slots, wash_day = slots_of(wash_days)
    check('окна мойки — по её часам, шагу и длительности',
          wash_slots == ['10:00', '10:30', '11:00'], str(wash_slots))
    check('посты мойки — из её настроек', wash_day and wash_day['posts'] == 1,
          str(wash_day and wash_day['posts']))

    tire_slots, tire_day = slots_of(http.get('/public/days' + q).json())
    check('у шиномонтажа окна свои — с семи утра, через час',
          tire_slots[:2] == ['07:00', '08:00'], str(tire_slots[:3]))

    print()
    print('=== Мойке нужен класс машины ===')
    no_class = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(10)), 'license_plate': 'А100АА77', 'direction': 'wash'})
    check('без класса — отказ', no_class.status_code == 400
          and 'класс' in no_class.json()['detail'].lower(), no_class.text)
    bad_class = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(10)), 'license_plate': 'А100АА77', 'direction': 'wash',
        'wash_class': 'bus'})
    check('с непонятным классом — отказ', bad_class.status_code == 400,
          bad_class.text)

    booked = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(10)), 'license_plate': 'А100АА77', 'direction': 'wash',
        'wash_class': 'Crossover', 'wheel_diameter': 'R16',
        'wheels_assembled': True})
    check('записались на мойку', booked.status_code == 200, booked.text)
    data = booked.json()
    check('запись — мойка', data.get('direction') == 'wash', str(data))
    check('с классом машины', data.get('wash_class') == 'crossover'
          and data.get('wash_class_title') == 'Кроссовер')
    check('длительность — мойки', data['duration_minutes'] == 45)
    check('колёс и диаметра у мойки нет', data.get('wheel_diameter') is None
          and data.get('wheels_assembled') is None)
    check('«Я на месте» у мойки нет', data['can_check_in'] is False)
    wash_id = data['id']

    db = SessionLocal()
    from app.models import Car
    car = db.query(Car).filter(Car.license_plate == 'А100АА77').first()
    check('в карточку машины колёса с мойки не записаны',
          car is not None and car.wheels_assembled is None)
    db.close()

    print()
    print('=== Занятость раздельная ===')
    wash_slots, _ = slots_of(http.get('/public/days' + q + '&direction=wash').json())
    check('мойка в 10:00 заняла окна мойки', wash_slots == ['11:00'],
          str(wash_slots))
    tire_slots, _ = slots_of(http.get('/public/days' + q).json())
    check('а шиномонтажу 10:00 свободно', '10:00' in tire_slots, str(tire_slots))

    relax()
    tire = http.post('/public/book' + q, json={
        'at': iso(at(10)), 'license_plate': 'В200ВВ77',
        'client_phone': '79160000202', 'wheel_diameter': 'R16',
        'wheels_assembled': True})
    check('на шиномонтаж в 10:00 записались, хотя мойка занята',
          tire.status_code == 200, tire.text)
    check('ответ — про работы, не про мойку', 'Работы' in tire.json()['message'])

    wash_slots, _ = slots_of(http.get('/public/days' + q + '&direction=wash').json())
    check('шиномонтаж окна мойки не занял', wash_slots == ['11:00'],
          str(wash_slots))

    relax()
    taken = http.post('/public/book' + q, json={
        'at': iso(at(10)), 'license_plate': 'Е300ЕЕ77',
        'client_phone': '79160000303', 'direction': 'wash',
        'wash_class': 'sedan'})
    check('второй на тот же пост мойки — занято', taken.status_code == 409,
          taken.text)

    relax()
    by_link = http.post('/public/book' + q, json={
        'at': iso(at(11)), 'license_plate': 'Е300ЕЕ77',
        'client_phone': '79160000303', 'direction': 'wash',
        'wash_class': 'jeep', 'wheel_diameter': 'R18'})
    check('по ссылке на мойку записались', by_link.status_code == 200,
          by_link.text)
    check('ответ про мойку', 'Мойка' in by_link.json()['message'],
          by_link.json()['message'])
    relax()
    no_class = http.post('/public/book' + q, json={
        'at': iso(at(11, 30)), 'license_plate': 'Е300ЕЕ77',
        'client_phone': '79160000303', 'direction': 'wash'})
    check('по ссылке без класса — отказ', no_class.status_code == 400,
          no_class.text)

    db = SessionLocal()
    row = db.query(Appointment).filter(
        Appointment.license_plate == 'Е300ЕЕ77').first()
    check('в базе — мойка, джип, без диаметра',
          row.direction == 'wash' and row.wash_class == 'jeep'
          and row.wheel_diameter is None and row.duration_minutes == 45,
          f'{row.direction} {row.wash_class} {row.wheel_diameter}')
    tire_row = db.query(Appointment).filter(
        Appointment.license_plate == 'В200ВВ77').first()
    check('запись на шиномонтаж — шиномонтаж', tire_row.direction == 'tire'
          and tire_row.wash_class is None and tire_row.wheel_diameter == 'R16')
    db.close()

    print()
    print('=== Мои записи и «Я на месте» ===')
    tire_mine = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(14)), 'license_plate': 'А100АА77',
        'wheel_diameter': 'R17', 'wheels_assembled': True})
    check('на шиномонтаж из кабинета — как раньше, без направления',
          tire_mine.status_code == 200 and tire_mine.json()['direction'] == 'tire',
          tire_mine.text)

    mine = http.get('/booking/my', headers=auth).json()
    by_id = {item['id']: item for item in mine}
    check('мойка видна как мойка', by_id.get(wash_id, {}).get('direction') == 'wash'
          and by_id[wash_id]['wash_class_title'] == 'Кроссовер', str(by_id.get(wash_id)))
    tire_item = by_id.get(tire_mine.json()['id'], {})
    check('шиномонтаж — с диаметром', tire_item.get('direction') == 'tire'
          and tire_item.get('wheel_diameter') == 'R17', str(tire_item))

    # Запись на мойку через полчаса: шиномонтажу «Я на месте» уже можно
    db = SessionLocal()
    soon = shop_now().replace(second=0, microsecond=0) + timedelta(minutes=30)
    near_wash = Appointment(shop_id=shop_id, client_id=owner_id,
                            scheduled_at=soon, duration_minutes=45,
                            license_plate='А100АА77', direction='wash',
                            wash_class='sedan', status='scheduled')
    near_tire = Appointment(shop_id=shop_id, client_id=owner_id,
                            scheduled_at=soon, duration_minutes=60,
                            license_plate='А100АА77', status='scheduled')
    db.add_all([near_wash, near_tire])
    db.commit()
    check('шиномонтажу за полчаса отметиться можно', can_check_in(near_tire))
    check('мойке — нет', not can_check_in(near_wash)
          and to_public(near_wash)['can_check_in'] is False)
    near_wash_id = near_wash.id
    db.close()
    here = http.post(f'/booking/{near_wash_id}/here', headers=auth)
    check('«Я на месте» по мойке отклонено', here.status_code == 400, here.text)

    # Поздно вечером «через полчаса» — уже завтра: убираем, чтобы не
    # путать проверки обмена ниже
    db = SessionLocal()
    db.query(Appointment).filter(Appointment.scheduled_at == soon).delete()
    db.commit()
    db.close()

    print()
    print('=== Напоминания ===')
    wash_late = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(10, day=LATER)), 'license_plate': 'А100АА77',
        'direction': 'wash', 'wash_class': 'minivan'})
    tire_late = http.post('/booking' + q, headers=auth, json={
        'at': iso(at(12, day=LATER)), 'license_plate': 'А100АА77',
        'wheel_diameter': 'R17'})
    check('записались на послезавтра', wash_late.status_code == 200
          and tire_late.status_code == 200, wash_late.text + tire_late.text)

    db = SessionLocal()

    def planned(appointment_id):
        return {row.kind: row for row in db.query(Notice).filter(
            Notice.about == 'appointment',
            Notice.about_id == appointment_id).all()}

    wash_notices = planned(wash_late.json()['id'])
    tire_notices = planned(tire_late.json()['id'])
    check('мойке — «подъезжайте»', KIND_ARRIVE in wash_notices, str(list(wash_notices)))
    check('без строки про «Я на месте»',
          'Я на месте' not in wash_notices[KIND_ARRIVE].text,
          wash_notices[KIND_ARRIVE].text)
    check('«опоздали» мойке не планируется', KIND_LATE not in wash_notices)
    check('шиномонтажу — как раньше: «Я на месте» и «опоздали»',
          'Я на месте' in tire_notices[KIND_ARRIVE].text
          and KIND_LATE in tire_notices)

    # Запись перевели на мойку уже после того, как «опоздали» встало в
    # очередь, — при отправке оно не уходит
    late = tire_notices[KIND_LATE]
    check('«опоздали» шиномонтажу уходит', not notices._out_of_season(db, late))
    row = db.get(Appointment, tire_late.json()['id'])
    row.direction = 'wash'
    db.commit()
    check('стала мойкой — «опоздали» не уходит', notices._out_of_season(db, late))
    row.direction = 'tire'
    db.commit()
    db.close()

    print()
    print('=== Обмен с цехом ===')
    setting('wash_booking_posts', '2')
    day = TOMORROW.isoformat()

    plain = http.get(f'/sync/appointments?day={day}', headers=KEY).json()
    check('по умолчанию — только шиномонтаж',
          plain['appointments'] and all(item['direction'] == 'tire'
                                        for item in plain['appointments']),
          str([item['direction'] for item in plain['appointments']]))
    check('и посты шиномонтажа', plain['posts'] == 1, str(plain['posts']))
    tire_item = [item for item in plain['appointments']
                 if item['license_plate'] == 'В200ВВ77'][0]
    check('мойка в то же время не вытеснила шиномонтаж за сетку',
          tire_item['column'] == 0, str(tire_item['column']))

    washes = http.get(f'/sync/appointments?day={day}&direction=wash',
                      headers=KEY).json()
    plates = sorted(item['license_plate'] for item in washes['appointments'])
    check('direction=wash — только мойка', plates == ['А100АА77', 'Е300ЕЕ77'],
          str(plates))
    check('посты мойки под запись', washes['posts'] == 2, str(washes['posts']))
    check('у записи класс машины', {item['wash_class']
                                    for item in washes['appointments']}
          == {'crossover', 'jeep'})
    check('колонки — внутри мойки', all(item['column'] == 0
                                        for item in washes['appointments']))
    bad = http.get(f'/sync/appointments?day={day}&direction=space', headers=KEY)
    check('непонятное направление — ошибка', bad.status_code == 400)

    made = http.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': iso(at(10, 15)), 'duration_minutes': 30,
        'license_plate': 'К400КК77', 'client_phone': '79160000404',
        'direction': 'wash', 'wash_class': 'sedan', 'wheels_assembled': True})
    check('приёмщик записал на мойку', made.status_code == 200
          and made.json()['direction'] == 'wash' and made.json()['posts'] == 2,
          made.text)
    db = SessionLocal()
    row = db.get(Appointment, made.json()['id'])
    check('в базе — мойка, седан, без колёс', row.direction == 'wash'
          and row.wash_class == 'sedan' and row.wheels_assembled is None)
    db.close()

    third = http.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': iso(at(10, 30)), 'duration_minutes': 30,
        'license_plate': 'М500ММ77', 'direction': 'wash', 'wash_class': 'sedan'})
    check('оба поста мойки заняты — отказ', third.status_code == 409, third.text)

    odd = http.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': iso(at(11, 30)), 'duration_minutes': 30,
        'license_plate': 'М500ММ77', 'direction': 'wash', 'wash_class': 'bus'})
    check('непонятный класс — ошибка', odd.status_code == 400, odd.text)

    old_shop = http.post('/sync/appointments', headers=KEY, json={
        'scheduled_at': iso(at(16)), 'duration_minutes': 60,
        'license_plate': 'М500ММ77', 'client_phone': '79160000505'})
    check('старый цех без направления — шиномонтаж',
          old_shop.status_code == 200 and old_shop.json()['direction'] == 'tire',
          old_shop.text)

    # Перенос мойки проверяется по постам мойки: в 11:00 уже стоит
    # джип, но постов мойки два — место есть
    moved = http.patch(f'/sync/appointments/{made.json()["id"]}', headers=KEY,
                       json={'scheduled_at': iso(at(11, 0))})
    check('перенос мойки на свободный пост мойки', moved.status_code == 200,
          moved.text)

    print()
    print('=== Посты шиномонтажа мойку не видят ===')
    posts = http.get(f'/sync/posts?day={day}', headers=KEY).json()
    check('/sync/posts — посты шиномонтажа', posts.get(day) == 1, str(posts))

finish()
