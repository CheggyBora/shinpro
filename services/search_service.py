"""
Поиск «что помню» — для нарядов и хранения (решение владельца 08.11.2026).

Раньше искали по номеру машины целиком и в точном написании: «123» или
«А123» не находили «А123ВВ777», а по телефону и имени хранение не
искалось вовсе. Теперь одна строка — и всё, что подходит:

  · кусок номера в любом написании: «123», «а123вв», «a123bb»;
  · телефон по последним цифрам: «8931» (от четырёх цифр);
  · имя клиента по вхождению, без учёта регистра: «андр»;
  · номер наряда или комплекта: «№57», «57».

Совпадения складываются: «123» найдёт и машину с 123 в номере, и наряд
№123. Лишнее видно в списке сразу, а пропущенное не видно никогда.
"""
from models import Car, Client
from utils import normalize_plate, normalize_phone

MIN_PLATE = 2
MIN_PHONE_DIGITS = 4


def _number(text):
    """«№57», «#57», «57» → 57. Иначе None."""
    rest = text.strip().lstrip('№#').strip()
    return int(rest) if rest.isdigit() and len(rest) <= 9 else None


def _digits(text):
    return ''.join(ch for ch in text if ch.isdigit())


def _has_letters(text):
    return any(ch.isalpha() for ch in text)


def phone_matches(phone, text):
    """Телефон подходит под набранные цифры — по вхождению."""
    digits = _digits(text)
    if len(digits) < MIN_PHONE_DIGITS or not phone:
        return False
    stored = _digits(phone)
    return any(p and p in stored for p in {digits, normalize_phone(text) or ''})


def name_matches(name, text):
    needle = text.strip().lower()
    return bool(name and _has_letters(needle) and len(needle) >= 2 and needle in name.lower())


def plate_matches(plate, text):
    piece = normalize_plate(text)
    return bool(plate and len(piece) >= MIN_PLATE and piece in normalize_plate(plate))


def find(db, text):
    """
    Машины, клиенты и номер (наряда или комплекта), подходящие под строку.
    {'car_ids', 'client_ids', 'number'}. Пустая строка — пусто.
    """
    text = (text or '').strip()
    result = {'car_ids': set(), 'client_ids': set(), 'number': None}
    if not text:
        return result
    result['number'] = _number(text)

    piece = normalize_plate(text)
    if len(piece) >= MIN_PLATE:
        # Номера хранятся приведёнными (normalize_plate): кусок ищем так же
        for car in db.query(Car).filter(Car.license_plate.like(f'%{piece}%')).all():
            result['car_ids'].add(car.id)

    if len(_digits(text)) >= MIN_PHONE_DIGITS or _has_letters(text):
        # Кириллицу без учёта регистра SQLite не сравнивает — сравниваем
        # здесь; клиентов немного, перебрать их дешевле обходных путей
        for client in db.query(Client).all():
            if phone_matches(client.phone, text) or name_matches(client.name, text):
                result['client_ids'].add(client.id)
    return result
