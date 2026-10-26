"""
Направления объекта: шиномонтаж и мойка (решения владельца от 26.10.2026).

Объект может быть только шиномонтажом, только мойкой или и тем и другим.
Смена одна, сотрудники общие; у мойки свои посты, свой прайс — по классу
машины, а не по диаметру, — и услуги мойки начисляются тому, кто их
делал, а не всем на смене.

Наряд один на машину: при создании отмечают, на что приехал человек, и
потом можно добавить второе направление. Каждое направление занимает свой
пост.
"""
TIRE, WASH = 'tire', 'wash'
TITLES = {TIRE: 'Шиномонтаж', WASH: 'Мойка'}

TIRE_KEY = 'direction_tire'
WASH_KEY = 'direction_wash'
WASH_POSTS_KEY = 'wash_posts'
WASH_POSTS_DEFAULT = 2

# Классы машины для прайса мойки — в этом порядке и показываем
WASH_CLASSES = ['sedan', 'crossover', 'jeep', 'minivan']
WASH_CLASS_TITLES = {'sedan': 'Седан', 'crossover': 'Кроссовер', 'jeep': 'Джип',
                     'minivan': 'Минивэн'}

# Чем заполнить прайс мойки, когда её впервые включили: цены ставит
# владелец, названия — чтобы не начинать с пустого экрана
WASH_STARTER = ['Мойка кузова, 2 фазы', 'Комплексная мойка', 'Уборка салона',
                'Чернение шин', 'Воск', 'Мойка двигателя']


def _settings(db):
    from services.settings_service import SettingsService
    return SettingsService(db)


def _flag(db, key, default):
    # Не is_on(): тот считает пустое включённым, а мойка по умолчанию
    # выключена — объект, где её нет, не должен вдруг увидеть переключатель
    value = _settings(db).get(key)
    value = default if value in (None, '') else value
    return str(value).strip().lower() not in ('0', 'false', 'no', 'нет', 'выкл')


def tire_on(db):
    return _flag(db, TIRE_KEY, '1')


def wash_on(db):
    return _flag(db, WASH_KEY, '0')


# Мастера шиномонтажа — по наряду, а не все на смене. Отдельный тумблер в
# настройках (решение владельца от 26.10.2026): включён — наряд ставят на
# пост и в наряд добавляют мастеров, которые на нём работают; шиномонтаж
# делят они. Выключен — как всегда: все, кто был на смене при создании
TIRE_ASSIGN_KEY = 'tire_assign_employees'


def tire_assign(db):
    return _flag(db, TIRE_ASSIGN_KEY, '0')


def set_tire_assign(db, on):
    _settings(db).set(TIRE_ASSIGN_KEY, '1' if on else '0')


def assigned(db, direction):
    """Начисляется ли строка тому, кого выбрали в ней. Только мойка:
    мастеров шиномонтажа выбирают на весь наряд."""
    return direction == WASH


def enabled(db):
    """Включённые направления. Ничего не включено — считаем шиномонтажом."""
    found = [d for d, on in ((TIRE, tire_on(db)), (WASH, wash_on(db))) if on]
    return found or [TIRE]


def both(db):
    return len(enabled(db)) == 2


# Главное окно ставит сюда «направления поменялись»: перерисовать
# переключатель сверху и спрятать лишние разделы
ON_CHANGE = None


def set_enabled(db, tire, wash):
    if not tire and not wash:
        raise ValueError('Хотя бы одно направление должно работать')
    settings = _settings(db)
    settings.set(TIRE_KEY, '1' if tire else '0')
    settings.set(WASH_KEY, '1' if wash else '0')
    if wash:
        seed_wash_services(db)
    if ON_CHANGE is not None:
        try:
            ON_CHANGE()
        except Exception:
            pass


def salary_base(db, direction):
    """От чего процент: revenue — итог строки после скидок, minus — минус расходник."""
    value = _settings(db).get(f'salary_base_{direction}') or 'minus'
    return 'revenue' if value == 'revenue' else 'minus'


def wash_booking_on(db):
    """Принимать запись на мойку через кабинет."""
    return wash_on(db) and _flag(db, 'wash_booking_enabled', '0')


def wash_booking_posts(db):
    return max(1, _settings(db).get_int('wash_booking_posts', 2))


def wash_booking_minutes(db):
    return max(10, _settings(db).get_int('wash_booking_minutes', 30))


def wash_posts(db):
    return max(1, _settings(db).get_int(WASH_POSTS_KEY, WASH_POSTS_DEFAULT))


def parse(value):
    """«tire,wash» → ['tire', 'wash'] в постоянном порядке."""
    chosen = {part.strip() for part in str(value or '').split(',') if part.strip()}
    return [d for d in (TIRE, WASH) if d in chosen] or [TIRE]


def join(directions):
    return ','.join(parse(','.join(directions)))


def class_title(wash_class):
    return WASH_CLASS_TITLES.get(wash_class or '', '—')


def class_by_title(title):
    return next((key for key, value in WASH_CLASS_TITLES.items() if value == title), None)


def seed_wash_services(db):
    """Завести услуги мойки, если их ещё нет. Цены — нули: ставит владелец."""
    from models import Service
    have = db.query(Service).filter(Service.direction == WASH).count()
    if have:
        return 0
    for name in WASH_STARTER:
        db.add(Service(name=name, vehicle_type='all', direction=WASH, is_active=True))
    db.commit()
    return len(WASH_STARTER)
