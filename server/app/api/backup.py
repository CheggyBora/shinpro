"""
Копия базы цеха на сервере (решение владельца 13.11.2026).

Компьютер на точке может умереть вместе с диском — а с ним и локальные
копии. Программа шлёт сюда сжатую копию всей базы (при запуске, не чаще
раза в три часа, и при закрытии смены). На новом компьютере: чистая
программа → код подключения → «Восстановить с сервера» — и всё на месте:
неоплаченные наряды, категории мастеров, рецепты, история склада.

Храним последние копии каждой точки, старые стираем. Видно в дашборде →
«Точки»: когда пришла последняя копия.
"""
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.security import require_sync_key
from app.services import shop_settings
from app.utils import now as shop_now

router = APIRouter(prefix='/sync/backup', tags=['Обмен: копия базы цеха'])

KEEP = 20
MAX_BYTES = 300 * 1024 * 1024
LAST_KEY = 'backup_last_at'
NAME = re.compile(r'^\d{8}_\d{6}\.db\.gz$')


def backup_dir():
    return os.environ.get('SERVER_BACKUP_DIR') or os.path.join(
        os.path.dirname(settings.PHOTO_DIR.rstrip('/\\')), 'shop-backups')


def _folder(shop):
    path = os.path.join(backup_dir(), str(shop.id))
    os.makedirs(path, exist_ok=True)
    return path


def copies(shop):
    folder = os.path.join(backup_dir(), str(shop.id))
    if not os.path.isdir(folder):
        return []
    return sorted((name for name in os.listdir(folder) if NAME.match(name)), reverse=True)


def last_at(db, shop):
    return shop_settings.get(db, LAST_KEY, shop=shop)


@router.post('', summary='Принять копию базы цеха (gzip)')
async def upload(request: Request, shop=Depends(require_sync_key), db: Session = Depends(get_db)):
    data = await request.body()
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail='Копия пустая или слишком большая')
    if data[:2] != b'\x1f\x8b':
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail='Ждём сжатую копию (gzip)')
    moment = shop_now()
    name = moment.strftime('%Y%m%d_%H%M%S') + '.db.gz'
    folder = _folder(shop)
    with open(os.path.join(folder, name), 'wb') as out:
        out.write(data)
    for old in copies(shop)[KEEP:]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass
    shop_settings.set_value(db, LAST_KEY, moment.replace(microsecond=0).isoformat(), shop=shop)
    return {'ok': True, 'name': name, 'size': len(data), 'kept': len(copies(shop))}


@router.get('', summary='Копии базы цеха')
def listing(shop=Depends(require_sync_key)):
    folder = os.path.join(backup_dir(), str(shop.id))
    return {'copies': [{'name': name, 'size': os.path.getsize(os.path.join(folder, name)),
                        'taken': f'{name[6:8]}.{name[4:6]}.{name[:4]} {name[9:11]}:{name[11:13]}'}
                       for name in copies(shop)]}


@router.get('/latest', summary='Последняя копия базы цеха')
def latest(shop=Depends(require_sync_key)):
    found = copies(shop)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Копий базы на сервере нет')
    return FileResponse(os.path.join(backup_dir(), str(shop.id), found[0]),
                        media_type='application/gzip', filename=found[0],
                        headers={'X-Backup-Name': found[0]})
