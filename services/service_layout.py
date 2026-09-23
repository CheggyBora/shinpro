"""
Раскладка кнопок услуг в наряде.

Раньше список кнопок был вписан в код экрана наряда четырьмя колонками.
Из-за этого услуга, добавленная в прайс-лист, кнопки не получала:
в базе она есть, а нажать её в наряде нельзя.

Теперь кнопки строятся из прайс-листа, а в настройках хранится только
порядок: какая услуга в какой колонке и на каком месте. Услуга, которой
в раскладке нет, всё равно появится — программа поставит её в самую
короткую колонку. Услуга, удалённая из прайса, из раскладки пропадёт.
"""
import json

LAYOUT_KEY = 'service_button_layout'
COLUMN_COUNT = 4

# Порядок, сложившийся за годы работы: слева ходовые услуги, справа
# мелочёвка и проверки. Применяется, пока раскладку не изменили руками.
DEFAULT_LAYOUT = [
    [
        'Съем+Установка', 'Мойка',
        'Шиномонтаж', 'Балансировка', 'Герметик обода',
        'Обработка смазкой', 'Правка литого диска',
        'Ремонт грибком', 'Ремонт кордовой заплаткой',
    ],
    [
        'Runflat', 'Оптимизация балансировки', 'Замена вентиля',
        'Установка датчика давления',
        'Шлифовка бортов диска', 'Шлифовка ступицы',
        'Косметический ремонт шины', 'Дошиповка (за 1 шип)',
        'Грязевая покрышка АТ/МТ',
    ],
    [
        'Ремонт жгутом', 'Подкачка/проверка давления',
        'Зачистка диска от скотча', 'Слесарные работы',
        'Открутка секретного болта', 'Срыв болта/гайки', 'Прочие услуги',
        'Ремонт бокового пореза',
        'Съем+Установка внутреннего колеса',
    ],
    [
        'Вентиль под датчик', 'Вентиль черный', 'Пакет',
        'Золотник', 'Колпочки',
        'Проверка на герметичность', 'Проверка на балансировку',
        'Проверка затяжки болтов',
    ],
]


def _read_saved(db):
    """Раскладка из настроек. Пусто или мусор — значит, раскладка по умолчанию."""
    from services.settings_service import SettingsService

    raw = (SettingsService(db).get(LAYOUT_KEY, '') or '').strip()
    if not raw:
        return None

    try:
        columns = json.loads(raw)
    except (ValueError, TypeError):
        return None

    if not isinstance(columns, list) or not columns:
        return None

    result = []
    for column in columns[:COLUMN_COUNT]:
        if isinstance(column, list):
            result.append([str(name) for name in column if str(name).strip()])
    return result or None


def build_columns(db, available_names):
    """
    Разложить услуги прайс-листа по колонкам кнопок.

    available_names — имена услуг из прайса в том порядке, в каком они
    там идут. Возвращает ровно COLUMN_COUNT списков имён.
    """
    available = list(dict.fromkeys(available_names))
    known = set(available)

    saved = _read_saved(db) or DEFAULT_LAYOUT
    columns = []
    for index in range(COLUMN_COUNT):
        source = saved[index] if index < len(saved) else []
        # Услуги, удалённой из прайса, кнопка не полагается
        columns.append([name for name in dict.fromkeys(source) if name in known])

    placed = {name for column in columns for name in column}

    # Новая услуга без места в раскладке — в самую короткую колонку,
    # чтобы кнопки не съезжали в один длинный столбец
    for name in available:
        if name in placed:
            continue
        shortest = min(range(COLUMN_COUNT), key=lambda i: len(columns[i]))
        columns[shortest].append(name)
        placed.add(name)

    return columns


def save_layout(db, columns):
    """Сохранить порядок кнопок. Пустой список — вернуть раскладку по умолчанию."""
    from services.settings_service import SettingsService

    settings = SettingsService(db)
    if not columns or not any(columns):
        settings.set(LAYOUT_KEY, '')
        return

    cleaned = []
    for column in columns[:COLUMN_COUNT]:
        cleaned.append([str(name).strip() for name in column if str(name).strip()])
    settings.set(LAYOUT_KEY, json.dumps(cleaned, ensure_ascii=False))


def reset_layout(db):
    """Забыть свой порядок и вернуться к раскладке по умолчанию."""
    save_layout(db, None)
