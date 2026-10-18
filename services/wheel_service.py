"""
Какое колесо ремонтировали.

У ремонта и правки важно, на каком колесе их делали: клиент вернётся
по гарантии с «опять спускает», и по наряду должно быть видно, то ли
это колесо. Поэтому для таких услуг при добавлении в наряд мастер
отмечает колёса на схеме машины.

Какие услуги спрашивают колесо — настраивается списком названий.
Названиями, а не номерами: «Правка литого диска» заведена в прайсе
отдельно для легковых, джипов и грузовых, а спрашивать надо у всех.

Колёса хранятся в строке наряда короткими обозначениями: «ПЛ,ЗП».
Одно колесо может повториться — два жгута в одной покрышке.
"""
import json

SETTING_KEY = 'wheel_services'

# Выключатель всей функции. Выключили — схема не открывается ни у
# какой услуги, а список услуг сохраняется до включения обратно
ENABLED_KEY = 'wheel_pick_enabled'

DEFAULT_SERVICES = [
    'Ремонт жгутом',
    'Ремонт грибком',
    'Ремонт кордовой заплаткой',
    'Ремонт бокового пореза',
    'Правка литого диска',
]

# (обозначение, полное название)
CAR_WHEELS = [
    ('ПЛ', 'переднее левое'),
    ('ПП', 'переднее правое'),
    ('ЗЛ', 'заднее левое'),
    ('ЗП', 'заднее правое'),
]

# Сзади у грузовой по два колеса с каждой стороны
TRUCK_WHEELS = [
    ('ПЛ', 'переднее левое'),
    ('ПП', 'переднее правое'),
    ('ЗЛн', 'заднее левое наружное'),
    ('ЗЛв', 'заднее левое внутреннее'),
    ('ЗПв', 'заднее правое внутреннее'),
    ('ЗПн', 'заднее правое наружное'),
]

SPARE = ('Зап', 'запаска')


def wheels_for(vehicle_type):
    """Колёса машины этого типа, запаска — последней."""
    wheels = TRUCK_WHEELS if vehicle_type == 'truck' else CAR_WHEELS
    return wheels + [SPARE]


def full_name(code):
    for known, name in CAR_WHEELS + TRUCK_WHEELS + [SPARE]:
        if known == code:
            return name
    return code


def parse(raw):
    """«ПЛ,ЗП» → ['ПЛ', 'ЗП']."""
    return [part.strip() for part in (raw or '').split(',') if part.strip()]


def join(codes):
    return ','.join(code for code in codes if code) or None


def describe(raw):
    """
    Для показа: «ПЛ, ЗП», повторы — «ПЛ×2». Порядок — как отмечали.
    Пусто — пустая строка.
    """
    codes = parse(raw)
    counts = {}
    for code in codes:
        counts[code] = counts.get(code, 0) + 1
    parts = []
    for code in counts:
        parts.append(code if counts[code] == 1 else f'{code}×{counts[code]}')
    return ', '.join(parts)


def item_title(item):
    """Название позиции для наряда и чека: «Ремонт жгутом (ПЛ, ЗП)»."""
    name = item.service.name if item.service else '—'
    wheels = describe(getattr(item, 'wheels', None))
    return f'{name} ({wheels})' if wheels else name


class WheelSettings:
    """Какие услуги спрашивают колесо."""

    def __init__(self, db):
        from services.settings_service import SettingsService
        self.settings = SettingsService(db)

    def names(self):
        raw = self.settings.get_raw(SETTING_KEY)
        if raw is None:
            return list(DEFAULT_SERVICES)
        try:
            names = json.loads(raw)
        except ValueError:
            return list(DEFAULT_SERVICES)
        return [name for name in names if isinstance(name, str) and name]

    def set_names(self, names):
        unique = []
        for name in names:
            name = (name or '').strip()
            if name and name not in unique:
                unique.append(name)
        # Пустой список — тоже ответ: «ни у какой услуги не спрашивать».
        # Поэтому храним его, а не удаляем настройку — иначе вернулись
        # бы услуги по умолчанию
        self.settings.set(SETTING_KEY, json.dumps(unique, ensure_ascii=False))
        return unique

    def add(self, name):
        return self.set_names(self.names() + [name])

    def remove(self, name):
        return self.set_names([n for n in self.names() if n != name])

    def enabled(self):
        return self.settings.is_on(ENABLED_KEY)

    def set_enabled(self, value):
        self.settings.set(ENABLED_KEY, '1' if value else '0')

    def asks(self, service_name):
        return self.enabled() and service_name in self.names()
