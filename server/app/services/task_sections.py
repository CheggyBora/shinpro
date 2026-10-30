"""
Разделы задач точки (решение владельца 30.10.2026).

Владелец переименовывает и скрывает встроенные разделы и добавляет свои
в программе цеха; список приходит обменом настройкой «task_sections».
Здесь он нужен, чтобы:

  · задача своего раздела («От контрагента») проходила проверку;
  · в Telegram и в сводке раздел назывался так, как его назвали;
  · дашборд показывал те же разделы и цвета, что и цех.

Цех ещё не присылал список — работают встроенные, как раньше.
"""
import json
import re

from app.models.task import (CATEGORY_TITLES, DIRECTION_CATEGORIES, TIRE, WASH,
                             WORK, STORAGE, TIRES, PAINT, SUPPLY)
from app.services import shop_settings

SETTING = 'task_sections'

# Цвета встроенных — те же, что в дашборде и в цеху
BUILTIN_COLORS = {
    WORK: ('#1d4ed8', '#dbeafe'),
    STORAGE: ('#0f766e', '#ccfbf1'),
    TIRES: ('#c2410c', '#ffedd5'),
    PAINT: ('#6d28d9', '#ede9fe'),
    SUPPLY: ('#b45309', '#fef3c7'),
}


def _builtin():
    rows = []
    for key in (WORK, STORAGE, TIRES, PAINT, SUPPLY):
        directions = [d for d in (TIRE, WASH) if key in DIRECTION_CATEGORIES[d]]
        color, background = BUILTIN_COLORS[key]
        rows.append({'key': key, 'title': CATEGORY_TITLES[key], 'directions': directions,
                     'hidden': False, 'color': color, 'background': background,
                     'builtin': True})
    return rows


def _shop_id(shop):
    return getattr(shop, 'id', shop)


def load(db, shop):
    """Разделы точки по порядку: [{key, title, directions, hidden, color, background, builtin}]."""
    result = _builtin()
    if shop is None:
        return result
    try:
        sent = json.loads(shop_settings.get(db, SETTING, shop=_shop_id(shop)) or '[]')
    except (TypeError, ValueError):
        return result
    if not isinstance(sent, list):
        return result
    builtin = {row['key']: row for row in result}
    for item in sent:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip().lower()
        # Ключ попадает в стиль и разметку дашборда — только буквы и цифры
        if not re.fullmatch(r'[a-z0-9_]{1,10}', key):
            continue
        title = str(item.get('title') or '').strip()[:30]
        if key in builtin:
            row = builtin[key]
            row['title'] = title or row['title']
            row['hidden'] = bool(item.get('hidden')) and key != WORK
            continue
        directions = [d for d in item.get('directions') or [] if d in (TIRE, WASH)] or [TIRE]
        result.append({'key': key, 'title': title or key, 'directions': directions,
                       'hidden': bool(item.get('hidden')),
                       'color': _color(item.get('color'), '#334155'),
                       'background': _color(item.get('background'), '#e2e8f0'),
                       'builtin': False})
    return result


def _color(value, fallback):
    text = str(value or '').strip()
    # Цвет попадает в стиль страницы — только «#rrggbb», ничего другого
    if len(text) == 7 and text[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in text[1:]):
        return text
    return fallback


def allowed(sections, direction):
    """Разделы, в которые можно поставить задачу этого слоя, — со скрытыми."""
    return {row['key'] for row in sections if direction in row['directions']}


def titles(db, shop):
    return {row['key']: row['title'] for row in load(db, shop)}
