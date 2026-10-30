"""
Разделы задач календаря: встроенные и свои (решение владельца 30.10.2026).

Встроенные — Рабочая, Хранение, Шины, Покраска, у мойки Поставки. Их
можно переименовать и скрыть, но не удалить: на них завязана программа —
задачи «отвезти комплект» сама ставит в «Хранение», у «Покраски» поле
суммы. Свои разделы владелец добавляет сам: «От контрагента», «Закупка».

Удаления нет — только «скрыть», как в прайсе: у старых задач раздел
остаётся со своим названием, в новых его просто не предлагают.

Хранится одной настройкой: что поменяли во встроенных и свои разделы.
Применяется к словарям models.calendar на месте — календарь, окно задачи
и Telegram видят новое без перезапуска. Тот же список уходит на сервер:
дашборд показывает те же разделы и цвета.
"""
import json

from models import calendar as cal

SETTING = 'task_sections'
MAX_TITLE = 30

# Цвета своих разделов (текст, фон) — по кругу; те же в дашборде
PALETTE = [
    ('#be185d', '#fce7f3'),
    ('#15803d', '#dcfce7'),
    ('#0369a1', '#e0f2fe'),
    ('#4d7c0f', '#ecfccb'),
    ('#b91c1c', '#fee2e2'),
    ('#7c2d12', '#ffedd5'),
    ('#334155', '#e2e8f0'),
    ('#a16207', '#fef9c3'),
]

BUILTIN = [
    {'key': cal.WORK, 'title': 'Рабочая', 'directions': ['tire', 'wash']},
    {'key': cal.STORAGE, 'title': 'Хранение', 'directions': ['tire']},
    {'key': cal.TIRES, 'title': 'Шины', 'directions': ['tire']},
    {'key': cal.PAINT, 'title': 'Покраска', 'directions': ['tire']},
    {'key': cal.SUPPLY, 'title': 'Поставки', 'directions': ['wash']},
]
BUILTIN_COLORS = {
    cal.WORK: ('#1d4ed8', '#dbeafe'),
    cal.STORAGE: ('#0f766e', '#ccfbf1'),
    cal.TIRES: ('#c2410c', '#ffedd5'),
    cal.PAINT: ('#6d28d9', '#ede9fe'),
    cal.SUPPLY: ('#b45309', '#fef3c7'),
}
BUILTIN_KEYS = [row['key'] for row in BUILTIN]


class SectionError(Exception):
    """Понятная человеку причина, почему раздел не сохранить."""


def _settings(db):
    from services.settings_service import SettingsService
    return SettingsService(db)


def _saved(db):
    try:
        rows = json.loads(_settings(db).get(SETTING, '') or '[]')
    except (TypeError, ValueError):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get('key')]


def load(db):
    """
    Все разделы по порядку: встроенные, потом свои.
    [{'key', 'title', 'directions', 'hidden', 'builtin', 'colors'}]
    """
    saved = {row['key']: row for row in _saved(db)}
    result = []
    for base in BUILTIN:
        mine = saved.get(base['key'], {})
        result.append({'key': base['key'],
                       'title': (mine.get('title') or base['title'])[:MAX_TITLE],
                       'directions': list(base['directions']),
                       'hidden': bool(mine.get('hidden')) and base['key'] != cal.WORK,
                       'builtin': True,
                       'colors': BUILTIN_COLORS[base['key']]})
    for row in _saved(db):
        if row['key'] in BUILTIN_KEYS:
            continue
        directions = [d for d in row.get('directions') or [] if d in ('tire', 'wash')] or ['tire']
        color = row.get('color') if isinstance(row.get('color'), int) else 0
        result.append({'key': row['key'], 'title': (row.get('title') or row['key'])[:MAX_TITLE],
                       'directions': directions, 'hidden': bool(row.get('hidden')),
                       'builtin': False, 'color': color % len(PALETTE),
                       'colors': PALETTE[color % len(PALETTE)]})
    return result


