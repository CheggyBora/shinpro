"""
Резервное копирование базы данных.

База лежит одним файлом рядом с программой. Без копий любой сбой диска,
случайное удаление или повреждение файла означает потерю всей бухгалтерии
без возможности восстановления.

Копия снимается при каждом запуске программы. Старые копии удаляются,
чтобы папка не росла бесконечно.
"""
import os
import shutil
import sqlite3
from datetime import datetime
from logger import log

# Сколько копий держим. При одном запуске в день это примерно месяц истории.
KEEP_BACKUPS = 30

# Не снимаем копию чаще, чем раз в столько минут: программу могут
# перезапускать несколько раз подряд, и каждый раз копировать смысла нет.
MIN_INTERVAL_MINUTES = 60

BACKUP_PREFIX = 'tire_shop_'
BACKUP_SUFFIX = '.db'


def get_backup_dir(db_path):
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), 'backups')


def list_backups(backup_dir):
    """Все копии, от новых к старым."""
    if not os.path.isdir(backup_dir):
        return []

    files = [
        os.path.join(backup_dir, name)
        for name in os.listdir(backup_dir)
        if name.startswith(BACKUP_PREFIX) and name.endswith(BACKUP_SUFFIX)
    ]
    return sorted(files, key=os.path.getmtime, reverse=True)


def _recently_backed_up(backup_dir):
    """Есть ли свежая копия, чтобы не плодить их при перезапусках."""
    backups = list_backups(backup_dir)
    if not backups:
        return False

    age_minutes = (datetime.now().timestamp() - os.path.getmtime(backups[0])) / 60
    return age_minutes < MIN_INTERVAL_MINUTES


def cleanup_old(backup_dir, keep=KEEP_BACKUPS):
    """Удалить самые старые копии сверх лимита. Возвращает число удалённых."""
    backups = list_backups(backup_dir)
    removed = 0

    for path in backups[keep:]:
        try:
            os.remove(path)
            removed += 1
        except OSError as e:
            log.error(f"Не удалось удалить старую копию {path}: {e}")

    return removed


def create_backup(db_path, force=False):
    """
    Снять копию базы.

    Копирование делается средствами SQLite (метод backup), а не простым
    копированием файла: так копия остаётся целостной, даже если в базу
    в этот момент пишут.

    Возвращает путь к копии или None, если копирование не потребовалось.
    """
    if not os.path.exists(db_path):
        return None

    backup_dir = get_backup_dir(db_path)
    os.makedirs(backup_dir, exist_ok=True)

    if not force and _recently_backed_up(backup_dir):
        return None

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f'{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}')

    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    cleanup_old(backup_dir)
    return backup_path


def restore_from_backup(backup_path, db_path):
    """
    Восстановить базу из копии.

    Текущая база сохраняется рядом с пометкой damaged, чтобы её можно
    было изучить, а не потерять безвозвратно.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Копия не найдена: {backup_path}")

    if os.path.exists(db_path):
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        damaged = f'{db_path}.damaged_{stamp}'
        shutil.copy2(db_path, damaged)

    shutil.copy2(backup_path, db_path)
    return db_path
