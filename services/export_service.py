"""
Выгрузка отчётов в Excel.

Пишем CSV в кодировке UTF-8 с меткой порядка байтов и точкой с запятой
в качестве разделителя — именно так русская версия Excel открывает файл
двойным кликом, с правильной кириллицей и разложенным по столбцам.

Отдельная библиотека для .xlsx не подключается сознательно: она утяжеляет
сборку программы, а для выгрузки таблиц ничего не даёт.
"""
import csv
import os
import subprocess
import sys
from datetime import datetime

from utils import get_moscow_time
from logger import log

# Русский Excel ждёт «;» и запятую как десятичный разделитель
DELIMITER = ';'
ENCODING = 'utf-8-sig'


EXPORT_DIR_KEY = 'export_folder'


def get_default_exports_dir():
    """Папка выгрузок по умолчанию — рядом с программой."""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'exports')


def get_exports_dir(db=None):
    """
    Папка для выгрузок.

    Если в настройках задана своя папка — используется она. Когда путь
    задан, но недоступен (например, отключили сетевой диск), молча
    возвращаемся к папке рядом с программой: отчёт важнее, чем место.
    """
    path = None

    if db is not None:
        try:
            from services.settings_service import SettingsService
            configured = (SettingsService(db).get(EXPORT_DIR_KEY, '') or '').strip()
            if configured:
                path = configured
        except Exception as e:
            log.error(f"Не удалось прочитать папку выгрузок из настроек: {e}")

    if not path:
        path = get_default_exports_dir()

    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError as e:
        log.error(f"Папка выгрузок недоступна ({path}): {e}. Сохраняем рядом с программой.")
        fallback = get_default_exports_dir()
        os.makedirs(fallback, exist_ok=True)
        return fallback


def _format(value):
    """Подготовить значение к записи: числа с запятой, даты по-русски."""
    if value is None:
        return ''
    if isinstance(value, float):
        # Excel в русской локали ждёт запятую в дробях
        return f"{value:.2f}".replace('.', ',')
    if isinstance(value, datetime):
        return value.strftime('%d.%m.%Y %H:%M')
    return str(value)


def export_rows(name, headers, rows, title=None, db=None):
    """
    Выгрузить таблицу в файл.

    name — основа имени файла, к нему добавляется дата и время.
    db нужен, чтобы взять папку сохранения из настроек.
    Возвращает путь к созданному файлу.
    """
    stamp = get_moscow_time().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(get_exports_dir(db), f'{name}_{stamp}.csv')

    with open(path, 'w', encoding=ENCODING, newline='') as handle:
        writer = csv.writer(handle, delimiter=DELIMITER)
        if title:
            writer.writerow([title])
            writer.writerow([])
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_format(value) for value in row])

    return path


def open_file(path):
    """Открыть выгруженный файл в Excel или в том, чем открываются таблицы."""
    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except Exception as e:
        log.error(f"Не удалось открыть файл выгрузки: {e}")
        return False
