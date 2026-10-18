"""
Живая очередь по QR: страница у въезда и обмен с цехом.

  · без связи с цехом место по QR не даём — человек ждал бы в очереди,
    которую никто не видит;
  · место лежит в куке: обновил страницу — он на своём месте;
  · одна машина — одно место, чужой телефон не снимет и не займёт его;
  · цех забирает новые места и присылает место, время и пост;
  · позвали — вошедшему в кабинет уходит сообщение, на странице — пост
    и схема;
  · диаметр из онлайн-записи доходит до цеха.
"""
import os
import sys
import tempfile
from datetime import timedelta

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_live_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-live'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-live'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Appointment, Client, Shop
from app.models.live import LiveTicket
from app.security import create_token
from app.utils import now as shop_now
import app.api.live as live_api

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


told = []


def fake_send(db, client, account, kind, text, about=None, about_id=None):
    told.append((client.phone, text))
    return 'telegram'


live_api.notices.send_now = fake_send

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}
FORM = {'license_plate': 'а123вв777', 'phone': '+7 909 901-89-31',
        'wheel_diameter': 'R16', 'wheels_assembled': True}

with TestClient(app) as http:
    db = SessionLocal()
    shop = db.query(Shop).first()
    slug = shop.slug
    account_id, shop_id = shop.account_id, shop.id
    shop.last_sync_at = None
    db.commit()
    db.close()
    q = f'?shop={slug}'

    print('=== Страницы открываются ===')
    page = http.get(f'/z/{slug}/q')
    check('страница очереди', page.status_code == 200 and 'Встать в очередь' in page.text)
    scene = http.get('/parking')
    check('схема площадки', scene.status_code == 200 and 'THREE' in scene.text)

    print()
    print('=== Цех без связи — по QR не встать ===')
    state = http.get('/live/state' + q).json()
    check('страница знает, что связи нет', state['online'] is False, str(state))
    refused = http.post('/live/join' + q, json=FORM)
    check('отказ', refused.status_code == 503, str(refused.status_code))
    check('сказано идти к приёмщику', 'приёмщик' in refused.json()['detail'])

    # Цех вышел на связь
    http.post('/sync/live', headers=KEY, json={'entries': []})

    print()
    print('=== Встать в очередь ===')
    joined = http.post('/live/join' + q, json=FORM)
    check('принято', joined.status_code == 200, joined.text)
    check('номер приведён к виду', joined.json()['license_plate'] == 'А123ВВ777')
    check('кука с местом', any(name.startswith('tire_live_') for name in list(joined.cookies) + list(http.cookies)))
    check('цех ещё не видел', joined.json()['seen_by_shop'] is False)

    mine = http.get('/live/state' + q).json()['ticket']
    check('обновил страницу — место на месте', mine and mine['license_plate'] == 'А123ВВ777', str(mine))

    again = http.post('/live/join' + q, json=FORM)
    db = SessionLocal()
    count = db.query(LiveTicket).count()
    db.close()
    check('тот же номер и телефон — то же место', again.status_code == 200 and count == 1, str(count))

    stranger = TestClient(app)
    other = stranger.post('/live/join' + q, json=dict(FORM, phone='79160000000'))
    check('с чужим телефоном — отказ', other.status_code == 409, str(other.status_code))
    check('чужой не видит чужое место',
          stranger.get('/live/state' + q).json()['ticket'] is None)

    print()
    print('=== Вошедший в кабинет ===')
    db = SessionLocal()
    owner = Client(account_id=account_id, phone='79160000001', name='Пётр',
                   telegram_chat_id='555')
    db.add(owner)
    db.commit()
    token = create_token(owner.id)
    db.close()
    cabinet = TestClient(app)
    auth = {'Authorization': f'Bearer {token}'}
    st = cabinet.get('/live/state' + q, headers=auth).json()
    check('страница знает, что он вошёл', st['signed_in'] and st['phone'] == '79160000001', str(st))
    vip = cabinet.post('/live/join' + q, headers=auth,
                       json={'license_plate': 'К900ОР99', 'wheel_diameter': 'R17',
                             'wheels_assembled': False})
    check('встал без телефона в форме — взят из кабинета', vip.status_code == 200, vip.text)

    print()
    print('=== Цех забирает новые места ===')
    answer = http.post('/sync/live', headers=KEY, json={'entries': []}).json()
    plates = sorted(n['license_plate'] for n in answer['new'])
    check('цех получил оба места', plates == ['А123ВВ777', 'К900ОР99'], str(answer))
    first = next(n for n in answer['new'] if n['license_plate'] == 'А123ВВ777')
    check('с диаметром и колёсами', first['wheel_diameter'] == 'R16' and first['wheels_assembled'] is True)
    second = next(n for n in answer['new'] if n['license_plate'] == 'К900ОР99')

    eta = (shop_now() + timedelta(minutes=25)).replace(microsecond=0).isoformat()
    answer = http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'waiting',
         'place': 2, 'eta_at': eta},
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'waiting',
         'place': 1, 'eta_at': eta},
    ]}).json()
    check('второй раз не отдаёт как новые', answer['new'] == [], str(answer))
    mine = http.get('/live/state' + q).json()['ticket']
    check('видно место', mine['place'] == 2 and mine['seen_by_shop'], str(mine))
    check('видно время', mine['eta'] == eta[11:16], str(mine))

    print()
    print('=== Позвали ===')
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'called',
         'place': None, 'post_number': 3},
    ]})
    check('вошедшему ушло сообщение', told and told[-1][0] == '79160000001' and 'пост 3' in told[-1][1], str(told))
    vip_state = cabinet.get('/live/state' + q, headers=auth).json()['ticket']
    check('на странице — пост и схема',
          vip_state['post'] == 3 and vip_state['scene'] == '/parking?client=1#post3', str(vip_state))
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'called', 'post_number': 3},
    ]})
    check('повторный обмен не шлёт второй раз', len(told) == 1, str(told))

    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'called', 'post_number': 2},
    ]})
    check('без входа сообщения нет — только страница', len(told) == 1)
    check('на странице — пост', http.get('/live/state' + q).json()['ticket']['post'] == 2)

    print()
    print('=== Ушёл сам ===')
    left = http.post('/live/leave' + q).json()
    check('принято', left['left'] is True)
    answer = http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'called', 'post_number': 2},
    ]}).json()
    check('цех узнал, что ушёл', first['server_id'] in answer['left'], str(answer))
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 11, 'server_id': first['server_id'], 'state': 'left'},
    ]})
    check('место закрыто — страница предлагает встать снова',
          http.get('/live/state' + q).json()['ticket'] is None)

    print()
    print('=== Обслужили — можно встать ещё раз ===')
    http.post('/sync/live', headers=KEY, json={'entries': [
        {'local_id': 12, 'server_id': second['server_id'], 'state': 'done'},
    ]})
    done = cabinet.get('/live/state' + q, headers=auth).json()['ticket']
    check('видно «готово»', done and done['state'] == 'done', str(done))
    cabinet.post('/live/leave' + q, headers=auth)
    check('после «ещё раз» место забыто',
          cabinet.get('/live/state' + q, headers=auth).json()['ticket'] is None)

    print()
    print('=== Чужой ключ обмена ===')
    bad = http.post('/sync/live', headers={'X-Sync-Key': 'wrong'}, json={'entries': []})
    check('отказ', bad.status_code in (401, 403), str(bad.status_code))

    print()
    print('=== Диаметр из записи доходит до цеха ===')
    db = SessionLocal()
    at = (shop_now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    db.add(Appointment(shop_id=shop_id, scheduled_at=at, duration_minutes=30,
                       license_plate='В001ВВ77', wheels_assembled=True,
                       wheel_diameter='R18', status='scheduled'))
    db.commit()
    db.close()
    day = http.get(f'/sync/appointments?day={at.date().isoformat()}', headers=KEY).json()
    row = next(a for a in day['appointments'] if a['license_plate'] == 'В001ВВ77')
    check('диаметр в обмене', row.get('wheel_diameter') == 'R18', str(row))
    check('колёса в обмене', row.get('wheels_assembled') is True, str(row))

    print()
    print('=== Запись: «подъезжайте», «Я на месте», вызов на пост ===')
    from app.models import Notice, KIND_ARRIVE, KIND_LATE
    from app.services import notices as notices_service
    db = SessionLocal()
    soon = (shop_now() + timedelta(minutes=40)).replace(second=0, microsecond=0)
    person = db.query(Client).filter(Client.phone == '79160000001').first()
    visit = Appointment(shop_id=shop_id, client_id=person.id, scheduled_at=soon,
                        duration_minutes=30, license_plate='Т555ТТ77',
                        wheels_assembled=True, wheel_diameter='R16', status='scheduled')
    db.add(visit)
    db.commit()
    notices_service.plan_for_appointment(db, person, 'РИФ', visit)
    kinds = sorted(n.kind for n in db.query(Notice).filter(
        Notice.about_id == visit.id, Notice.about == 'appointment').all())
    check('будет «подъезжайте за 10 минут»', KIND_ARRIVE in kinds, str(kinds))
    check('и на случай опоздания', KIND_LATE in kinds, str(kinds))
    arrive = db.query(Notice).filter(Notice.about_id == visit.id, Notice.kind == KIND_ARRIVE).first()
    check('«подъезжайте» — за полчаса', arrive.send_at == soon - timedelta(minutes=30), str(arrive.send_at))
    check('в тексте — к какому времени', (soon - timedelta(minutes=10)).strftime('%H:%M') in arrive.text, arrive.text)
    late = db.query(Notice).filter(Notice.about_id == visit.id, Notice.kind == KIND_LATE).first()
    check('«опоздали» — через 10 минут после записи', late.send_at == soon + timedelta(minutes=10), str(late.send_at))
    visit_id = visit.id
    person_id = person.id
    db.close()

    mine = cabinet.get('/booking/my', headers=auth).json()
    row = next(a for a in mine if a['id'] == visit_id)
    check('за 40 минут уже можно «Я на месте»', row['can_check_in'] is True, str(row))
    here = cabinet.post(f'/booking/{visit_id}/here', headers=auth)
    check('отметился', here.status_code == 200 and here.json()['on_site'] is True, here.text)
    db = SessionLocal()
    waiting = [n.kind for n in db.query(Notice).filter(
        Notice.about_id == visit_id, Notice.state == 'waiting').all()]
    db.close()
    check('«подъезжайте» и «опоздали» отменены', KIND_ARRIVE not in waiting and KIND_LATE not in waiting, str(waiting))

    day = http.get(f'/sync/appointments?day={soon.date().isoformat()}', headers=KEY).json()
    synced = next(a for a in day['appointments'] if a['id'] == visit_id)
    check('цех видит «на месте»', synced['on_site'] is True, str(synced))

    before = len(told)
    called = http.post(f'/sync/appointments/{visit_id}/call', headers=KEY, json={'post': 4})
    check('цех позвал', called.status_code == 200, called.text)
    check('клиенту ушло «проезжайте на пост 4»',
          len(told) == before + 1 and 'пост 4' in told[-1][1], str(told[-1:]))
    row = next(a for a in cabinet.get('/booking/my', headers=auth).json() if a['id'] == visit_id)
    check('в кабинете — пост и схема', row['called_post'] == 4 and row['scene'] == '/parking?client=1#post4', str(row))

    db = SessionLocal()
    far = Appointment(shop_id=shop_id, client_id=person_id,
                      scheduled_at=shop_now() + timedelta(hours=5), duration_minutes=30,
                      license_plate='Т666ТТ77', status='scheduled')
    db.add(far)
    db.commit()
    far_id = far.id
    db.close()
    early = cabinet.post(f'/booking/{far_id}/here', headers=auth)
    check('за 5 часов «Я на месте» не нажать', early.status_code == 400, str(early.status_code))

    print()
    print('=== Приёмщик отметил «на месте» — свободного поста нет ===')
    db = SessionLocal()
    walkin = Appointment(shop_id=shop_id, client_id=person_id,
                         scheduled_at=shop_now() + timedelta(minutes=5), duration_minutes=30,
                         license_plate='Х777ХХ77', status='scheduled')
    db.add(walkin)
    db.commit()
    notices_service.plan_for_appointment(db, db.get(Client, person_id), 'РИФ', walkin)
    walkin_id = walkin.id
    db.close()
    marked = http.patch(f'/sync/appointments/{walkin_id}', headers=KEY, json={'on_site': True})
    check('принято', marked.status_code == 200, marked.text)
    db = SessionLocal()
    row = db.get(Appointment, walkin_id)
    check('на месте', row.on_site_at is not None)
    pending = [n.kind for n in db.query(Notice).filter(
        Notice.about_id == walkin_id, Notice.state == 'waiting').all()]
    check('«опоздали» не уйдёт', KIND_LATE not in pending, str(pending))
    db.close()

    print()
    print('=== Не дождались — вызов снят, «на месте» тоже ===')
    released = http.patch(f'/sync/appointments/{visit_id}', headers=KEY, json={'on_site': False})
    check('принято', released.status_code == 200, released.text)
    row = next(a for a in cabinet.get('/booking/my', headers=auth).json() if a['id'] == visit_id)
    check('поста больше нет, можно снова «Я на месте»',
          row['called_post'] is None and row['on_site'] is False and row['can_check_in'] is True, str(row))

    print()
    print('=== Перенос записи — «на месте» сброшен, напоминания заново ===')
    later = (shop_now() + timedelta(hours=3)).replace(second=0, microsecond=0)
    http.patch(f'/sync/appointments/{walkin_id}', headers=KEY, json={'on_site': True})
    moved = http.patch(f'/sync/appointments/{walkin_id}', headers=KEY,
                       json={'scheduled_at': later.isoformat()})
    check('перенесли', moved.status_code == 200, moved.text)
    db = SessionLocal()
    row = db.get(Appointment, walkin_id)
    check('«на месте» и вызов сброшены', row.on_site_at is None and row.called_post is None)
    planned = {n.kind: n.send_at for n in db.query(Notice).filter(
        Notice.about_id == walkin_id, Notice.state == 'waiting').all()}
    check('«подъезжайте» по новому времени',
          planned.get(KIND_ARRIVE) == later - timedelta(minutes=30), str(planned))
    check('«опоздали» по новому времени',
          planned.get(KIND_LATE) == later + timedelta(minutes=10), str(planned))
    db.close()

    print()
    print('=== Напоминание в будущем ждёт, даже если канала пока нет ===')
    db = SessionLocal()
    nobody = Client(account_id=account_id, phone='79160000999', name='Без канала')
    db.add(nobody)
    db.commit()
    future = notices_service.add(db, nobody, KIND_ARRIVE, 'тест',
                                 send_at=shop_now() + timedelta(hours=2))
    now_one = notices_service.add(db, nobody, KIND_ARRIVE, 'тест')
    check('отложенное — ждёт', future.state == 'waiting', future.state)
    check('срочное без канала — пропущено', now_one.state == 'skipped', now_one.state)
    db.close()

    print()
    print('=== Цех не принял место — оно закрыто ===')
    live_api._joins.clear()
    first = http.post('/live/join' + q, json={**FORM, 'license_plate': 'Р100РР77',
                                              'phone': '79160000500'})
    check('встал', first.status_code == 200, first.text)
    ticket_id = http.post('/sync/live', headers=KEY, json={'entries': []}).json()['new'][-1]['server_id']
    http.post('/sync/live', headers=KEY, json={'entries': [], 'rejected': [ticket_id]})
    db = SessionLocal()
    check('закрыто', db.get(LiveTicket, ticket_id).state == 'left')
    db.close()

    print()
    print('=== Одно место на телефон и защита от заваливания ===')
    live_api._joins.clear()
    one = http.post('/live/join' + q, json={**FORM, 'license_plate': 'Р200РР77',
                                            'phone': '79160000600'})
    again = http.post('/live/join' + q, json={**FORM, 'license_plate': 'Р201РР77',
                                              'phone': '79160000601'})
    check('с той же кукой — то же место', again.json().get('license_plate') == 'Р200РР77', again.text)
    http.cookies.clear()
    same_phone = http.post('/live/join' + q, json={**FORM, 'license_plate': 'Р202РР77',
                                                   'phone': '79160000600'})
    check('тот же телефон, другая машина — отказ', same_phone.status_code == 409, same_phone.text)
    answers = []
    for n in range(10):
        http.cookies.clear()
        answers.append(http.post('/live/join' + q, json={
            **FORM, 'license_plate': f'С{300 + n}СС77', 'phone': f'791600007{n:02d}'}).status_code)
    check('с одного адреса — не больше 8 в час', 429 in answers, str(answers))
    live_api._joins.clear()

    print()
    print('=== Цех ушёл сам, а место у цеха ещё живо — цеху скажут ===')
    http.cookies.clear()
    mine = http.post('/live/join' + q, json={**FORM, 'license_plate': 'У100УУ77',
                                             'phone': '79160000800'})
    sid = mine.json()['id'] if 'id' in mine.json() else None
    fresh = http.post('/sync/live', headers=KEY, json={'entries': []}).json()['new']
    sid = next(t['server_id'] for t in fresh if t['license_plate'] == 'У100УУ77')
    http.post('/live/leave' + q)
    answer = http.post('/sync/live', headers=KEY, json={'entries': [{
        'local_id': 77, 'server_id': sid, 'state': 'waiting', 'place': 1,
        'eta_at': None, 'post_number': None}]}).json()
    check('в ответе — «ушёл»', sid in answer['left'], str(answer))
    state = http.get('/live/state' + q).json()
    check('на странице места уже нет', state['ticket'] is None, str(state))

    print()
    print('=== Не забранное цехом полчаса — закрыто ===')
    live_api._joins.clear()
    http.cookies.clear()
    old_one = http.post('/live/join' + q, json={**FORM, 'license_plate': 'Ф100ФФ77',
                                                'phone': '79160000900'})
    db = SessionLocal()
    stale = db.query(LiveTicket).filter(LiveTicket.license_plate == 'Ф100ФФ77').first()
    stale.created_at = shop_now() - timedelta(hours=10)
    stale_id = stale.id
    db.commit()
    db.close()
    answer = http.post('/sync/live', headers=KEY, json={'entries': []}).json()
    check('цеху не отдано', stale_id not in [t['server_id'] for t in answer['new']], str(answer))
    db = SessionLocal()
    check('закрыто', db.get(LiveTicket, stale_id).state == 'left')
    db.close()

    print()
    print('=== Не сезон: очередь выключена ===')
    http.post('/sync/live', headers=KEY, json={'entries': [], 'enabled': False})
    state = http.get('/live/state' + q).json()
    check('страница знает', state['enabled'] is False, str(state))
    http.cookies.clear()
    refused = http.post('/live/join' + q, json={**FORM, 'license_plate': 'Ц100ЦЦ77',
                                                'phone': '79160000950'})
    check('встать нельзя', refused.status_code == 409, refused.text)
    row = next(a for a in cabinet.get('/booking/my', headers=auth).json() if a['id'] == visit_id)
    check('«Я на месте» не показываем', row['can_check_in'] is False, str(row))
    db = SessionLocal()
    off_visit = Appointment(shop_id=shop_id, client_id=person_id,
                            scheduled_at=shop_now() + timedelta(hours=2), duration_minutes=30,
                            license_plate='Ц200ЦЦ77', status='scheduled')
    db.add(off_visit)
    db.commit()
    made = notices_service.plan_for_appointment(db, db.get(Client, person_id), 'РИФ', off_visit)
    kinds = [n.kind for n in made]
    check('«опоздали — пост отдали очереди» не планируем', KIND_LATE not in kinds, str(kinds))
    arrive = next(n for n in made if n.kind == KIND_ARRIVE)
    check('и про «Я на месте» не пишем', 'Я на месте' not in arrive.text, arrive.text)
    db.close()
    http.post('/sync/live', headers=KEY, json={'entries': [], 'enabled': True})
    check('включили — снова можно', http.get('/live/state' + q).json()['enabled'] is True)

finish()
