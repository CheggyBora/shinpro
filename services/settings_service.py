"""
Настройки программы, хранящиеся в базе.

Раньше значения из таблицы settings доставались вручную в каждом месте,
где понадобились, с разбором строк и своими значениями по умолчанию.
Здесь всё в одном месте: имя настройки, значение по умолчанию и тип.
"""
from models import Settings
from services.company_service import COMPANY_DEFAULTS

# Настройки этапа планирования времени.
# Значения по умолчанию подобраны так, чтобы программа работала
# осмысленно сразу, до того как их настроят под конкретный шиномонтаж.
DEFAULTS = {
    # Сколько минут закладывается на наряд сверх услуг:
    # приём машины, оформление, заезд и выезд с поста
    'order_base_minutes': '10',

    # Сколько постов открыто по умолчанию при открытии смены
    'default_posts': '2',

    # Запас к расчётному времени в процентах: реальность всегда медленнее
    # норматива, лучше приятно удивить клиента, чем задержать
    'queue_buffer_percent': '15',

    # Через сколько минут без изменений состав наряда считается
    # устоявшимся и сохраняется сам. 0 — выключить автосохранение.
    'order_autosave_minutes': '3',

    # Во сколько закрывается забытая смена. Программа закроет её сама
    # и посчитает итоги до того, как откроют новую.
    'shift_autoclose_time': '09:00',
    'shift_autoclose_enabled': '1',

    # Отправлять ли сводку по смене в Telegram при закрытии
    'shift_report_to_telegram': '1',

    # Папка для выгрузки отчётов. Пусто — рядом с программой.
    'export_folder': '',

    # Бот для отправки отчётов. Получатели — списком в JSON,
    # telegram_chat_id остался для совместимости со старыми настройками
    'telegram_bot_token': '',
    'telegram_chat_id': '',
    'telegram_recipients': '',

    # Печать наклеек на комплекты шин. Выключена, пока нет принтера
    # этикеток: при выключении всё работает как раньше.
    'label_printing_enabled': '0',
    'label_size': '58x40',

    # Чек на термопринтере вместо листа A4
    'thermal_receipt_enabled': '0',
    'thermal_receipt_width': '58',

    # Раскладка кнопок услуг в наряде. Пусто — раскладка по умолчанию,
    # см. services/service_layout.py
    'service_button_layout': '',

    # Сколько времени закладывать на запись. Услуги при записи по телефону
    # ещё неизвестны, но колёса в сборе или россыпью — известно почти
    # всегда, и это главная разница по времени.
    'booking_minutes_assembled': '30',   # колёса в сборе — перекидка
    'booking_minutes_tires': '60',       # только шины — разбортовка каждого
    'booking_minutes_unknown': '60',     # не выяснили — считаем по долгому

    # Шаг сетки окон, которые предлагаем клиенту. Час: на полчаса
    # не успеть даже перекидку с приёмом и выдачей машины
    'booking_slot_step': '60',

    # Часы, в которые вообще предлагаем записаться. В сезон шиномонтаж
    # работает почти круглосуточно, и окна должны это отражать.
    # 24:00 — до полуночи включительно
    'booking_opens_at': '07:00',
    'booking_closes_at': '24:00',

    # Обмен с сервером приложения. Выключен, пока сервера нет:
    # без него программа работает ровно как раньше.
    'sync_enabled': '0',
    'sync_server_url': '',
    'sync_server_key': '',
    'sync_last_success': '',
}

# Реквизиты организации живут рядом с остальными настройками,
# а их состав и значения по умолчанию — в company_service
DEFAULTS.update(COMPANY_DEFAULTS)


class SettingsService:
    def __init__(self, db):
        self.db = db

    def get(self, key, default=None):
        """Значение настройки строкой."""
        setting = self.db.query(Settings).filter(Settings.key == key).first()
        if setting and setting.value is not None:
            return setting.value
        if default is not None:
            return default
        return DEFAULTS.get(key)

    def get_raw(self, key):
        """
        Значение как оно есть в базе, без подмены на значение по умолчанию.

        Нужно там, где пустая строка — осмысленный ответ («не печатать это
        поле»), а не «настройку ещё не заводили». Возвращает None, если
        настройки в базе нет.
        """
        setting = self.db.query(Settings).filter(Settings.key == key).first()
        return setting.value if setting else None

    def get_int(self, key, default=None):
        try:
            return int(float(self.get(key, default)))
        except (TypeError, ValueError):
            fallback = default if default is not None else DEFAULTS.get(key, 0)
            return int(float(fallback))

    def get_float(self, key, default=None):
        try:
            return float(self.get(key, default))
        except (TypeError, ValueError):
            fallback = default if default is not None else DEFAULTS.get(key, 0)
            return float(fallback)

    def set(self, key, value, commit=True):
        setting = self.db.query(Settings).filter(Settings.key == key).first()
        if setting:
            setting.value = str(value)
        else:
            self.db.add(Settings(key=key, value=str(value)))
        if commit:
            self.db.commit()

    def ensure_defaults(self):
        """Завести отсутствующие настройки со значениями по умолчанию."""
        created = 0
        for key, value in DEFAULTS.items():
            if not self.db.query(Settings).filter(Settings.key == key).first():
                self.db.add(Settings(key=key, value=value))
                created += 1
        if created:
            self.db.commit()
        return created
