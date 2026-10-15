"""
Настройки, которыми цех управляет работой приложения.

Значения приходят при обмене. Пока цех ничего не прислал, берутся
те же числа, что стоят в программе шиномонтажа по умолчанию —
приложение должно вести себя предсказуемо с первого дня.
"""
from app.models import ShopSetting
from app.utils import now as shop_now

DEFAULTS = {
    # Время на запись по колёсам — те же значения, что в цеху
    'booking_minutes_assembled': '30',
    'booking_minutes_tires': '60',
    'booking_minutes_unknown': '60',

    # Шаг сетки окон, которые предлагаем клиенту. Час: на полчаса
    # не успеть даже перекидку с приёмом и выдачей машины
    'booking_slot_step': '60',

    # Постов под запись на дни, которые в цеху отдельно не настраивали
    'booking_posts': '1',

    # Постов, отданных онлайн-очереди. Приезжают из цеха
    'queue_posts': '1',
    'queue_ahead_minutes': '60',
    'queue_lead_minutes': '20',

    # Чем подтверждать номер при первом входе. Ключи приезжают из цеха:
    # менять их должен владелец, а не тот, у кого есть доступ к серверу
    'call_provider': '',
    'call_token': '',
    'sms_provider': '',
    'sms_key': '',
    'sms_sender': '',

    # Часы, в которые предлагаем записаться. 24:00 — до полуночи
    'booking_opens_at': '07:00',
    'booking_closes_at': '24:00',

    # За сколько дней вперёд клиент может записаться. Дальше не пускаем:
    # цех не знает, кто будет работать через два месяца
    'booking_days_ahead': '14',

    # За сколько часов до времени записи её ещё можно отменить
    # в приложении. Позже — только звонком, чтобы окно не пропало зря
    'booking_cancel_hours': '2',

    # Через сколько минут молчания цеха очередь считается устаревшей
    'queue_stale_minutes': '15',

    # Куда слать код подтверждения при первом заходе в кабинет:
    # sms — на тот же телефон (проще человеку, но платно)
    # email — письмом (бесплатно, но адрес придётся спросить)
    'verify_channel': 'sms',

    # Бот и получатели для сообщений о комплектах со склада.
    # Приходят из настроек цеха при обмене
    'telegram_token': '',
    'telegram_chats': '',

    # Хранение и сезон. Значения те же, что в программе цеха: пока цех
    # не прислал свои, приложение должно считать так же, как он
    # Принимает ли точка запись через интернет. Присылает цех
    'booking_enabled': '1',

    'storage_warn_days': '7',

    # За сколько дней записываться с выдачей комплекта со склада.
    # Комплект надо найти и привезти — в тот же день это не делается
    'storage_lead_days': '2',
    'season_autumn_at': '01.10',
    'season_spring_at': '10.04',
    'season_reminders_enabled': '1',

    # Калькулятор покраски: размеры, цены и дополнения одной строкой.
    # Присылает цех; пока не прислал, калькулятор в кабинете не
    # показывается — выдумывать цены на покраску нельзя
    'paint_config': '',

    'shop_name': 'Шиномонтаж',
    'shop_phone': '',
    'shop_address': '',
}


def _shop_id(shop):
    """Точка может прийти объектом или номером — принимаем оба."""
    if shop is None:
        return None
    return getattr(shop, 'id', shop)


def get(db, key, default=None, shop=None):
    """
    Настройка точки.

    Настройки присылает цех, и у каждой точки они свои: разные часы
    работы, разное время на колесо, разное название в чеке. Без точки
    берём значение по умолчанию — выдумывать, чьи настройки подойдут,
    нельзя.
    """
    row = db.query(ShopSetting).filter(
        ShopSetting.key == key,
        ShopSetting.shop_id == _shop_id(shop)).first()

    if row is not None and row.value is not None:
        return row.value
    if default is not None:
        return default
    return DEFAULTS.get(key)


def get_int(db, key, default=None, shop=None):
    try:
        return int(float(get(db, key, default, shop)))
    except (TypeError, ValueError):
        return int(float(DEFAULTS.get(key, 0)))


def set_value(db, key, value, commit=True, shop=None, when=None):
    """
    Записать настройку точки.

    when — когда её поменяли. Часть настроек правят с двух сторон: часы
    записи и посты меняют и в цеху, и владелец из дашборда. Разошлись —
    прав тот, кто поставил позже, а для этого время правки должно быть
    именно временем правки, а не временем, когда данные доехали.

    Запись того же значения метку не двигает: обмен присылает все
    настройки целиком каждый раз, и без этой проверки цех «выигрывал»
    бы у дашборда просто тем, что вышел на связь.
    """
    shop_id = _shop_id(shop)
    row = db.query(ShopSetting).filter(
        ShopSetting.key == key,
        ShopSetting.shop_id == shop_id).first()

    if row is None:
        row = ShopSetting(key=key, shop_id=shop_id)
        db.add(row)

    fresh = None if value is None else str(value)
    if row.value != fresh or row.updated_at is None:
        row.value = fresh
        row.updated_at = when or shop_now()

    if commit:
        db.commit()
    return row


# Что считается выключением. Всё остальное — включено, в том числе
# пустое и непонятное: выключенная запись закрывает точку для клиентов,
# и приходить к этому по умолчанию, из-за сбоя или старой версии
# программы, нельзя. Выключают осознанно — галочкой в цеху или
# кнопкой в дашборде
OFF = ('0', 'false', 'no', 'нет', 'выкл')


def is_on(value):
    """Включено ли. Непонятное считаем включённым, а не наоборот."""
    return str(value).strip().lower() not in OFF


def updated_at(db, key, shop=None):
    """Когда настройку поменяли здесь. None — такой настройки нет."""
    row = db.query(ShopSetting).filter(
        ShopSetting.key == key,
        ShopSetting.shop_id == _shop_id(shop)).first()
    return row.updated_at if row is not None else None


def all_values(db, shop=None):
    """Все настройки точки с подставленными значениями по умолчанию."""
    values = dict(DEFAULTS)
    rows = db.query(ShopSetting).filter(
        ShopSetting.shop_id == _shop_id(shop)).all()

    for row in rows:
        if row.value is not None:
            values[row.key] = row.value
    return values

def title(db, shop):
    """
    Как называть точку человеку.

    Берём название, присланное цехом. Нет его — собственное имя точки,
    под которым её завели.

    Отдельной функцией, потому что обычное get() здесь не годится: не
    найдя настройки, оно возвращает значение по умолчанию — «Шиномонтаж».
    Оно непустое, и запасное имя до дела не доходит. На одной точке это
    незаметно, а на двух обе называются одинаково, и человеку нечего
    выбирать.
    """
    if shop is None:
        return DEFAULTS.get('shop_name')

    return get(db, 'shop_name', '', shop=shop) or shop.name


def address(db, shop):
    """Адрес точки: присланный цехом или записанный при заведении."""
    if shop is None:
        return None

    return get(db, 'shop_address', '', shop=shop) or shop.address
