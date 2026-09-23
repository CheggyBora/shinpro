"""
Оплата пользования программой.

Главное, что проверяется, — что именно закрывается, когда не заплатили.
Онлайн: кабинет, запись, дашборд. Обмен с цехом — никогда: цех
продолжает работать и досылать данные, чтобы после оплаты всё ожило
само, а не восстанавливалось руками.

И второе: срок складывается из платежей, а не правится вручную. Через
полгода на вопрос «почему стоит эта дата» должен отвечать список
платежей, а не память.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_billing_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-billing'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_BILLING_GRACE_DAYS'] = '5'

from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import SessionLocal
from app.models import Account, AccountPayment, StaffUser, Visit
from app.security import hash_secret
from app.services import billing, tenancy
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
    account, shop, sync_key = tenancy.create_account(db, 'Колесо', 'Колесо')
    account_id, shop_id, shop_slug = account.id, shop.id, shop.slug

    owner = StaffUser(account_id=account_id, phone='79099018931',
                      name='Хозяин', role='owner',
                      phone_verified_at=shop_now())
    owner.pin_hash = hash_secret('79099018931', '4831')
    db.add(owner)
    db.commit()

    print('=== Пока срок не задан, платить некому ===')
    status = billing.state(account)
    check('состояние «без оплаты»', status['state'] == billing.FREE,
          status['state'])
    check('всё открыто', status['is_open'] is True)

    print('\n=== Платёж продлевает срок ===')
    payment = billing.record_payment(db, account, 3000, months=1,
                                     comment='за сентябрь')
    check('платёж записан', payment.id is not None)
    check('сумма сохранена', payment.amount == 3000.0)
    check('срок появился', account.paid_until is not None)
    check('это примерно месяц',
          29 <= (account.paid_until - shop_now()).days <= 31,
          str((account.paid_until - shop_now()).days))
    check('видно, за какой отрезок платили',
          payment.period_to == account.paid_until)

    print('\n=== Заплатил заранее — время не сгорает ===')
    was = account.paid_until
    billing.record_payment(db, account, 3000, months=1)
    check('второй месяц лёг сверху первого',
          (account.paid_until - was).days == 30,
          str((account.paid_until - was).days))
    check('платежей теперь два',
          db.query(AccountPayment).filter(
              AccountPayment.account_id == account_id).count() == 2)

    print('\n=== Один и тот же платёж не проходит дважды ===')
    first = billing.record_payment(db, account, 3000, months=1,
                                   method='yookassa', external_id='pay-777')
    before = account.paid_until
    again = billing.record_payment(db, account, 3000, months=1,
                                   method='yookassa', external_id='pay-777')
    check('вернулась та же строка', again.id == first.id)
    check('срок не вырос второй раз', account.paid_until == before,
          f'{account.paid_until} против {before}')

    print('\n=== Срок вышел: сначала отсрочка, потом закрыто ===')
    account.paid_until = shop_now() - timedelta(days=2)
    db.commit()
    status = billing.state(account)
    check('идёт отсрочка', status['state'] == billing.GRACE, status['state'])
    check('и всё ещё открыто', status['is_open'] is True)

    account.paid_until = shop_now() - timedelta(days=10)
    db.commit()
    status = billing.state(account)
    check('отсрочка кончилась', status['state'] == billing.OVERDUE,
          status['state'])
    check('но проверка выключена — открыто', status['is_open'] is True,
          'SERVER_BILLING_ENFORCE выключен')

    print('\n=== Включаем проверку ===')
    settings.BILLING_ENFORCE = True

    check('теперь закрыто', billing.is_open(account) is False)

    closed = client.post('/staff/login', headers={'X-Shop': shop_slug},
                         json={'phone': '+7 909 901-89-31', 'pin': '4831'})
    check('в дашборд не пускает', closed.status_code == 402,
          str(closed.status_code))
    check('сказано, что цех работает как обычно',
          'цех' in closed.json()['detail'].lower(), closed.json()['detail'])

    page = client.get('/public/info', params={'shop': shop_slug})
    check('запись закрыта', page.status_code == 402, str(page.status_code))

    print('\n=== Обмен с цехом продолжает работать ===')
    answer = client.post('/sync/push', headers={'X-Sync-Key': sync_key}, json={
        'visits': [{'local_id': 1, 'visited_at': shop_now().isoformat(),
                    'total_amount': 1000.0}],
    })
    check('цех отдал данные, несмотря на долг', answer.status_code == 200,
          str(answer.status_code))

    db2 = SessionLocal()
    check('наряд лёг в базу',
          db2.query(Visit).filter(Visit.shop_id == shop_id).count() == 1)
    db2.close()

    state = client.get('/sync/state', headers={'X-Sync-Key': sync_key})
    check('и сводку получил', state.status_code == 200, str(state.status_code))

    print('\n=== Оплатили — открылось сразу ===')
    billing.record_payment(db, account, 3000, months=1)
    check('состояние снова «оплачено»',
          billing.state(account)['state'] == billing.PAID)

    opened = client.post('/staff/login', headers={'X-Shop': shop_slug},
                         json={'phone': '+7 909 901-89-31', 'pin': '4831'})
    check('дашборд пускает', opened.status_code == 200, str(opened.status_code))
    check('страница записи открылась',
          client.get('/public/info',
                     params={'shop': shop_slug}).status_code == 200)

    print('\n=== Закрытие вручную — отдельно от неоплаты ===')
    billing.block(db, account, 'по просьбе заказчика')
    status = billing.state(account)
    check('состояние «закрыт»', status['state'] == billing.BLOCKED,
          status['state'])
    check('причина сохранена', status.get('reason') == 'по просьбе заказчика')
    check('закрыт, хотя оплачено', status['is_open'] is False)

    billing.unblock(db, account)
    check('открыли обратно', billing.is_open(account) is True)

    print('\n=== Кого пора предупредить, а кто уже должен ===')
    account.paid_until = shop_now() + timedelta(days=2)
    db.commit()
    soon = billing.expiring(db, days=3)
    check('срок кончается на днях — в списке',
          any(row.id == account_id for row in soon), str(len(soon)))

    account.paid_until = shop_now() - timedelta(days=30)
    db.commit()
    check('давний долг — в списке должников',
          any(row.id == account_id for row in billing.overdue(db)))

    account.paid_until = shop_now() - timedelta(days=1)
    db.commit()
    check('вчерашний срок — ещё не должник, идёт отсрочка',
          not any(row.id == account_id for row in billing.overdue(db)))

    settings.BILLING_ENFORCE = False
    db.close()

finish()
