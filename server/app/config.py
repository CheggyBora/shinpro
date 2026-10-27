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


def _hosts_of(origins):
    """«https://lk.rif-service.ru» -> «lk.rif-service.ru»."""
    hosts = []
    for origin in origins:
        host = origin.split('://', 1)[-1].split('/', 1)[0].split(':', 1)[0]
        host = host.strip().lower().rstrip('.')
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _parent_domain(hosts):
    """«lk.rif-service.ru» -> «rif-service.ru»: под ним заводятся адреса организаций."""
    for host in hosts:
        parts = host.split('.')
        if len(parts) >= 3:
            return '.'.join(parts[1:])
    return ''


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

    # --- Оплата пользования --------------------------------------------
    # Проверка выключена: пока заказчик один и это вы сами, платить
    # некому. Включается, когда появится первый платящий — до тех пор
    # место под проверку просто стоит на своём месте
    BILLING_ENFORCE = _bool('SERVER_BILLING_ENFORCE', False)

    # Сколько дней всё работает после конца оплаченного срока. Человек
    # мог уехать, забыть, перепутать дату — закрывать в ту же минуту
    # значит наказывать за невнимательность, а не взыскивать долг
    BILLING_GRACE_DAYS = int(os.environ.get('SERVER_BILLING_GRACE_DAYS', '5'))

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

    # --- Подтверждение номера звонком ----------------------------------
    # Человек звонит на выданный номер, вызов сбрасывается до соединения,
    # и номер подтверждается сам — вводить нечего. Дешевле SMS и быстрее:
    # нечего прочитать, продиктовать и перепутать.
    #
    # Пока не задан, подтверждение звонком не предлагается вовсе.
    CALL_PROVIDER = os.environ.get('SERVER_CALL_PROVIDER', 'off')
    CALL_TOKEN = os.environ.get('SERVER_CALL_TOKEN', '')

    # --- Уведомления в браузере ---------------------------------------
    # Пара ключей VAPID: ими сервер подписывает уведомления, чтобы
    # Google и Apple знали, от кого они. Пара одна на весь сервер —
    # она про сервер, а не про заказчика. Нет ключей — кнопка
    # «Уведомлять в браузере» в кабинете не показывается.
    #
    # Сгенерировать: python manage.py push-keys
    PUSH_PUBLIC_KEY = os.environ.get('SERVER_PUSH_PUBLIC_KEY', '')
    PUSH_PRIVATE_KEY = os.environ.get('SERVER_PUSH_PRIVATE_KEY', '')

    # Адрес, по которому Google напишет, если с нашими уведомлениями
    # что-то не так. Без него часть серверов пуша отвечает отказом
    PUSH_CONTACT = os.environ.get('SERVER_PUSH_CONTACT', '')

    # --- Фото из цеха --------------------------------------------------
    # Куда складывать снимки с телефонов мастеров. На диске, а не в
    # базе: базу с картинками внутри нельзя ни скопировать, ни
    # восстановить за разумное время.
    PHOTO_DIR = os.environ.get(
        'SERVER_PHOTO_DIR',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'photos'))

    # Сколько весит один снимок после сжатия в телефоне. Больше —
    # отказываем: это либо не фото, либо телефон не сжал, и на плохой
    # связи такая отправка не дойдёт всё равно
    PHOTO_MAX_BYTES = int(os.environ.get('SERVER_PHOTO_MAX_BYTES',
                                         str(3 * 1024 * 1024)))

    # Сколько месяцев храним. Фото нужно, пока о нём спорят; через год
    # о прошлогодней грыже не спорит никто, а место оно занимает
    PHOTO_KEEP_MONTHS = int(os.environ.get('SERVER_PHOTO_KEEP_MONTHS', '12'))

    # --- Номер машины с фото ----------------------------------------
    # Наряд по фото с телефона (docs/order_photo.md): номер распознаётся
    # здесь же, на сервере. Выключить — SERVER_PLATES=0: тогда номер
    # всегда вписывают руками, остальное работает как было.
    PLATES_ENABLED = _bool('SERVER_PLATES', True)

    # Куда скачиваются веса моделей (~13 МБ, один раз). Служба пишет
    # только в свою рабочую папку (ProtectSystem=strict, ProtectHome),
    # поэтому не в ~/.cache, а рядом с кодом. Раскатка эту папку не
    # стирает — см. deploy/post-receive
    PLATE_MODEL_DIR = os.environ.get(
        'SERVER_PLATE_MODEL_DIR',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'plate-models'))

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

    # --- Адреса организаций ---------------------------------------------
    #
    # Свои адреса шиномонтажа, который держит сервер: lk.rif-service.ru
    # и admin.rif-service.ru. Пришёл запрос на них — это он. По умолчанию
    # берутся из SERVER_CORS_ORIGINS: их пишет install.sh, и на рабочем
    # сервере вписывать ничего не нужно
    HOME_HOSTS = _hosts_of(
        [h for h in os.environ.get('SERVER_HOME_HOSTS', '').split(',') if h.strip()]
        or CORS_ORIGINS)

    # Под этим доменом организации получают свой адрес сразу при
    # заведении: koleso.rif-service.ru — запись, koleso-admin.rif-service.ru
    # — дашборд. Пусто — берётся из домашних адресов (lk.rif-service.ru
    # -> rif-service.ru)
    PLATFORM_DOMAIN = (os.environ.get('SERVER_PLATFORM_DOMAIN', '').strip().lower().rstrip('.')
                       or _parent_domain(HOME_HOSTS))

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
        if (cls.SMS_PROVIDER == 'log' and cls.MAIL_PROVIDER == 'log'
                and not (cls.CALL_PROVIDER not in ('', 'off')
                         and cls.CALL_TOKEN)):
            problems.append(
                'Войти некому: ни SMS, ни почта, ни подтверждение звонком '
                'не настроены. Коды пишутся в журнал сервера')
        return problems


settings = Settings()
