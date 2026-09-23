"""
Журнал работы программы.

Раньше программа рассказывала о себе через print(). У собранного exe
консоли нет, поэтому эти сообщения уходили в никуда: когда мастер
говорил «вчера чек не напечатался», выяснить причину было нечем.

Теперь всё пишется в файл logs/tire_shop.log рядом с программой.
Файл растёт до 2 МБ, потом откладывается в сторону и начинается новый;
храним пять последних, так что диск не забьётся.

Пользоваться так:

    from logger import log
    log.info("Смена закрыта")
    log.warning("Не удалось отправить отчёт: %s", error)
    log.exception("Ошибка при печати чека")   # добавит трассировку
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOGGER_NAME = 'tire_shop'
LOG_FILE_NAME = 'tire_shop.log'

# 2 МБ на файл и пять файлов в запасе: примерно месяц работы одного поста
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

# Тесты и сервисные скрипты могут увести журнал в сторону,
# чтобы не сорить рядом с программой
DIR_ENV_VAR = 'TIRE_SHOP_LOG_DIR'

log = logging.getLogger(LOGGER_NAME)

_configured = False


def get_logs_dir():
    """Папка журнала — рядом с программой, как чеки и выгрузки."""
    override = os.environ.get(DIR_ENV_VAR)
    if override:
        return override

    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'logs')


def get_log_path():
    return os.path.join(get_logs_dir(), LOG_FILE_NAME)


def setup_logging(level=logging.INFO, to_console=True):
    """
    Включить запись в журнал. Повторный вызов ничего не ломает.

    Если файл создать не удалось — нет прав, диск занят — программа
    всё равно должна работать: журнал полезен, но не обязателен.
    """
    global _configured
    if _configured:
        return log

    log.setLevel(level)
    # Записи не должны заодно уходить в корневой журнал: иначе
    # сторонние библиотеки задублируют их в консоль
    log.propagate = False

    formatter = logging.Formatter(
        '%(asctime)s  %(levelname)-7s  %(message)s',
        datefmt='%d.%m.%Y %H:%M:%S')

    try:
        directory = get_logs_dir()
        os.makedirs(directory, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(directory, LOG_FILE_NAME),
            maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8')
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except OSError:
        pass

    # В окне без консоли sys.stdout бывает None — тогда обходимся файлом
    if to_console and sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        log.addHandler(console)

    if not log.handlers:
        # Совсем без обработчиков logging ругается на каждую запись
        log.addHandler(logging.NullHandler())

    _configured = True
    return log


def cleanup_old_logs(days=90):
    """
    Удалить отложенные файлы журнала старше указанного срока.

    Ротация ограничивает журнал по размеру, но при редкой работе
    старые файлы могут пролежать годами и только путать.
    """
    import time

    directory = get_logs_dir()
    if not os.path.isdir(directory):
        return 0

    edge = time.time() - days * 24 * 3600
    removed = 0
    for name in os.listdir(directory):
        # Трогаем только отложенные копии: текущий файл открыт на запись
        if not name.startswith(LOG_FILE_NAME + '.'):
            continue
        path = os.path.join(directory, name)
        try:
            if os.path.getmtime(path) < edge:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


# Журнал включается сам при первом обращении: иначе сообщение,
# записанное до setup_logging(), потерялось бы — а это как раз
# сообщения о запуске, ради которых журнал и заводили
setup_logging()
