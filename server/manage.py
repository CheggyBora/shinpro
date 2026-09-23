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
        }[args.command]
        handler(db, args)
    finally:
        db.close()


if __name__ == '__main__':
    main()
