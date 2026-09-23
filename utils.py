import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from logger import log


def make_output_safe():
    """
    Сделать печать в консоль устойчивой к её кодировке.

    Консоль Windows работает в cp1251, а в отладочных сообщениях программы
    есть символы вроде «✓», «⚠» и «₽». Попытка их напечатать выбрасывает
    UnicodeEncodeError, и программа падала прямо при запуске — обработчик
    ошибки печатал «✗» и падал следом.

    Ошибка вывода отладочного сообщения не должна ронять программу,
    поэтому непечатаемые символы просто заменяются на «?».

    Вызывается один раз при старте, до создания окна.
    """
    for stream in (sys.stdout, sys.stderr):
        # В оконном режиме PyInstaller потоков вывода может не быть вовсе
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            # Поток не поддерживает перенастройку — не страшно
            pass

def get_moscow_time():
    """
    Получить текущее время:
    - На Replit: московское время (UTC+3)
    - Локально: системное время компьютера

    Возвращает naive datetime (без часового пояса).

    ВАЖНО: раньше функция возвращала aware datetime (с tzinfo). SQLite при записи
    всё равно отбрасывает часовой пояс, поэтому в базе время всегда лежало без него.
    Из-за этого любая арифметика вида "время из БД - get_moscow_time()" падала с
    TypeError: can't subtract offset-naive and offset-aware datetimes.
    Теперь функция возвращает время в том же виде, в каком оно хранится в базе.
    """
    # Проверяем, запущена ли программа на Replit
    is_replit = os.getenv('REPL_ID') is not None or os.getenv('REPLIT_DB_URL') is not None

    if is_replit:
        # На Replit используем фиксированное московское время UTC+3
        moscow_tz = timezone(timedelta(hours=3))
        return datetime.now(moscow_tz).replace(tzinfo=None)
    else:
        # Локально используем системное время компьютера
        return datetime.now()


def as_naive(value):
    """
    Привести время к naive-виду для безопасного сравнения.

    Нужно для старых записей в базе, созданных до исправления: они могли
    сохраниться с часовым поясом. Возвращает None без изменений.
    """
    if value is not None and getattr(value, 'tzinfo', None) is not None:
        return value.replace(tzinfo=None)
    return value


# Латинские буквы, визуально неотличимые от кириллических.
# На клавиатуре легко набрать "A123BC" латиницей вместо "А123ВС" кириллицей —
# для базы это два РАЗНЫХ номера, и история машины теряется.
_LATIN_TO_CYRILLIC = str.maketrans({
    'A': 'А', 'B': 'В', 'E': 'Е', 'K': 'К', 'M': 'М', 'H': 'Н',
    'O': 'О', 'P': 'Р', 'C': 'С', 'T': 'Т', 'Y': 'У', 'X': 'Х',
})

# Символы, которые люди вставляют в номер, но которые ничего не значат
_PLATE_JUNK = ' \t-_.,/\\|'


def normalize_plate(plate):
    """
    Привести госномер к единому виду.

    "а123бв 777", "А123БВ-777", "a123bb777" -> "А123БВ777"

    Приводит к верхнему регистру, убирает разделители и заменяет латинские
    буквы на кириллические двойники. Только эти 12 букв используются
    в российских номерах, поэтому замена безопасна.

    Возвращает пустую строку для пустого ввода.
    """
    if not plate:
        return ''

    result = str(plate).strip().upper()
    for char in _PLATE_JUNK:
        result = result.replace(char, '')

    return result.translate(_LATIN_TO_CYRILLIC)


def normalize_phone(phone):
    """
    Привести номер телефона к единому виду для поиска и сравнения.

    "+7 (909) 901-89-31", "8 909 901 89 31", "9099018931" -> "79099018931"

    Хранит только цифры. Российские номера приводятся к формату 7XXXXXXXXXX,
    чтобы один и тот же человек не заводился в базе дважды.
    Иностранные номера сохраняются как есть (только цифры).

    Возвращает пустую строку для пустого ввода.
    """
    if not phone:
        return ''

    digits = ''.join(char for char in str(phone) if char.isdigit())

    if len(digits) == 11 and digits[0] == '8':
        # 8 909 ... -> 7 909 ...
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        # 909 ... -> 7 909 ...
        digits = '7' + digits

    return digits


def retry_after_rollback(db, operation):
    """
    Выполнить операцию с базой, а при сбое откатить сессию и повторить один раз.

    Программа держит одну сессию на всё время работы. Если какой-то запрос
    падает, сессия остаётся в сорванном состоянии, и все последующие запросы
    падают следом, пока не сделать откат. Раньше этот приём был скопирован
    в интерфейсе одиннадцать раз; теперь он один.

    Если операция не удалась и со второго раза, ошибка передаётся наверх —
    её должен показать вызывающий код.
    """
    try:
        return operation()
    except Exception as first_error:
        log.info(f"Запрос к базе не удался ({first_error}), откатываем и повторяем")
        try:
            db.rollback()
        except Exception as rollback_error:
            log.error(f"Не удалось откатить сессию: {rollback_error}")
        return operation()


def money_round(value):
    """
    Округлить сумму до целого рубля. Половина округляется ВВЕРХ.

    Встроенная функция round() для этого не годится: она округляет
    половину к чётному, то есть round(332.5) даёт 332, а не 333,
    как ожидает и кассир, и клиент.

    Возвращает float, чтобы значение без проблем ложилось в базу.
    """
    if value is None:
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def format_phone(phone):
    """
    Отформатировать номер для показа человеку: "79099018931" -> "+7 (909) 901-89-31".

    Номера не российского формата возвращаются без изменений.
    """
    digits = normalize_phone(phone)

    if len(digits) == 11 and digits[0] == '7':
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"

    return phone or ''
