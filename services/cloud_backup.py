"""
Копия базы на сервере (решение владельца 13.11.2026).

Локальные копии (backup_service) лежат на том же диске, что и база:
умер диск — пропали обе. Поэтому копия уходит ещё и на сервер:

  · при запуске программы — если с прошлой отправки прошло больше трёх
    часов;
  · при закрытии смены — всегда.

На новом компьютере: чистая программа → код подключения → «Восстановить
с сервера». Текущая база при восстановлении не теряется — остаётся
рядом с пометкой damaged (backup_service.restore_from_backup).

Отправка в своём потоке и молча: нет связи — попробуем в следующий раз,
работе цеха это не мешает.
"""
import gzip
import os
import sqlite3
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from logger import log

SENT_KEY = 'cloud_backup_at'
EVERY = timedelta(hours=3)
TIMEOUT = 120


class BackupError(Exception):
    pass


def _sync():
    from config import SessionLocal
    from services.sync_service import SyncService
    db = SessionLocal()
    return db, SyncService(db)


def _snapshot(db_path):
    """Целостная копия базы (как backup_service) — сжатая, байтами."""
    handle, temp = tempfile.mkstemp(suffix='.db')
    os.close(handle)
    try:
        source = sqlite3.connect(db_path)
        try:
            target = sqlite3.connect(temp)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        with open(temp, 'rb') as raw:
            return gzip.compress(raw.read(), compresslevel=6)
    finally:
        try:
            os.remove(temp)
        except OSError:
            pass


def _request(sync, method, path, data=None):
    from config import offline_test_mode
    if offline_test_mode():
        raise BackupError('Тестовый режим без связи')
    url = sync.get_url()
    if not url or not sync.get_key():
        raise BackupError('Обмен с сервером не настроен')
    request = urllib.request.Request(f'{url.rstrip("/")}{path}', data=data, method=method,
                                     headers={'X-Sync-Key': sync.get_key(),
                                              'Content-Type': 'application/gzip'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
            return answer.read(), dict(answer.headers)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise BackupError('Копий базы на сервере нет')
        raise BackupError(f'Сервер отказал: {e.code}')
    except urllib.error.URLError as e:
        raise BackupError(f'Нет связи с сервером: {e.reason}')


def upload(db_path, force=False):
    """Отправить копию. Возвращает True — отправили, False — рано или нечего."""
    db, sync = _sync()
    try:
        from services.settings_service import SettingsService
        settings = SettingsService(db)
        if not sync.is_enabled():
            return False
        last = settings.get(SENT_KEY)
        if not force and last:
            try:
                if datetime.now() - datetime.fromisoformat(last) < EVERY:
                    return False
            except ValueError:
                pass
        if not db_path or not os.path.exists(db_path):
            return False
        _request(sync, 'POST', '/sync/backup', _snapshot(db_path))
        settings.set(SENT_KEY, datetime.now().replace(microsecond=0).isoformat())
        log.info('Копия базы отправлена на сервер')
        return True
    finally:
        db.close()


def upload_in_background(db_path, force=False):
    def worker():
        try:
            upload(db_path, force=force)
        except Exception as e:
            log.warning(f'Копия базы на сервер не ушла: {e}')
    threading.Thread(target=worker, daemon=True).start()


def latest_info():
    """Последняя копия на сервере: {'name', 'taken', 'size'} или None."""
    import json
    db, sync = _sync()
    try:
        body, _headers = _request(sync, 'GET', '/sync/backup')
        rows = json.loads(body.decode('utf-8')).get('copies') or []
        return rows[0] if rows else None
    finally:
        db.close()


def restore(db_path):
    """
    Заменить базу последней копией с сервера. Текущая база остаётся рядом
    с пометкой damaged. После — программу нужно перезапустить.
    """
    from services.backup_service import restore_from_backup
    db, sync = _sync()
    try:
        body, _headers = _request(sync, 'GET', '/sync/backup/latest')
    finally:
        db.close()
    try:
        raw = gzip.decompress(body)
    except OSError:
        raise BackupError('Копия с сервера повреждена')
    handle, temp = tempfile.mkstemp(suffix='.db')
    os.close(handle)
    with open(temp, 'wb') as out:
        out.write(raw)
    try:
        check = sqlite3.connect(temp)
        try:
            tables = {row[0] for row in check.execute("select name from sqlite_master where type='table'")}
        finally:
            check.close()
        if 'work_orders' not in tables or 'settings' not in tables:
            raise BackupError('Это не база программы шиномонтажа')
        # Ключ обмена — тот, что ввели сейчас: в копии может быть старый
        db, sync = _sync()
        try:
            url, key = sync.get_url(), sync.get_key()
        finally:
            db.close()
        fix = sqlite3.connect(temp)
        try:
            from services.sync_service import URL_KEY, KEY_KEY, ENABLED_KEY
            for name, value in ((URL_KEY, url), (KEY_KEY, key), (ENABLED_KEY, '1')):
                changed = fix.execute('update settings set value=? where key=?', (value, name)).rowcount
                if not changed:
                    fix.execute('insert into settings (key, value) values (?, ?)', (name, value))
            fix.commit()
        except sqlite3.Error:
            pass
        finally:
            fix.close()
        # Соединения с базой закрыть, журнал старой базы (-wal, -shm) убрать:
        # иначе при следующем открытии SQLite накатит его поверх копии
        try:
            from config import engine
            engine.dispose()
        except Exception:
            pass
        restore_from_backup(temp, db_path)
        for suffix in ('-wal', '-shm'):
            try:
                os.remove(db_path + suffix)
            except OSError:
                pass
    finally:
        try:
            os.remove(temp)
        except OSError:
            pass
    return db_path
