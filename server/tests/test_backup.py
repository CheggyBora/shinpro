"""
Копия базы цеха на сервере (13.11.2026).

  · цех шлёт сжатую копию — сервер хранит, отдаёт последнюю обратно;
  · не gzip — отказ; без ключа — отказ; чужая точка своих копий не видит;
  · старые стираются — хранится 20 последних;
  · в «Точках» дашборда видно, когда пришла последняя копия.
"""
import gzip
import os
import shutil
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))

_db_path = os.path.join(tempfile.gettempdir(), 'tire_backup_test.db')
if os.path.exists(_db_path):
    os.remove(_db_path)
_dir = os.path.join(tempfile.gettempdir(), 'tire_backup_test_files')
shutil.rmtree(_dir, ignore_errors=True)

os.environ['SERVER_DATABASE_URL'] = 'sqlite:///' + _db_path.replace(os.sep, '/')
os.environ['SERVER_SECRET_KEY'] = 'test-secret-backup-0123456789'
os.environ['SERVER_SYNC_KEY'] = 'test-sync-backup'
os.environ['SERVER_MAIL_PROVIDER'] = 'log'
os.environ['SERVER_BACKUP_DIR'] = _dir

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import Shop
from app.services import onboarding, tenancy
from app.api import backup as backup_api

_failures = []


def check(name, condition, detail=''):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))
    if not condition:
        _failures.append(name)


KEY = {'X-Sync-Key': os.environ['SERVER_SYNC_KEY']}

with TestClient(app) as http:
    data = gzip.compress(b'SQLite format 3\x00' + b'x' * 2000)
    answer = http.post('/sync/backup', headers=KEY, content=data)
    check('копия принята', answer.status_code == 200 and answer.json()['kept'] == 1, answer.text)
    back = http.get('/sync/backup/latest', headers=KEY)
    check('последняя отдаётся той же', back.status_code == 200 and back.content == data)
    listing = http.get('/sync/backup', headers=KEY).json()['copies']
    check('в списке — одна, с датой', len(listing) == 1 and listing[0]['taken'], str(listing))
    check('не gzip — отказ', http.post('/sync/backup', headers=KEY, content=b'plain').status_code == 400)
    check('без ключа — отказ', http.post('/sync/backup', content=data).status_code in (401, 403))

    db = SessionLocal()
    shop = db.query(Shop).first()
    _, stranger, stranger_key = tenancy.create_account(db, 'Чужой шиномонтаж')
    point = onboarding.point_out(db, shop)
    check('в «Точках» видно время последней копии', bool(point.get('backup_at')), str(point))
    db.close()
    check('чужая точка своих копий не видит',
          http.get('/sync/backup/latest', headers={'X-Sync-Key': stranger_key}).status_code == 404)

    folder = os.path.join(_dir, str(shop.id))
    for index in range(25):
        open(os.path.join(folder, f'202601{index + 1:02d}_120000.db.gz'), 'wb').write(data)
    http.post('/sync/backup', headers=KEY, content=data)
    check('хранится 20 последних', len(backup_api.copies(shop)) == 20, str(len(backup_api.copies(shop))))

print('-' * 60)
if _failures:
    print(f'ПРОВАЛЕНО ПРОВЕРОК: {len(_failures)}')
    sys.exit(1)
print('Все проверки пройдены')
