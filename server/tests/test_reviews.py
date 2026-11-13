"""
Отзывы клиентов (решение владельца 13.11.2026).

  · ссылки владелец вписывает в «Оформлении»;
  · площадки — свой список (название и ссылка);
  · наряд с галочкой «Предложить оставить отзыв» — через час карточка в
    кабинете и сообщение; без галочки — ничего; повторный обмен — не дубль;
  · ссылок нет — не пишем.
"""
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_reviews_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)

OWNER_PHONE = '+7 909 901-89-54'
os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-key-for-reviews'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-reviews'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_OWNER_PHONE'] = OWNER_PHONE
os.environ['SERVER_OWNER_NAME'] = 'Иван Владелец'

import logging
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Notice, KIND_REVIEW
from app.utils import now as shop_now

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


class CodeCatcher(logging.Handler):
    code = None

    def emit(self, record):
        message = record.getMessage()
        if 'код' in message:
            CodeCatcher.code = message.strip().split()[-1]


logging.getLogger('tire_server').addHandler(CodeCatcher())
KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}


def enter(http, phone, pin):
    http.post('/staff/code', json={'phone': phone})
    token = http.post('/staff/verify', json={'phone': phone, 'code': CodeCatcher.code}).json()['token']
    headers = {'Authorization': f'Bearer {token}'}
    given = http.post('/staff/pin', json={'pin': pin}, headers=headers).json()
    return {'Authorization': f"Bearer {given['token']}"}


def visit(local_id, ask):
    moment = shop_now().replace(microsecond=0).isoformat()
    return {'local_id': local_id, 'client_local_id': 1, 'license_plate': 'А123ВВ777',
            'visited_at': moment, 'total_amount': 2000, 'payment_method': 'cash',
            'ask_review': ask}


def reviews():
    db = SessionLocal()
    try:
        return db.query(Notice).filter(Notice.kind == KIND_REVIEW).all()
    finally:
        db.close()


with TestClient(app) as http:
    owner = enter(http, OWNER_PHONE, '4832')
    http.post('/sync/push', headers=KEY, json={'clients': [
        {'local_id': 1, 'name': 'Пётр', 'phone': '+79005554433'}]})

    print('=== Ссылок ещё нет ===')
    http.post('/sync/push', headers=KEY, json={'visits': [visit(1, True)]})
    check('без ссылок клиенту ничего', not reviews())

    print('\n=== Владелец вписал ссылки ===')
    brand = http.put('/dashboard/brand', headers=owner, json={'reviews': [
        {'title': 'Яндекс Карты', 'url': 'yandex.ru/maps/org/rif/123'},
        {'title': 'Авито', 'url': ''},
        {'title': 'Отзыв на сайте', 'url': 'https://rif.ru/otzyvy'}]}).json()
    check('свой список: пустая ссылка выброшена, https дописан, порядок свой', brand['reviews'] == [
        {'title': 'Яндекс Карты', 'url': 'https://yandex.ru/maps/org/rif/123'},
        {'title': 'Отзыв на сайте', 'url': 'https://rif.ru/otzyvy'}], str(brand['reviews']))
    check('подсказки площадок есть', 'Google Карты' in brand['review_suggested'])

    http.post('/sync/push', headers=KEY, json={'visits': [visit(2, False)]})
    check('без галочки — ничего', not reviews())
    http.post('/sync/push', headers=KEY, json={'visits': [visit(3, True)]})
    rows = reviews()
    check('с галочкой — «спасибо» со ссылками', len(rows) == 1 and 'yandex.ru/maps' in rows[0].text
          and 'rif.ru/otzyvy' in rows[0].text and '2ГИС' not in rows[0].text, str([r.text for r in rows]))
    check('через час, а не у кассы', rows and shop_now() + timedelta(minutes=50) < rows[0].send_at
          < shop_now() + timedelta(minutes=70))
    http.post('/sync/push', headers=KEY, json={'visits': [visit(3, True)]})
    check('повторный обмен того же наряда — не дубль', len(reviews()) == 1)

    print('\n=== QR для отзыва ===')
    link = http.get('/sync/review-link', headers=KEY).json()
    check('программа получает адрес страницы и что ссылки есть',
          '/otzyv/' in link['url'] and link['url'].startswith('https://') and link['has_links'], str(link))
    slug = link['url'].rsplit('/', 1)[1]
    page = http.get(f'/otzyv/{slug}')
    check('страница открывается без входа', page.status_code == 200 and 'Оставьте отзыв' in page.text)
    data = http.get(f'/public/review/{slug}').json()
    check('на странице — площадки из списка',
          [l['title'] for l in data['links']] == ['Яндекс Карты', 'Отзыв на сайте'], str(data))

    print('\n=== Карточка в кабинете клиента ===')
    from app.models import Client, Visit
    from app.services import reviews as review_service
    db = SessionLocal()
    client = db.query(Client).filter(Client.phone.like('%5554433')).first()
    check('сразу после оплаты карточки ещё нет', review_service.for_client(db, client) is None)
    row = db.query(Visit).filter(Visit.ask_review.is_(True), Visit.review_planned_at.isnot(None),
                                 Visit.local_id == 3).first()
    row.review_planned_at = shop_now() - timedelta(minutes=61)
    db.commit()
    card = review_service.for_client(db, client)
    check('через час — «Оставьте отзыв» с площадками', card and card['visit_id'] == row.id
          and [l['title'] for l in card['links']] == ['Яндекс Карты', 'Отзыв на сайте'], str(card))
    review_service.close_for_client(db, client, row.id)
    check('клиент закрыл — карточки нет', review_service.for_client(db, client) is None)
    db.close()
    check('чужой адрес — 404', http.get('/public/review/net-takogo').status_code == 404)

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
