"""
Онлайн-очередь: место занимают из дома.

Главное решение, которое тут проверяется: **порядок по времени
прибытия, а не по времени нажатия.** Иначе тот, кто в часе езды,
занимает первую позицию, пост стоит пустой, а живущий в пяти минутах
ждёт его.

Второе — честность перед человеком. Ему называют время, и он строит
на нём планы: выехать, отпроситься, отвезти ребёнка. Если время
уехало, он должен узнать об этом от нас, а не стоя у ворот.

Третье — пост не простаивает. Из онлайна никого нет, встала живая
машина: прогноз сдвигается на её работу, и это говорится вслух.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_queue_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-queue'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-queue'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Client, OpenOrder, QueueTicket, Shop, CALLED, EXPIRED
from app.services import queue_service, shop_settings
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


with TestClient(app) as client:
    db = SessionLocal()
    shop = db.query(Shop).first()
    shop.last_sync_at = shop_now()

    # Один пост под очередь, работа полчаса — так проще считать
    shop_settings.set_value(db, 'queue_posts', '1', commit=False, shop=shop)
    shop_settings.set_value(db, 'booking_minutes_unknown', '30', shop=shop)

    people = []
    for number in range(1, 5):
        person = Client(account_id=shop.account_id,
                        phone=f'7916000000{number}', name=f'Клиент {number}')
        db.add(person)
        people.append(person)
    db.commit()
    for person in people:
        db.refresh(person)

    NOW = shop_now()

    print('=== Время назначаем мы: не раньше чем через час ===')
    # Человека ни о чём не спрашиваем. Он занимает место, а когда
    # подъезжать — узнаёт из ответа
    first = queue_service.join(db, shop, people[0], plate='А111АА77', now=NOW)
    check('час от постановки',
          first.eta_at == NOW + timedelta(minutes=60), str(first.eta_at))

    second = queue_service.join(db, shop, people[1], plate='К222КК77',
                                now=NOW + timedelta(minutes=1))

    print()
    print('=== Порядок — в котором вставали ===')
    order = [t.license_plate for t in queue_service.line(db, shop, NOW)]
    check('первым встал — первым и идёт',
          order == ['А111АА77', 'К222КК77'], str(order))

    print()
    print('=== Обоим — не раньше их часа ===')
    times = queue_service.forecast(db, shop, NOW)
    check('первого через час', times[first.id] == first.eta_at,
          str(times[first.id]))
    check('второго не раньше его часа', times[second.id] >= second.eta_at,
          str(times[second.id]))

    print()
    print('=== Приехавший обгоняет того, кто ещё едет ===')
    # Приехал раньше названного — держать его за время нелепо, он
    # уже здесь
    queue_service.arrived(db, shop, second, now=NOW + timedelta(minutes=5))
    order = [t.license_plate for t in queue_service.line(
        db, shop, NOW + timedelta(minutes=5))]
    check('приехавший впереди', order == ['К222КК77', 'А111АА77'], str(order))

    print()
    print('=== Звать можно только того, кто на месте ===')
    nobody = queue_service.next_up(db, shop, NOW + timedelta(minutes=5))
    check('зовём приехавшего', nobody.id == second.id,
          str(nobody.license_plate))

    refused = None
    try:
        queue_service.call(db, shop, first)
    except queue_service.QueueError as e:
        refused = str(e)
    check('того, кто в пути, звать нельзя', refused is not None, str(refused))
    check('сказано, почему', 'на месте' in (refused or ''), str(refused))

    print()
    print('=== Не приехал — в конец очереди, и это один раз ===')
    # Смещать на позицию не стали: человеку трудно объяснить, почему
    # он то второй, то третий. Правило одно — не успел, в конец
    queue_service.call(db, shop, second, now=NOW + timedelta(minutes=6))
    check('позван', second.state == CALLED, second.state)

    was_first = first.eta_at
    queue_service.move_back(db, shop, second, now=NOW + timedelta(minutes=6))

    check('остался в очереди', second.is_open is True, second.state)
    check('перенос посчитан', second.moves == 1, str(second.moves))
    check('встал за последним', second.eta_at > first.eta_at,
          f'{second.eta_at} против {first.eta_at}')
    check('чужое время не тронули', first.eta_at == was_first,
          f'{first.eta_at} против {was_first}')
    check('отметку о приезде сбросили', second.arrived_at is None)

    order = [t.license_plate for t in queue_service.line(
        db, shop, NOW + timedelta(minutes=6))]
    check('и он теперь последний', order[-1] == 'К222КК77', str(order))

    print()
    print('=== Выпавший никого вперёд не тянет ===')
    # Человек рассчитывал на названное время: выехать, отпроситься,
    # отвезти ребёнка. Освободившееся берёт живая очередь
    queue_service.remember_promise(db, shop, NOW + timedelta(minutes=6))
    promised = first.promised_at

    queue_service.move_back(db, shop, second, now=NOW + timedelta(minutes=7))
    check('второй перенос закрывает место', second.state == EXPIRED,
          second.state)

    times = queue_service.forecast(db, shop, NOW + timedelta(minutes=7))
    check('время оставшегося не уехало назад',
          times[first.id] >= promised,
          f'{times[first.id]} против {promised}')

    print()
    print('=== Пост заняли живой машиной — прогноз сдвигается ===')
    # Из онлайна никого нет, пост не должен простаивать. Но тем, кто
    # в очереди, надо сказать: их время уехало
    db.add(OpenOrder(shop_id=shop.id, local_id=77, license_plate='Х555ХХ99',
                     state='work', started_at=NOW,
                     planned_minutes=40, on_queue_post=True,
                     updated_at=NOW))
    db.commit()

    busy = queue_service.busy_until(db, shop, NOW)
    check('пост занят до конца её работ',
          busy == NOW + timedelta(minutes=40), str(busy))

    times = queue_service.forecast(db, shop, NOW)
    check('ждущего зовут после неё',
          times[first.id] >= NOW + timedelta(minutes=40),
          str(times[first.id]))

    print()
    print('=== Обычная машина пост очереди не занимает ===')
    db.query(OpenOrder).delete()
    db.add(OpenOrder(shop_id=shop.id, local_id=78, license_plate='О777ОО77',
                     state='work', started_at=NOW, planned_minutes=40,
                     on_queue_post=False, updated_at=NOW))
    db.commit()

    check('пост свободен', queue_service.busy_until(db, shop, NOW) is None,
          str(queue_service.busy_until(db, shop, NOW)))

    print()
    print('=== Названное время уехало — человеку говорят ===')
    db.query(OpenOrder).delete()
    db.commit()

    queue_service.remember_promise(db, shop, NOW)
    was = first.promised_at
    check('время запомнили', was is not None, str(was))

    # Пост заняли живой машиной надолго — время ждущего уехало за
    # то, что мы ему называли
    db.add(OpenOrder(shop_id=shop.id, local_id=79, license_plate='Х555ХХ99',
                     state='work', started_at=NOW, planned_minutes=120,
                     on_queue_post=True, updated_at=NOW))
    db.commit()

    slipped = queue_service.remember_promise(db, shop, NOW)
    check('заметили сдвиг', len(slipped) == 1, str(len(slipped)))
    check('именно у ждущего', slipped[0][0].id == first.id)
    check('и видно, с какого на какое',
          slipped[0][2] > slipped[0][1], f'{slipped[0][1]} -> {slipped[0][2]}')

    print()
    print('=== Мелкий сдвиг человека не трогает ===')
    # «Ваше время сдвинулось на три минуты» — это раздражение, а не
    # помощь: работа идёт живыми людьми
    quiet = queue_service.remember_promise(db, shop, NOW)
    check('второй раз о том же не говорим', quiet == [], str(quiet))

    print()
    print('=== Дважды в очередь не встать ===')
    twice = None
    try:
        queue_service.join(db, shop, people[0], now=NOW)
    except queue_service.QueueError as e:
        twice = str(e)
    check('отказано', twice is not None, str(twice))

    print()
    print('=== Клиенту называют время приезда, а не черёд ===')
    # Разницу в двадцать минут человек должен видеть, а не держать
    # в голове
    turn = NOW.replace(microsecond=0) + timedelta(hours=1)
    come = queue_service.when_text(db, shop, turn)
    check('время со скидкой на запас',
          come == (turn - timedelta(minutes=20)).strftime('%H:%M'), come)

    print()
    print('=== Приехавшего берём сразу, не дожидаясь его времени ===')
    # Он здесь, машина у ворот. Держать его до названного часа, когда
    # пост свободен, — это простой на ровном месте
    from app.models import QueueTicket as T

    db.query(T).delete()

    # Пост очереди свободен — иначе приехавшего честно не на что
    # поставить, и это правильно
    db.query(OpenOrder).delete()
    db.commit()

    check('пост очереди свободен',
          queue_service.busy_until(db, shop, NOW) is None,
          str(queue_service.busy_until(db, shop, NOW)))

    early = queue_service.join(db, shop, people[0], plate='Е777ЕЕ77', now=NOW)
    check('время назначено через час',
          early.eta_at == NOW + timedelta(minutes=60), str(early.eta_at))

    queue_service.arrived(db, shop, early, now=NOW + timedelta(minutes=3))
    times = queue_service.forecast(db, shop, NOW + timedelta(minutes=3))
    check('но взять можно сразу',
          times[early.id] <= NOW + timedelta(minutes=4), str(times[early.id]))

    ready = queue_service.next_up(db, shop, NOW + timedelta(minutes=3))
    check('он и следующий на пост', ready.id == early.id,
          str(ready.license_plate))

    queue_service.leave(db, early)

    print()
    print('=== Постов под очередь нет — встать нельзя ===')
    shop_settings.set_value(db, 'queue_posts', '0', shop=shop)
    check('очередь выключена', queue_service.enabled(db, shop) is False)

    off = None
    try:
        queue_service.join(db, shop, people[3], now=NOW)
    except queue_service.QueueError as e:
        off = str(e)
    check('отказано', off is not None, str(off))

    db.close()

finish()
