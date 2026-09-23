"""Госномера и телефоны приводятся к единому виду."""
import _setup
from _setup import check, finish

from utils import normalize_plate, normalize_phone, format_phone


def eq(fn, arg, expected):
    got = fn(arg)
    check(f'{fn.__name__}({arg!r}) -> {expected!r}', got == expected, f'получено {got!r}')


print('=== Госномера ===')
eq(normalize_plate, 'А123ВВ777', 'А123ВВ777')
eq(normalize_plate, 'а123вв777', 'А123ВВ777')      # нижний регистр
eq(normalize_plate, ' А123 ВВ 777 ', 'А123ВВ777')  # пробелы
eq(normalize_plate, 'А123ВВ-777', 'А123ВВ777')     # дефис
eq(normalize_plate, 'A123BB777', 'А123ВВ777')      # латиница
eq(normalize_plate, 'a123bb777', 'А123ВВ777')
eq(normalize_plate, 'K900OP99', 'К900ОР99')        # латинские K, O, P
eq(normalize_plate, '', '')
eq(normalize_plate, None, '')

# Разные написания одного номера должны давать ровно один результат
variants = ['А123ВВ777', 'а123вв777', 'A123BB777', 'a123 bb 777', ' А123ВВ-777 ']
check('все написания номера дают один результат',
      len({normalize_plate(v) for v in variants}) == 1,
      str({normalize_plate(v) for v in variants}))

print('\n=== Телефоны ===')
eq(normalize_phone, '+7 (909) 901-89-31', '79099018931')
eq(normalize_phone, '8 909 901 89 31', '79099018931')  # восьмёрка -> семёрка
eq(normalize_phone, '9099018931', '79099018931')       # без кода страны
eq(normalize_phone, '79099018931', '79099018931')
eq(normalize_phone, '', '')
eq(normalize_phone, None, '')

pvariants = ['+7 (909) 901-89-31', '8 909 901 89 31', '89099018931', '9099018931']
check('все написания телефона дают один результат',
      len({normalize_phone(v) for v in pvariants}) == 1,
      str({normalize_phone(v) for v in pvariants}))

print('\n=== Показ телефона человеку ===')
eq(format_phone, '89099018931', '+7 (909) 901-89-31')
eq(format_phone, '79099018931', '+7 (909) 901-89-31')

finish()
