"""
Настройки, которыми цех управляет работой приложения.

Значения приходят при обмене. Пока цех ничего не прислал, берутся
те же числа, что стоят в программе шиномонтажа по умолчанию —
приложение должно вести себя предсказуемо с первого дня.
"""
from app.models import ShopSetting

DEFAULTS = {
    # Время на запись по колёсам — те же значения, что в цеху
    'booking_minutes_assembled': '30',
    'booking_minutes_tires': '60',
    'booking_minutes_unknown': '60',

    # Шаг сетки окон, которые предлагаем клиенту. Час: на полчаса
    # не успеть даже перекидку с приёмом и выдачей машины
    'booking_slot_step': '60',

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
    'storage_warn_days': '7',
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


def set_value(db, key, value, commit=True, shop=None):
    shop_id = _shop_id(shop)
    row = db.query(ShopSetting).filter(
        ShopSetting.key == key,
        ShopSetting.shop_id == shop_id).first()

    if row is None:
        row = ShopSetting(key=key, shop_id=shop_id)
        db.add(row)

    row.value = None if value is None else str(value)
    if commit:
        db.commit()
    return row


def all_values(db, shop=None):
    """Все настройки точки с подставленными значениями по умолчанию."""
    values = dict(DEFAULTS)
    rows = db.query(ShopSetting).filter(
        ShopSetting.shop_id == _shop_id(shop)).all()

    for row in rows:
        if row.value is not None:
            values[row.key] = row.value
    return values
