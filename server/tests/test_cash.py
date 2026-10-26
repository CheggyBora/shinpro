"""
Касса: ордера из цеха и раздел дашборда «Касса» (docs/cash.md).

  · ордера приходят в обмене и обновляются по uid точки; повтор — не дубль;
  · старая программа без cash_orders и полей кассы у смены — обмен как раньше;
  · кривой ордер (вид, способ, сумма, uid) пропускается и не роняет обмен;
  · поля кассы смены: прислали — записали, не прислали — не тронули;
  · дашборд: остаток сейчас (открытая смена — «должно быть», закрытая —
    пересчитанное), ордера периода, итоги по статьям с вычтенными
    отменами, безнал отдельно, смены с расхождениями;
  · без права на выручку — отказ; чужая точка — 404; ордер чужой точки
    не виден и не затирается;
  · удаление точки забирает её ордера.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_cash_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-51'
ADMIN_PHONE = '+7 916 555-12-51'

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-cash'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-cash'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import CashOrder, Shop, ShopShift
from app.services import tenancy

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


class CodeCatcher(logging.Handler):
    def __init__(self):
        super().__init__()
        self.code = None

    def emit(self, record):
        message = record.getMessage()
        if 'код' in message:
            self.code = message.strip().split()[-1]


catcher = CodeCatcher()
logging.getLogger('tire_server').addHandler(catcher)

KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify',
                      json={'phone': phone, 'code': catcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def order(uid, kind='out', number=1, category='Вода', amount=1000.0,
          method='cash', **extra):
    row = {'uid': uid, 'kind': kind, 'number': number, 'category': category,
           'amount': amount, 'method': method, 'note': 'Вода «Родник»',
           'employee_local_id': 2, 'shift_local_id': 41,
           'created_at': '2026-10-26T15:00:00', 'reverses_uid': None,
           'payout_local_id': None, 'changed_at': '2026-10-26T15:00:01'}
    row.update(extra)
    return row


def orders_of(shop_id):
    db = SessionLocal()
    try:
        return {row.uid: row for row in db.query(CashOrder).filter(
            CashOrder.shop_id == shop_id).all()}
    finally:
        db.close()


def shift_of(shop_id, local_id):
    db = SessionLocal()
    try:
        return db.query(ShopShift).filter(
            ShopShift.shop_id == shop_id,
            ShopShift.local_id == local_id).first()
    finally:
        db.close()


PERIOD = 'from=2026-10-20&to=2026-10-27'

with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4832')
    http.post('/staff/people', headers=owner, json={
        'phone': ADMIN_PHONE, 'name': 'Ольга', 'role': 'admin',
        'permissions': ['orders']})
    admin = enter(http, ADMIN_PHONE, '5821')

    db = SessionLocal()
    shop = db.query(Shop).first()
    shop_id, slug = shop.id, shop.slug
    other, other_key = tenancy.add_shop(db, shop.account, 'РИФ на Южной')
    other_id = other.id
    _, stranger, stranger_key = tenancy.create_account(db, 'Чужой шиномонтаж')
    stranger_shop_id = stranger.id
    db.close()
    OTHER = {'X-Sync-Key': other_key}
    STRANGER = {'X-Sync-Key': stranger_key}

    print('=== Старая программа: без кассы ===')
    answer = http.post('/sync/push', headers=KEY, json={
        'employees': [{'local_id': 2, 'name': 'Андрей'}],
        'shifts': [{'local_id': 40, 'started_at': '2026-10-25T09:00:00',
                    'ended_at': '2026-10-25T21:00:00', 'status': 'closed'}]})
    check('обмен без cash_orders принят', answer.status_code == 200,
          answer.text[:200])
    check('ордеров ноль', answer.json().get('cash_orders') == 0)
    row = shift_of(shop_id, 40)
    check('у старой смены касса пустая, а не ноль',
          row.cash_start is None and row.cash_expected is None
          and row.cash_counted is None and row.cash_diff is None)

    print()
    print('=== Новая программа: ордера и пересчёт ===')
    answer = http.post('/sync/push', headers=KEY, json={
        'shifts': [
            {'local_id': 40, 'started_at': '2026-10-25T09:00:00',
             'ended_at': '2026-10-25T21:00:00', 'status': 'closed',
             'cash_start': 5000, 'cash_expected': 19450, 'cash_counted': 19250,
             'cash_diff': -200, 'cash_diff_reason': 'не нашли'},
            {'local_id': 41, 'started_at': '2026-10-26T09:00:00',
             'status': 'open', 'cash_start': 19250, 'cash_expected': 21000.5,
             'cash_counted': None, 'cash_diff': None,
             'cash_diff_reason': None},
        ],
        'cash_orders': [
            order('o-water', number=32, amount=1000),
            order('o-cons', number=31, category='Расходники', amount=1850,
                  created_at='2026-10-26T13:30:00'),
            order('o-salary', number=33, category='Зарплата', amount=4000,
                  payout_local_id=7, created_at='2026-10-26T18:10:00'),
            order('o-card', number=34, category='Зарплата', amount=3500,
                  method='noncash', payout_local_id=8,
                  created_at='2026-10-26T18:12:00'),
            order('i-change', kind='in', number=14, category='Внесение',
                  amount='3 000,00', created_at='2026-10-26T10:15:00'),
            # Отменили расход на воду: обратный ордер того же вида
            order('o-water-back', number=35, amount=1000,
                  reverses_uid='o-water', employee_local_id=3,
                  created_at='2026-10-26T16:00:00'),
            # Мусор
            order('o-bad-kind', kind='sideways'),
            order('o-neg', amount=-50),
            order('o-nan', amount='NaN'),
            order('o-text', amount='много'),
            order('', number=99),
            {'kind': 'out', 'amount': 1},
            'не ордер',
            order('o-odd-method', method='bitcoin', amount=10,
                  category='Прочее', created_at='не дата'),
        ]})
    check('обмен принят', answer.status_code == 200, answer.text[:300])
    data = answer.json()
    check('принято семь ордеров', data.get('cash_orders') == 7,
          str(data.get('cash_orders')))
    check('мусор назван в ответе',
          {'o-bad-kind', 'o-neg', 'o-nan', 'o-text'} <= set(data.get('cash_rejected', [])),
          str(data.get('cash_rejected')))
    stored = orders_of(shop_id)
    check('в базе семь ордеров', len(stored) == 7, str(sorted(stored)))
    check('«3 000,00» — число', stored['i-change'].amount == 3000.0,
          str(stored['i-change'].amount))
    check('непонятный способ — наличные', stored['o-odd-method'].method == 'cash')
    check('кривая дата — время приёма, а не пусто',
          stored['o-odd-method'].created_at is not None)
    check('поля ордера на месте',
          stored['o-water'].number == 32 and stored['o-water'].category == 'Вода'
          and stored['o-water'].note == 'Вода «Родник»'
          and stored['o-water'].employee_local_id == 2
          and stored['o-water'].shift_local_id == 41
          and stored['o-salary'].payout_local_id == 7
          and stored['o-water-back'].reverses_uid == 'o-water'
          and stored['o-water'].changed_at.isoformat() == '2026-10-26T15:00:01')
    closed = shift_of(shop_id, 40)
    check('пересчёт закрытой смены записан',
          closed.cash_start == 5000 and closed.cash_expected == 19450
          and closed.cash_counted == 19250 and closed.cash_diff == -200
          and closed.cash_diff_reason == 'не нашли')
    opened = shift_of(shop_id, 41)
    check('у открытой смены — текущий остаток',
          opened.cash_expected == 21000.5 and opened.cash_counted is None)

    print()
    print('=== Повтор — обновление, а не дубль ===')
    answer = http.post('/sync/push', headers=KEY, json={'cash_orders': [
        order('o-water', number=32, amount=1100, note='Вода, 7 бутылей'),
        order('o-water', number=32, amount=1000, note='Вода, 6 бутылей')]})
    check('принято', answer.status_code == 200 and answer.json()['cash_orders'] == 2)
    stored = orders_of(shop_id)
    check('дубля нет', len(stored) == 7)
    check('последняя присылка главнее', stored['o-water'].amount == 1000
          and stored['o-water'].note == 'Вода, 6 бутылей')

    answer = http.post('/sync/push', headers=KEY, json={'shifts': [
        {'local_id': 40, 'started_at': '2026-10-25T09:00:00',
         'ended_at': '2026-10-25T21:00:00', 'status': 'closed'}]})
    check('смена без полей кассы — пересчёт не стёрт',
          shift_of(shop_id, 40).cash_counted == 19250)
    answer = http.post('/sync/push', headers=KEY, json={'shifts': [
        {'local_id': 40, 'started_at': '2026-10-25T09:00:00',
         'status': 'closed', 'cash_counted': 'abc', 'cash_diff': 'inf',
         'cash_diff_reason': 'x' * 400}]})
    check('кривые числа смены не роняют обмен', answer.status_code == 200,
          answer.text[:200])
    row = shift_of(shop_id, 40)
    check('кривое число — пусто, причина обрезана',
          row.cash_counted is None and row.cash_diff is None
          and len(row.cash_diff_reason) == 255)
    http.post('/sync/push', headers=KEY, json={'shifts': [
        {'local_id': 40, 'started_at': '2026-10-25T09:00:00',
         'ended_at': '2026-10-25T21:00:00', 'status': 'closed',
         'cash_start': 5000, 'cash_expected': 19450, 'cash_counted': 19250,
         'cash_diff': -200, 'cash_diff_reason': 'не нашли'}]})

    print()
    print('=== Чужие точки ===')
    answer = http.post('/sync/push', headers=OTHER, json={
        'shifts': [{'local_id': 41, 'started_at': '2026-10-26T08:00:00',
                    'status': 'open', 'cash_start': 1000,
                    'cash_expected': 1500}],
        'cash_orders': [order('o-water', number=1, amount=77, category='Вода'),
                        order('o-rent', number=2, amount=20000,
                              category='Аренда')]})
    check('вторая точка присылает свою кассу', answer.status_code == 200
          and answer.json()['cash_orders'] == 2)
    check('тот же uid у другой точки — свой ордер',
          orders_of(shop_id)['o-water'].amount == 1000
          and orders_of(other_id)['o-water'].amount == 77)
    http.post('/sync/push', headers=STRANGER, json={
        'cash_orders': [order('o-x', amount=5)]})

    print()
    print('=== Дашборд ===')
    answer = http.get('/dashboard/cash')
    check('без входа — 401', answer.status_code == 401, str(answer.status_code))
    answer = http.get(f'/dashboard/cash?{PERIOD}', headers=admin)
    check('без права на выручку — 403', answer.status_code == 403,
          str(answer.status_code))
    answer = http.get(f'/dashboard/cash?shop={stranger_shop_id}', headers=owner)
    check('точка чужого заказчика — 404', answer.status_code == 404)

    answer = http.get(f'/dashboard/cash?shop={slug}&{PERIOD}', headers=owner)
    check('касса отдаётся', answer.status_code == 200, answer.text[:200])
    data = answer.json()
    now = data['now']
    check('сейчас в кассе — открытая смена',
          len(now) == 1 and now[0]['cash_expected'] == 21000.5
          and now[0]['shop_id'] == shop_id and now[0]['shop_name']
          and now[0]['shift_started_at'].startswith('2026-10-26T09:00'),
          str(now))
    # Ордер с кривой датой лёг на время приёма — от сегодняшнего числа
    # зависит, попал ли он в период, поэтому его не считаем
    uids = [row['uid'] for row in data['orders'] if row['uid'] != 'o-odd-method']
    check('ордера периода, новые сверху',
          uids[:3] == ['o-card', 'o-salary', 'o-water-back']
          and len(uids) == 6, str(uids))
    by_uid = {row['uid']: row for row in data['orders']}
    check('отменённый ордер знает, кто его отменил',
          by_uid['o-water']['reversed_by_uid'] == 'o-water-back'
          and by_uid['o-water']['reversed_by_number'] == 35
          and by_uid['o-water']['reversed_by_title'] == '№3',
          str(by_uid['o-water']))
    check('отмена знает, что отменила',
          by_uid['o-water-back']['reverses_number'] == 32)
    check('у ордера имя сотрудника',
          by_uid['o-cons']['employee_title'].startswith('Андрей'),
          str(by_uid['o-cons']['employee_title']))
    totals = data['totals']
    check('отмена вычтена: вода обнулилась и пропала из итогов',
          'Вода' not in totals['out'], str(totals))
    check('расход по статьям наличными',
          totals['out'].get('Зарплата') == 4000
          and totals['out'].get('Расходники') == 1850
          and totals['out'].get('Без статьи') is None
          and totals['out'].get('Вода') is None, str(totals['out']))
    check('приход по статьям', totals['in'] == {'Внесение': 3000.0},
          str(totals['in']))
    check('безнал отдельно', totals['noncash_out'] == 3500,
          str(totals['noncash_out']))
    shifts = data['shifts']
    check('смены с пересчётом', [row['local_id'] for row in shifts] == [41, 40],
          str(shifts))
    check('расхождение и причина',
          shifts[1]['cash_diff'] == -200 and shifts[1]['cash_counted'] == 19250
          and shifts[1]['cash_expected'] == 19450
          and shifts[1]['cash_diff_reason'] == 'не нашли'
          and shifts[1]['shop_name'], str(shifts[1]))

    answer = http.get('/dashboard/cash?from=2026-10-26&to=2026-10-26',
                      headers=owner).json()
    check('без выбора точки — все точки сети',
          {row['shop_id'] for row in answer['now']} == {shop_id, other_id}
          and sum(row['cash_expected'] for row in answer['now']) == 22500.5,
          str(answer['now']))
    check('и их ордера', {row['shop_id'] for row in answer['orders']}
          == {shop_id, other_id})
    check('чужого заказчика нет',
          all(row['shop_id'] != stranger_shop_id for row in answer['orders']))
    check('итоги сложились по точкам',
          answer['totals']['out'].get('Вода') == 77
          and answer['totals']['out'].get('Аренда') == 20000,
          str(answer['totals']))

    # Смену закрыли — в кассе то, что пересчитали
    http.post('/sync/push', headers=KEY, json={'shifts': [
        {'local_id': 41, 'started_at': '2026-10-26T09:00:00',
         'ended_at': '2026-10-26T21:00:00', 'status': 'closed',
         'cash_start': 19250, 'cash_expected': 21000.5,
         'cash_counted': 21100, 'cash_diff': 99.5,
         'cash_diff_reason': 'сдача'}]})
    now = http.get(f'/dashboard/cash?shop={slug}&{PERIOD}',
                   headers=owner).json()['now']
    check('смена закрыта — в кассе пересчитанное',
          now[0]['cash_expected'] == 21100 and now[0]['shift_started_at'] is None
          and now[0]['shift_open'] is False, str(now))

    print()
    print('=== Удаление точки забирает и ордера ===')
    db = SessionLocal()
    tenancy.drop_shop(db, db.get(Shop, other_id))
    db.close()
    check('ордеров удалённой точки нет', not orders_of(other_id))
    check('свои на месте', len(orders_of(shop_id)) == 7)

finish()
