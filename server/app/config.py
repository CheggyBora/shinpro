"""
Настройки сервера.

Всё берётся из переменных окружения: пароли и ключи не должны лежать
в коде, а боевой сервер и компьютер разработчика настраиваются
по-разному без правки файлов.
"""
import os
import secrets


def _bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'да')


class Settings:
    # --- База -------------------------------------------------------
    # На боевом сервере — PostgreSQL. Для разработки хватает SQLite:
    # поднимать базу ради проверки одного запроса незачем.
    DATABASE_URL = os.environ.get(
        'SERVER_DATABASE_URL',
        'sqlite:///' + os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'server.db'))

    # --- Ключи ------------------------------------------------------
    # Ключ подписи токенов. Без переменной окружения генерируется новый
    # при каждом запуске — на боевом сервере это разлогинит всех при
    # перезапуске, поэтому там переменная обязательна.
    SECRET_KEY = os.environ.get('SERVER_SECRET_KEY') or secrets.token_urlsafe(48)
    SECRET_KEY_FROM_ENV = bool(os.environ.get('SERVER_SECRET_KEY'))

    # Ключ, которым программа в цеху доказывает, что она — это она.
    # Клиентские токены сюда не подходят: обмен даёт доступ ко всему.
    SYNC_KEY = os.environ.get('SERVER_SYNC_KEY', '')

    # Клиент заходит редко, а перезаходить через SMS раздражает.
    # 30 дней — компромисс между удобством и безопасностью.
    TOKEN_DAYS = int(os.environ.get('SERVER_TOKEN_DAYS', '30'))

    # Сотрудник смотрит дашборд с телефона и заходит часто, но доступ
    # к зарплатам всего цеха ценнее клиентского кабинета: неделя вместо
    # месяца — разумная плата за то, чтобы забытый телефон не открывал
    # выручку до конца месяца
    STAFF_TOKEN_DAYS = int(os.environ.get('SERVER_STAFF_TOKEN_DAYS', '7'))

    # Первый владелец. Из дашборда его завести нельзя: заводить людей
    # имеет право только владелец, а его ещё нет
    OWNER_PHONE = os.environ.get('SERVER_OWNER_PHONE', '')
    OWNER_NAME = os.environ.get('SERVER_OWNER_NAME', '')

    # --- Коды подтверждения ------------------------------------------
    CODE_LENGTH = 4
    CODE_TTL_MINUTES = int(os.environ.get('SERVER_CODE_TTL_MINUTES', '15'))

    # Сколько кодов можно запросить на один ящик за час: защита от
    # того, чтобы чужой почтой не завалили сотней писем
    CODE_REQUESTS_PER_HOUR = int(os.environ.get('SERVER_CODE_LIMIT', '5'))

    # Сколько раз можно ошибиться в коде, прежде чем он сгорит
    CODE_MAX_ATTEMPTS = int(os.environ.get('SERVER_CODE_ATTEMPTS', '5'))

    # --- ПИН-код -------------------------------------------------------
    PIN_LENGTH = int(os.environ.get('SERVER_PIN_LENGTH', '4'))

    # Сколько раз подряд можно ошибиться ПИНом на устройстве.
    # После этого — только вход по коду с почты: четыре цифры
    # перебираются за минуту, если не считать попытки
    PIN_MAX_FAILURES = int(os.environ.get('SERVER_PIN_FAILURES', '5'))

    # --- Почта ---------------------------------------------------------
    # Пока ящик отправителя не настроен, код пишется в журнал сервера.
    # Так приложение можно разрабатывать и показывать, ничего не настраивая.
    MAIL_PROVIDER = os.environ.get('SERVER_MAIL_PROVIDER', 'log')
    MAIL_HOST = os.environ.get('SERVER_MAIL_HOST', '')
    MAIL_PORT = int(os.environ.get('SERVER_MAIL_PORT', '465'))
    MAIL_USER = os.environ.get('SERVER_MAIL_USER', '')
    MAIL_PASSWORD = os.environ.get('SERVER_MAIL_PASSWORD', '')
    MAIL_FROM = os.environ.get('SERVER_MAIL_FROM', '')
    MAIL_USE_SSL = _bool('SERVER_MAIL_SSL', True)

    # --- SMS ----------------------------------------------------------
    # Оставлено на будущее: подтверждение идёт почтой, но напоминания
    # о записи или готовности машины удобнее слать сообщением
    SMS_PROVIDER = os.environ.get('SERVER_SMS_PROVIDER', 'log')
    SMS_API_KEY = os.environ.get('SERVER_SMS_API_KEY', '')
    SMS_SENDER = os.environ.get('SERVER_SMS_SENDER', '')

    # --- Шиномонтаж ---------------------------------------------------
    SHOP_NAME = os.environ.get('SERVER_SHOP_NAME', 'Шиномонтаж')

    # --- Прочее -------------------------------------------------------
    DEBUG = _bool('SERVER_DEBUG', False)

    # Откуда разрешено обращаться к серверу. Мобильному приложению CORS
    # не нужен, он понадобится, если появится сайт.
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.environ.get('SERVER_CORS_ORIGINS', '').split(',')
        if origin.strip()
    ]

    @classmethod
    def warnings(cls):
        """Чего не хватает для боевого запуска. Пишется в журнал при старте."""
        problems = []
        if not cls.SECRET_KEY_FROM_ENV:
            problems.append(
                'SERVER_SECRET_KEY не задан: после перезапуска сервера '
                'всем клиентам придётся войти заново')
        if not cls.SYNC_KEY:
            problems.append(
                'SERVER_SYNC_KEY не задан: обмен с программой в цеху выключен')
        if cls.MAIL_PROVIDER == 'log':
            problems.append(
                'Почта не настроена: коды подтверждения пишутся в журнал, '
                'а не отправляются клиенту')
        if cls.DATABASE_URL.startswith('sqlite'):
            problems.append(
                'Используется SQLite: для боевого сервера нужен PostgreSQL')
        if not cls.OWNER_PHONE:
            problems.append(
                'SERVER_OWNER_PHONE не задан: в дашборд войти некому — '
                'первого владельца из самого дашборда не завести')
        if cls.SMS_PROVIDER == 'log' and cls.MAIL_PROVIDER == 'log':
            problems.append(
                'SMS не настроены: коды входа пишутся в журнал сервера, '
                'а не уходят человеку')
        return problems


settings = Settings()
