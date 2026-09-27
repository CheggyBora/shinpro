#!/usr/bin/env python3
"""
Управление сервером из командной строки: аккаунты, точки, оплата.

Пока экранов для этого нет — и не нужно: заказчиков считаные единицы,
а лезть в базу руками нельзя. Эти команды делают ровно то же, что
сделали бы экраны, и оставляют те же следы.

    python manage.py accounts                          кто заведён
    python manage.py add-account "Шиномонтаж «РИФ»"     новый заказчик
    python manage.py add-shop rif "РИФ на Южной"        ещё одна точка
    python manage.py pay rif 3000 --months 1            записать платёж
    python manage.py payments rif                       за что платили
    python manage.py block rif --reason "по просьбе"    закрыть доступ
    python manage.py unblock rif                        открыть обратно
    python manage.py new-key rif-na-yuzhnoy             сменить ключ обмена
    python manage.py check                             всё ли готово
    python manage.py bot rif ТОКЕН --url https://домен   подключить бота
    python manage.py notify                            разослать созревшее

Ключ обмена показывается один раз — при создании точки или смене
ключа. В базе от него остаётся только отпечаток, и подсмотреть его
потом нельзя: можно лишь выдать новый.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal, init_db          # noqa: E402
from app.models import Account, Shop                    # noqa: E402
from app.services import billing, tenancy               # noqa: E402
from app.utils import now as shop_now                   # noqa: E402


def money(value):
    return f"{value:,.0f}".replace(',', ' ') + ' ₽'


def day(value):
    return value.strftime('%d.%m.%Y') if value else '—'


def find_account(db, name):
    """Аккаунт по короткому имени или номеру."""
    account = db.query(Account).filter(Account.slug == name).first()
    if account is None and str(name).isdigit():
        account = db.query(Account).filter(Account.id == int(name)).first()

    if account is None:
        sys.exit(f'Нет такого заказчика: {name}')

    return account


def cmd_accounts(db, args):
    rows = db.query(Account).order_by(Account.id).all()
    if not rows:
        print('Заказчиков пока нет')
        return

    for account in rows:
        status = billing.state(account)
        shops = ', '.join(shop.name for shop in account.shops) or 'нет точек'
        print(f"[{account.id}] {account.name}  ({account.slug})")
        until = (f" · до {day(status['paid_until'])}"
                 if status['paid_until'] else '')
        print(f"     {status['title']}{until}")
        print(f"     точки: {shops}")


def cmd_add_account(db, args):
    account, shop, key = tenancy.create_account(db, args.name, args.shop)

    print(f'Заведён заказчик: {account.name} ({account.slug})')
    print(f'Первая точка: {shop.name} ({shop.slug})')
    print(f'Страница записи: /z/{shop.slug}')
    print()
    print('Ключ обмена для программы в цеху — сохраните, второй раз')
    print('его показать нельзя:')
    print(f'    {key}')


def cmd_add_shop(db, args):
    account = find_account(db, args.account)
    shop, key = tenancy.add_shop(db, account, args.name)

    print(f'Добавлена точка: {shop.name} ({shop.slug})')
    print(f'Страница записи: /z/{shop.slug}')
    print()
    print('Ключ обмена — сохраните, второй раз его показать нельзя:')
    print(f'    {key}')


def cmd_new_key(db, args):
    shop = db.query(Shop).filter(Shop.slug == args.shop).first()
    if shop is None:
        sys.exit(f'Нет такой точки: {args.shop}')

    key = tenancy.generate_key()
    shop.sync_key_hash = tenancy.hash_key(key)
    shop.sync_key_set_at = shop_now()
    db.commit()

    print(f'Новый ключ обмена для точки {shop.name}:')
    print(f'    {key}')
    print()
    print('Старый ключ перестал работать. Впишите новый в настройках')
    print('программы в цеху, иначе обмен встанет.')


def cmd_pay(db, args):
    account = find_account(db, args.account)
    payment = billing.record_payment(
        db, account, args.amount, months=args.months,
        method=args.method, external_id=args.external_id,
        comment=args.comment)

    print(f'Записан платёж: {money(payment.amount)} от {day(payment.paid_at)}')
    print(f'Период: {day(payment.period_from)} — {day(payment.period_to)}')
    print(f'Оплачено до: {day(account.paid_until)}')


def cmd_payments(db, args):
    account = find_account(db, args.account)
    if not account.payments:
        print('Платежей не было')
        return

    total = 0.0
    for payment in account.payments:
        total += payment.amount
        print(f"{day(payment.paid_at)}  {money(payment.amount):>12}  "
              f"{day(payment.period_from)} — {day(payment.period_to)}  "
              f"{payment.method}"
              + (f"  {payment.comment}" if payment.comment else ''))

    print('-' * 60)
    print(f'Всего: {money(total)}, оплачено до {day(account.paid_until)}')


def cmd_block(db, args):
    account = find_account(db, args.account)
    billing.block(db, account, args.reason)
    print(f'Доступ закрыт: {account.name}')
    print('Цех продолжает работать, обмен идёт. Закрыт только онлайн.')


def cmd_unblock(db, args):
    account = find_account(db, args.account)
    billing.unblock(db, account)
    print(f'Доступ открыт: {account.name}')


def cmd_overdue(db, args):
    rows = billing.overdue(db)
    if not rows:
        print('Должников нет')
        return

    for account in rows:
        print(f"{account.name} ({account.slug}): оплачено до "
              f"{day(account.paid_until)}")


def cmd_check(db, args):
    """
    Что готово к работе, а что ещё нет.

    Смысл команды — отвечать на вопрос «почему не работает» до того,
    как он задан. Каждая строка либо в порядке, либо говорит, что
    именно сделать.
    """
    from app.config import settings
    from app.models import Account, Notice, Shop, StaffUser
    from app.services import billing

    good, bad, warn = [], [], []

    # --- База ---------------------------------------------------------
    try:
        db.query(Account).count()
        if settings.DATABASE_URL.startswith('sqlite'):
            warn.append('База SQLite. Для боевого сервера нужен PostgreSQL: '
                        'пропишите SERVER_DATABASE_URL')
        else:
            good.append('База PostgreSQL отвечает')
    except Exception as e:
        bad.append(f'База недоступна: {e}')
        print_report(good, warn, bad)
        return

    # --- Ключи --------------------------------------------------------
    if settings.SECRET_KEY_FROM_ENV:
        good.append('Ключ подписи задан')
    else:
        bad.append('SERVER_SECRET_KEY не задан: после перезапуска сервера '
                   'всех разлогинит')

    # --- Заказчики и точки --------------------------------------------
    accounts = db.query(Account).all()
    shops = db.query(Shop).all()

    if not accounts:
        bad.append('Ни одного заказчика. Заведите: '
                   'manage.py add-account "Название"')
    else:
        good.append(f'Заказчиков: {len(accounts)}, точек: {len(shops)}')

    without_key = [shop for shop in shops if not shop.sync_key_hash]
    if without_key:
        names = ', '.join(shop.name for shop in without_key)
        bad.append(f'Без ключа обмена: {names}. Выдайте: manage.py new-key имя')

    never = [shop for shop in shops if shop.sync_key_hash and not shop.last_sync_at]
    if never:
        names = ', '.join(shop.name for shop in never)
        warn.append(f'Ещё ни разу не выходили на связь: {names}. '
                    f'Впишите ключ в программе цеха: Настройки → Обмен')

    silent = [shop for shop in shops if shop.last_sync_at
              and (shop_now() - shop.last_sync_at).total_seconds() > 3600]
    if silent:
        names = ', '.join(f'{shop.name} ({day(shop.last_sync_at)})'
                          for shop in silent)
        warn.append(f'Давно не выходили на связь: {names}')

    # --- Дашборд ------------------------------------------------------
    owners = db.query(StaffUser).filter(
        StaffUser.role == 'owner', StaffUser.is_active.is_(True)).count()
    if owners:
        good.append(f'Владельцев дашборда: {owners}')
    elif settings.OWNER_PHONE:
        warn.append('Владелец заведётся при следующем запуске сервера')
    else:
        bad.append('В дашборд войти некому. Впишите SERVER_OWNER_PHONE '
                   'в .env и перезапустите службу')

    # --- Коды входа ---------------------------------------------------
    if settings.SMS_PROVIDER == 'log' and settings.MAIL_PROVIDER == 'log':
        bad.append('Коды входа пишутся в журнал, а не уходят человеку. '
                   'Задайте SERVER_SMS_PROVIDER и SERVER_SMS_API_KEY')
    else:
        good.append(f'Коды входа: {settings.SMS_PROVIDER}')

    # --- Напоминания клиентам -----------------------------------------
    if accounts:
        with_bot = [row for row in accounts if row.telegram_bot_token]
        if not with_bot:
            warn.append('Бот для напоминаний не подключён ни у кого: клиенты '
                        'не узнают о записи. Токен у @BotFather, потом '
                        'manage.py bot имя-заказчика ТОКЕН --url https://домен')
        else:
            stale = [row.name for row in with_bot if not row.telegram_secret]
            if stale:
                bad.append('Бот есть, а адрес для приёма сообщений не задан: '
                           + ', '.join(stale) + '. Повторите manage.py bot '
                           'с --url')
            else:
                names = ', '.join(f'@{row.telegram_bot_username}'
                                  for row in with_bot)
                good.append(f'Напоминания в Telegram: {names}')

        waiting = db.query(Notice).filter(Notice.state == 'failed').count()
        if waiting:
            warn.append(f'Не доставлено сообщений: {waiting}. Обычно это те, '
                        f'кто заблокировал бота')

    # --- Уведомления в браузере ---------------------------------------
    from app.services import webpush

    if webpush.available():
        good.append('Уведомления в браузере настроены')
    else:
        warn.append('Уведомления в браузере выключены: в кабинете нет '
                    'кнопки «Включить». Выдать ключи: manage.py push-keys')

    # --- Оплата -------------------------------------------------------
    if settings.BILLING_ENFORCE:
        overdue = billing.overdue(db)
        if overdue:
            names = ', '.join(row.name for row in overdue)
            warn.append(f'Не оплачено: {names}')
        else:
            good.append('Проверка оплаты включена, должников нет')

    print_report(good, warn, bad)


def print_report(good, warn, bad):
    for line in good:
        print(f'  [ок]   {line}')
    for line in warn:
        print(f'  [!]    {line}')
    for line in bad:
        print(f'  [нет]  {line}')

    print()
    if bad:
        print(f'Не готово: {len(bad)}. Сервер работает, но не так, '
              f'как должен.')
        sys.exit(1)

    print('Всё, что нужно для работы, настроено'
          + (', но есть замечания выше' if warn else ''))


def cmd_bot(db, args):
    """
    Подключить бота заказчику и сказать телеграму, куда слать сообщения.

    Токен берётся у @BotFather: /newbot, имя, готово. Свой бот у
    каждого заказчика — клиент «Колеса» не должен получать сообщения
    от бота «РИФа».
    """
    from app.services import telegram

    account = find_account(db, args.account)

    try:
        telegram.connect_bot(db, account, args.token)
    except telegram.TelegramError as e:
        sys.exit(f'Телеграм не принял токен: {e}')

    print(f'Бот подключён: @{account.telegram_bot_username}')

    if args.url:
        try:
            telegram.set_webhook(account, args.url)
            print(f'Сообщения от людей пойдут на {args.url}/telegram/…')
        except telegram.TelegramError as e:
            sys.exit(f'Не удалось настроить приём сообщений: {e}\n'
                     f'Адрес должен быть с https и смотреть на этот сервер')
    else:
        print()
        print('Приём сообщений не настроен. Когда домен будет готов:')
        print(f'    manage.py bot {account.slug} ТОКЕН --url https://домен.ру')


def cmd_notify(db, args):
    """
    Разослать созревшие напоминания.

    Запускается таймером раз в несколько минут. Напоминание о записи
    лежит в очереди с того момента, как человек записался, и уходит
    накануне приезда.
    """
    from app.models import BY_PUSH, BY_TELEGRAM
    from app.services import notices

    result = notices.send_due(db, limit=args.limit)

    print(f"Отправлено: {result['sent']} "
          f"(телеграм: {result[BY_TELEGRAM]}, браузер: {result[BY_PUSH]}), "
          f"не дошло: {result['failed']}, "
          f"пропущено: {result['skipped']}")


def cmd_push_keys(db, args):
    """
    Пара ключей для уведомлений в браузере.

    Печатаем строки для .env, а не вписываем их сами: файл принадлежит
    серверу, и молча менять его из команды — плохая привычка. К тому же
    смена ключей отписывает всех, кто подписался на старые, поэтому шаг
    должен быть осознанным.
    """
    from app.services import webpush

    if webpush.available() and not args.force:
        print('Ключи уже заданы. Новые отпишут всех, кто подписался на '
              'старые.')
        print('Если это правда нужно: manage.py push-keys --force')
        return

    public, private = webpush.generate_keys()

    print('Впишите в .env и перезапустите службу:')
    print()
    print(f'SERVER_PUSH_PUBLIC_KEY={public}')
    print(f'SERVER_PUSH_PRIVATE_KEY={private}')
    print('SERVER_PUSH_CONTACT=mailto:вашапочта@пример.ру')


def main():
    parser = argparse.ArgumentParser(
        description='Аккаунты, точки и оплата',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)

    commands.add_parser('accounts', help='кто заведён')

    add = commands.add_parser('add-account', help='новый заказчик')
    add.add_argument('name', help='название, как на вывеске')
    add.add_argument('--shop', help='название первой точки, если отличается')

    shop = commands.add_parser('add-shop', help='ещё одна точка')
    shop.add_argument('account', help='короткое имя заказчика')
    shop.add_argument('name', help='название точки')

    key = commands.add_parser('new-key', help='сменить ключ обмена')
    key.add_argument('shop', help='короткое имя точки')

    pay = commands.add_parser('pay', help='записать платёж')
    pay.add_argument('account')
    pay.add_argument('amount', type=float)
    pay.add_argument('--months', type=int, default=1)
    pay.add_argument('--method', default='manual')
    pay.add_argument('--external-id', dest='external_id')
    pay.add_argument('--comment')

    payments = commands.add_parser('payments', help='за что платили')
    payments.add_argument('account')

    block = commands.add_parser('block', help='закрыть доступ')
    block.add_argument('account')
    block.add_argument('--reason')

    unblock = commands.add_parser('unblock', help='открыть доступ')
    unblock.add_argument('account')

    commands.add_parser('overdue', help='кто не заплатил')
    commands.add_parser('check', help='всё ли готово к работе')

    bot = commands.add_parser('bot', help='подключить бота для напоминаний')
    bot.add_argument('account', help='короткое имя заказчика')
    bot.add_argument('token', help='токен от @BotFather')
    bot.add_argument('--url', help='адрес сервера, например https://домен.ру')

    notify = commands.add_parser('notify', help='разослать созревшие напоминания')
    notify.add_argument('--limit', type=int, default=100)

    keys = commands.add_parser('push-keys',
                               help='ключи для уведомлений в браузере')
    keys.add_argument('--force', action='store_true',
                      help='выдать новые, даже если ключи уже есть')

    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        handler = {
            'accounts': cmd_accounts,
            'add-account': cmd_add_account,
            'add-shop': cmd_add_shop,
            'new-key': cmd_new_key,
            'pay': cmd_pay,
            'payments': cmd_payments,
            'block': cmd_block,
            'unblock': cmd_unblock,
            'overdue': cmd_overdue,
            'check': cmd_check,
            'bot': cmd_bot,
            'notify': cmd_notify,
            'push-keys': cmd_push_keys,
        }[args.command]
        handler(db, args)
    finally:
        db.close()


if __name__ == '__main__':
    main()
