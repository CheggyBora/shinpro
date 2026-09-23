"""
Приведение номеров к единому виду.

Повторяет то же, что делает программа в цеху. Сделано отдельной копией
намеренно: сервер должен разворачиваться сам по себе, без исходников
настольной программы рядом. Но правила обязаны совпадать буква в букву —
иначе один и тот же человек станет двумя записями, а машина потеряется
при обмене.
"""

_LATIN_TO_CYRILLIC = str.maketrans({
    'A': 'А', 'B': 'В', 'E': 'Е', 'K': 'К', 'M': 'М', 'H': 'Н',
    'O': 'О', 'P': 'Р', 'C': 'С', 'T': 'Т', 'Y': 'У', 'X': 'Х',
})

_PLATE_JUNK = ' \t-_.,/\\|'


def normalize_plate(plate):
    """«а123бв 777», «A123BB777» -> «А123БВ777»."""
    if not plate:
        return ''

    result = str(plate).strip().upper()
    for char in _PLATE_JUNK:
        result = result.replace(char, '')

    return result.translate(_LATIN_TO_CYRILLIC)


def normalize_phone(phone):
    """«+7 (909) 901-89-31», «8 909 901 89 31» -> «79099018931»."""
    if not phone:
        return ''

    digits = ''.join(char for char in str(phone) if char.isdigit())

    if len(digits) == 11 and digits[0] == '8':
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits

    return digits


def format_phone(phone):
    """«79099018931» -> «+7 (909) 901-89-31»."""
    digits = normalize_phone(phone)
    if len(digits) == 11 and digits[0] == '7':
        return (f"+7 ({digits[1:4]}) {digits[4:7]}-"
                f"{digits[7:9]}-{digits[9:11]}")
    return phone or ''


def is_valid_phone(phone):
    """
    Годится ли номер.

    Проверяем длину российского номера: по нему клиент находится
    в базе цеха, и «12345» там не найдётся никогда.
    """
    digits = normalize_phone(phone)
    return len(digits) == 11 and digits[0] == '7'


def normalize_email(email):
    """
    Привести почту к единому виду.

    «Ivan@Mail.RU » и «ivan@mail.ru» — один ящик, но для базы это две
    разные строки, и человек завёлся бы дважды. Регистр убираем целиком:
    почтовые службы, которыми пользуются в России, его не различают.
    """
    if not email:
        return ''
    return str(email).strip().lower()


def is_valid_email(email):
    """
    Похоже ли это на почтовый ящик.

    Проверяем грубо и намеренно: строгая проверка адреса по стандарту
    отвергает существующие живые ящики, а настоящая проверка тут одна —
    дошло письмо с кодом или нет.
    """
    email = normalize_email(email)
    if len(email) < 5 or len(email) > 254:
        return False
    if email.count('@') != 1:
        return False

    name, domain = email.split('@')
    if not name or not domain:
        return False
    if '.' not in domain or domain.startswith('.') or domain.endswith('.'):
        return False

    return not any(char.isspace() for char in email)
