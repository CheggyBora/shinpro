"""
Реквизиты организации для печатных документов.

Раньше название, ИНН, адрес и телефон были вписаны прямо в код чека.
Из-за этого смена адреса или телефона требовала пересборки программы.
Теперь реквизиты лежат в настройках, а здесь — одно место, откуда их
берут все документы: чек A4, чек на термопринтер, наклейки, отчёты.
"""

# Значения по умолчанию совпадают с тем, что раньше было вписано в код,
# чтобы после обновления документы печатались ровно так же, как печатались.
COMPANY_DEFAULTS = {
    'company_name': 'Шиномонтаж «РИФ»',
    'company_slogan': 'Правка дисков, аргон, покраска',
    'company_legal_name': 'ИП Дюпин Андрей',
    'company_inn': '770208926387',
    'company_address': '115280, г. Москва, ул. Автозаводская, д. 24 стр. 1',
    'company_phone': '+7 909 901-89-31',
    'company_email': 'rifshina@gmail.com',
}

# Подписи для экрана настроек — в том порядке, в каком их удобно заполнять
COMPANY_FIELDS = [
    ('company_name', 'Название'),
    ('company_slogan', 'Подзаголовок'),
    ('company_legal_name', 'Юридическое лицо'),
    ('company_inn', 'ИНН'),
    ('company_address', 'Адрес'),
    ('company_phone', 'Телефон'),
    ('company_email', 'Электронная почта'),
]


class CompanyInfo:
    """Реквизиты, прочитанные из настроек, в удобном для печати виде."""

    def __init__(self, values):
        for key, default in COMPANY_DEFAULTS.items():
            value = values.get(key)
            # Пустое поле — это осознанный выбор: значит, его не печатаем.
            # Поэтому подставляем значение по умолчанию только когда
            # настройки вообще нет (None), а не когда она пустая.
            setattr(self, key[len('company_'):],
                    default if value is None else value.strip())

    def header_lines(self):
        """Строки блока реквизитов в шапке чека, без пустых."""
        lines = []
        if self.legal_name:
            lines.append(self.legal_name)
        if self.inn:
            lines.append(f'ИНН {self.inn}')
        if self.address:
            lines.extend(self._split_address())
        if self.phone:
            lines.append(f'Телефон: {self.phone}')
        if self.email:
            lines.append(f'email: {self.email}')
        return lines

    def _split_address(self):
        """
        Разбить адрес на две строки по запятой ближе к середине.

        Адрес хранится одной строкой — так его проще править. Но в шапке
        чека он длинный и наезжает на логотип, поэтому режем его по
        ближайшей к середине запятой, а не по количеству символов:
        «115280, г. Москва,» / «ул. Автозаводская, д. 24 стр. 1».
        """
        text = self.address
        if len(text) <= 34:
            return [text]

        middle = len(text) // 2
        positions = [i for i, char in enumerate(text) if char == ',']
        if not positions:
            return [text]

        cut = min(positions, key=lambda i: abs(i - middle))
        return [text[:cut + 1].strip(), text[cut + 1:].strip()]


def get_company(db=None):
    """
    Реквизиты организации. Без сессии откроет свою и закроет за собой —
    печать вызывается из мест, где сессии под рукой нет.
    """
    from services.settings_service import SettingsService

    own_session = db is None
    if own_session:
        from config import SessionLocal
        db = SessionLocal()
    try:
        settings = SettingsService(db)
        values = {}
        for key in COMPANY_DEFAULTS:
            # Читаем «сырое» значение: get() подменил бы пустую строку
            # на значение по умолчанию, а пустое поле значит «не печатать»
            values[key] = settings.get_raw(key)
        return CompanyInfo(values)
    except Exception:
        # Документ важнее настроек: если база недоступна, печатаем
        # с исходными реквизитами, а не роняем печать чека
        return CompanyInfo({})
    finally:
        if own_session:
            db.close()