def _store(db, sections):
    rows = []
    for row in sections:
        item = {'key': row['key'], 'title': row['title'], 'hidden': bool(row['hidden'])}
        if not row['builtin']:
            item['directions'] = row['directions']
            item['color'] = row.get('color', 0)
        rows.append(item)
    _settings(db).set(SETTING, json.dumps(rows, ensure_ascii=False))
    apply(sections)
    try:
        from services import sync_nudge
        sync_nudge.request('разделы задач')
    except Exception:
        pass


def apply(sections):
    """Переписать словари models.calendar на месте — все видят новое сразу."""
    cal.CATEGORY_TITLES.clear()
    cal.CATEGORY_COLORS.clear()
    cal.CATEGORIES[:] = [row['key'] for row in sections]
    for direction in ('tire', 'wash'):
        mine = [row for row in sections if direction in row['directions']]
        cal.KNOWN_BY_DIRECTION[direction] = [row['key'] for row in mine]
        cal.CATEGORIES_BY_DIRECTION[direction] = [row['key'] for row in mine if not row['hidden']]
    for row in sections:
        cal.CATEGORY_TITLES[row['key']] = row['title']
        cal.CATEGORY_COLORS[row['key']] = row['colors']


def refresh(db):
    """Прочитать из настроек и применить. Возвращает список разделов."""
    sections = load(db)
    apply(sections)
    return sections


def _clean_title(sections, title, key=None):
    title = ' '.join((title or '').split())
    if not title:
        raise SectionError('Напишите название раздела')
    if len(title) > MAX_TITLE:
        raise SectionError(f'Название — не длиннее {MAX_TITLE} знаков')
    if any(row['title'].lower() == title.lower() and row['key'] != key for row in sections):
        raise SectionError(f'Раздел «{title}» уже есть')
    return title


def add(db, title, directions=('tire',)):
    """Свой раздел. Ключ — c1, c2…: короткий, он уходит на сервер."""
    sections = load(db)
    title = _clean_title(sections, title)
    used = {row['key'] for row in sections}
    number = 1
    while f'c{number}' in used:
        number += 1
    taken = {row.get('color') for row in sections if not row['builtin']}
    color = next((i for i in range(len(PALETTE)) if i not in taken), len(sections) % len(PALETTE))
    directions = [d for d in directions if d in ('tire', 'wash')] or ['tire']
    row = {'key': f'c{number}', 'title': title, 'directions': directions, 'hidden': False,
           'builtin': False, 'color': color, 'colors': PALETTE[color]}
    sections.append(row)
    _store(db, sections)
    return row


def _find(sections, key):
    row = next((r for r in sections if r['key'] == key), None)
    if row is None:
        raise SectionError('Такого раздела нет')
    return row


def rename(db, key, title):
    sections = load(db)
    row = _find(sections, key)
    row['title'] = _clean_title(sections, title, key)
    _store(db, sections)


def set_hidden(db, key, hidden):
    sections = load(db)
    row = _find(sections, key)
    if key == cal.WORK and hidden:
        # В «Рабочую» падает всё, у чего раздела нет, — её прятать нельзя
        raise SectionError('«Рабочую» скрыть нельзя: в неё попадают задачи без раздела')
    row['hidden'] = bool(hidden)
    _store(db, sections)


def set_color(db, key, color):
    sections = load(db)
    row = _find(sections, key)
    if row['builtin']:
        raise SectionError('Цвет меняется только у своих разделов')
    row['color'] = int(color) % len(PALETTE)
    row['colors'] = PALETTE[row['color']]
    _store(db, sections)


def for_server(db):
    """Список для сервера и дашборда: ключ, название, где, скрыт, цвета."""
    return json.dumps([{'key': row['key'], 'title': row['title'],
                        'directions': row['directions'], 'hidden': row['hidden'],
                        'color': row['colors'][0], 'background': row['colors'][1]}
                       for row in load(db)], ensure_ascii=False)
