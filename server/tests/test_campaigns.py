"""
Напоминания, которые сервер придумывает сам: хранение и перекидка.

Эти два отличаются от остальных тем, что их никто не заказывал — и
потому ошибиться в них дороже. Проверяем:

  · о заканчивающемся хранении говорим заранее, а не в последний день;
  · о комплекте предупреждаем один раз, а не каждые пять минут;
  · о сезоне зовём в день, назначенный цехом, и один раз в год;
  · осенью и весной текст разный, а не «пора переобуваться» в обе;
  · зовём тех, кто ещё наш: чей комплект лежит и кто был за год;
  · пропавшего на три года не трогаем;
  · чужих клиентов другой точки не задеваем.

Каналы здесь не участвуют: отправка подменена, проверяется то, что
попадает в очередь.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, SERVER_DIR)

_db_path = os.path.join(tempfile.gettempdir(), 'tire_campaigns_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace('\\', '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-campaigns'
os.environ['SERVER_SYNC_KEY'] = ''
os.environ['SERVER_OWNER_PHONE'] = ''
os.environ['SERVER_MAIL_PROVIDER'] = 'log'

from datetime import timedelta

from app.database import init_db, SessionLocal
from app.models import (Client, Notice, ShopSetting, StoredSet, Visit,
                        KIND_SEASON, KIND_STORAGE,
                        ABOUT_AUTUMN, ABOUT_SPRING, SKIPPED)
from app.services import campaigns, tenancy
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

account, shop, _key = tenancy.create_account(db, 'Шиномонтаж «РИФ»')
other_shop, _other_key = tenancy.add_shop(db, account, 'РИФ на Южной')
shop_id, other_id = shop.id, other_shop.id


def setting(key, value, where=None):
    db.add(ShopSetting(shop_id=(where or shop).id, key=key, value=value))
    db.commit()


def person(phone, name, reachable=True):
    """Клиент, до которого можно дотянуться: иначе всё пропускается."""
    row = Client(account_id=account.id, phone=phone, name=name,
                 phone_verified_at=shop_now())
    if reachable:
        row.telegram_chat_id = '555' + phone[-4:]
    db.add(row)
    db.commit()
    return row


def stored_for(client, days_left, where=None, plate='А123ВВ777'):
    row = StoredSet(shop_id=(where or shop).id, client_id=client.id,
                    license_plate=plate, storage_type='шины с дисками',
                    diameter='R17', status='stored',
                    accepted_at=shop_now() - timedelta(days=150),
                    expires_at=shop_now() + timedelta(days=days_left))
    db.add(row)
    db.commit()
    return row


def visit_for(client, days_ago, where=None):
    row = Visit(shop_id=(where or shop).id, client_id=client.id,
                visited_at=shop_now() - timedelta(days=days_ago),
                total_amount=3000.0)
    db.add(row)
    db.commit()
    return row


setting('shop_name', 'Шиномонтаж «РИФ»')
setting('storage_warn_days', '7')

print('=== Хранение: за неделю предупреждаем, за месяц рано ===')
soon = person('79000000001', 'Андрей')
later = person('79000000002', 'Борис')

soon_set = stored_for(soon, days_left=3)
later_set = stored_for(later, days_left=40, plate='В222АА178')

made = campaigns.plan_storage(db, shop)
check('предупредили одного', len(made) == 1, str(len(made)))
check('именно того, у кого срок близко',
      made[0].client_id == soon.id, str(made[0].client_id))
check('это напоминание о хранении', made[0].kind == KIND_STORAGE,
      made[0].kind)
check('в тексте есть дата',
      soon_set.expires_at.strftime('%d.%m') in made[0].text, made[0].text)
check('и номер машины', 'А123ВВ777' in made[0].text, made[0].text)

print('\n=== Второй раз о том же комплекте не говорим ===')
again = campaigns.plan_storage(db, shop)
check('ничего нового', not again, str(len(again)))

print('\n=== Срок вышел — всё равно скажем, но один раз ===')
overdue = person('79000000003', 'Виктор')
overdue_set = stored_for(overdue, days_left=-5, plate='С333СС777')

made = campaigns.plan_storage(db, shop)
check('сказали просрочившему', len(made) == 1, str(len(made)))
check('текст про истёкший срок', 'истёк' in made[0].text, made[0].text)

print('\n=== Выданный комплект не трогаем ===')
gone = person('79000000004', 'Галина')
gone_set = stored_for(gone, days_left=1, plate='Е444ЕЕ777')
gone_set.status = 'released'
db.commit()

made = campaigns.plan_storage(db, shop)
check('о выданном молчим', not made, str(len(made)))

print('\n=== Сезон: дата назначается цехом ===')
setting('season_autumn_at', '01.10')
setting('season_spring_at', '10.04')
setting('season_reminders_enabled', '1')

summer = shop_now().replace(month=7, day=15)
check('в июле звать некого', campaigns.season_due(db, shop, summer) is None,
      str(campaigns.season_due(db, shop, summer)))

autumn = shop_now().replace(month=10, day=1)
check('первого октября — осень',
      campaigns.season_due(db, shop, autumn) == ABOUT_AUTUMN,
      str(campaigns.season_due(db, shop, autumn)))

spring = shop_now().replace(month=4, day=12)
check('двенадцатого апреля — весна',
      campaigns.season_due(db, shop, spring) == ABOUT_SPRING,
      str(campaigns.season_due(db, shop, spring)))

late = shop_now().replace(month=11, day=1)
check('через месяц звать поздно',
      campaigns.season_due(db, shop, late) is None,
      str(campaigns.season_due(db, shop, late)))

print('\n=== Зовём тех, кто ещё наш ===')
regular = person('79000000005', 'Дмитрий')
visit_for(regular, days_ago=100)

lost = person('79000000006', 'Евгений')
visit_for(lost, days_ago=900)

made = campaigns.plan_season(db, shop, autumn)
called = {notice.client_id for notice in made}

check('позвали того, кто был недавно', regular.id in called, str(called))
check('и тех, чьи комплекты лежат',
      {soon.id, later.id, overdue.id} <= called, str(called))
check('пропавшего три года назад не трогали', lost.id not in called,
      str(called))
check('выданный комплект сам по себе не повод', gone.id not in called,
      str(called))

print('\n=== Осенью текст про зиму и про очередь ===')
one = next(notice for notice in made if notice.client_id == regular.id)
check('это сезонное', one.kind == KIND_SEASON, one.kind)
check('зовут в зимнюю', 'зимнюю' in one.text, one.text)
check('и объясняют, зачем заранее', 'очеред' in one.text, one.text)

with_set = next(notice for notice in made if notice.client_id == soon.id)
check('владельцу комплекта сказали, что достанут',
      'достанем' in with_set.text, with_set.text)
check('а остальным — нет', 'достанем' not in one.text, one.text)

print('\n=== Второй раз за год не зовём ===')
again = campaigns.plan_season(db, shop, autumn)
check('ничего нового', not again, str(len(again)))

print('\n=== Та же дата на второй точке — человека не зовут дважды ===')
db.add(ShopSetting(shop_id=other_id, key='season_autumn_at', value='01.10'))
db.commit()
visit_for(regular, days_ago=30, where=other_shop)

again = campaigns.plan_season(db, other_shop, autumn)
check('повтора нет',
      regular.id not in {notice.client_id for notice in again},
      str([notice.client_id for notice in again]))

print('\n=== Весной зовут заново и другими словами ===')
made = campaigns.plan_season(db, shop, spring)
check('позвали снова', regular.id in {n.client_id for n in made},
      str(len(made)))

one = next(notice for notice in made if notice.client_id == regular.id)
check('зовут в летнюю', 'летнюю' in one.text, one.text)
check('и про заморозки', 'заморозки' in one.text, one.text)

print('\n=== Выключили — молчим ===')
row = db.query(ShopSetting).filter(ShopSetting.shop_id == shop_id,
                                   ShopSetting.key ==
                                   'season_reminders_enabled').first()
row.value = '0'
db.commit()

check('сезон не наступает',
      campaigns.season_due(db, shop, autumn) is None)

row.value = '1'
db.commit()

print('\n=== Человеку без каналов строка остаётся, но в отправку не идёт ===')
silent = person('79000000007', 'Жанна', reachable=False)
stored_for(silent, days_left=2, plate='К555КК777')

made = campaigns.plan_storage(db, shop)
check('в выдачу не попал', not made, str(len(made)))

left = db.query(Notice).filter(Notice.client_id == silent.id).all()
check('но след остался', len(left) == 1, str(len(left)))
check('помечен пропущенным', left[0].state == SKIPPED, left[0].state)

print('\n=== Всё сразу по всем точкам ===')
fresh = person('79000000008', 'Зоя')
stored_for(fresh, days_left=4, where=other_shop, plate='М666ММ777')

result = campaigns.plan_all(db, autumn)
check('нашлось хранение', result['storage'] == 1, str(result))
check('и сезонные по второй точке', result['season'] >= 1, str(result))

db.close()
finish()
