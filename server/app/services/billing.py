"""
Оплата пользования программой.

Пока заказчик один — свой собственный шиномонтаж, — платить некому, и
проверка выключена. Но появится второй, и вопрос «а он вообще платит»
придётся задавать каждому запросу. Место для этого вопроса заводится
сейчас: потом такие вещи вставляются в работающую систему кровью.

**Откуда берётся срок.** Из платежей. Каждый платёж — строка в
`account_payments`: когда, сколько, за какой отрезок и откуда про него
узнали. Срок в аккаунте складывается из этих строк, а не правится
руками: иначе через полгода никто не объяснит, почему там эта дата.

Сегодня платёж отмечается вручную — деньги пришли на счёт, вы их
записали. Завтра то же самое сделает платёжная система: у строки есть
поле для её номера платежа, и повторное уведомление не создаст вторую
запись.

**Что происходит, когда не оплачено.** Ничего резкого. Сначала
отсрочка — несколько дней после конца срока, когда всё работает как
работало: человек мог уехать, забыть, перепутать дату. Потом
закрывается онлайн: кабинет клиента, запись, дашборд.

**Что не закрывается никогда** — программа в цеху и обмен с ней. Цех
принимает машины, печатает чеки и считает зарплату без интернета
вообще, а обмен продолжает идти, чтобы данные не потерялись и всё
ожило сразу после оплаты. Отключать кассу за неоплату — это не
взыскание долга, а порча чужой работы.
"""
from datetime import timedelta

from app.config import settings
from app.models import Account, AccountPayment
from app.utils import now as shop_now

# Состояния, в которых бывает аккаунт
FREE = 'free'            # платить некому: срок не задан
PAID = 'paid'            # оплачено
GRACE = 'grace'          # срок вышел, идёт отсрочка
OVERDUE = 'overdue'      # отсрочка кончилась
BLOCKED = 'blocked'      # закрыт вручную

TITLES = {
    FREE: 'Без оплаты',
    PAID: 'Оплачено',
    GRACE: 'Срок вышел, идёт отсрочка',
    OVERDUE: 'Не оплачено',
    BLOCKED: 'Доступ закрыт',
}


def grace_days():
    return max(0, settings.BILLING_GRACE_DAYS)


def state(account):
    """
    Что с оплатой у этого аккаунта.

    Возвращает словарь: состояние, до какого числа оплачено, сколько
    дней осталось, закрывать ли онлайн. Одним словом это не описать —
    «не оплачено» и «пора закрывать» разные вещи, между ними отсрочка.
    """
    if account is None:
        return {'state': FREE, 'title': TITLES[FREE], 'paid_until': None,
                'days_left': None, 'grace_until': None, 'is_open': True}

    now = shop_now()

    if account.blocked_at is not None or not account.is_active:
        return {'state': BLOCKED, 'title': TITLES[BLOCKED],
                'paid_until': account.paid_until, 'days_left': None,
                'grace_until': None, 'is_open': False,
                'reason': account.block_reason}

    if account.paid_until is None:
        return {'state': FREE, 'title': TITLES[FREE], 'paid_until': None,
                'days_left': None, 'grace_until': None, 'is_open': True}

    grace_until = account.paid_until + timedelta(days=grace_days())
    left = (account.paid_until - now).days

    if account.paid_until >= now:
        name = PAID
    elif grace_until >= now:
        name = GRACE
    else:
        name = OVERDUE

    return {
        'state': name,
        'title': TITLES[name],
        'paid_until': account.paid_until,
        'days_left': left,
        'grace_until': grace_until,
        # Пока проверка выключена, открыто всё и всегда: включать её
        # разом на работающей системе нельзя
        'is_open': name in (PAID, GRACE) or not settings.BILLING_ENFORCE,
    }


def is_open(account):
    """Доступен ли онлайн этому аккаунту прямо сейчас."""
    return state(account)['is_open']


def record_payment(db, account, amount, months=1, until=None, method='manual',
                   external_id=None, comment=None, paid_at=None):
    """
    Записать платёж и продлить срок.

    Продление считается от текущего срока, а не от сегодня: заплатил
    заранее — время не сгорает. Если срок давно прошёл, считаем от
    сегодня: продавать задним числом месяц, которым не пользовались,
    нечестно.

    external_id — номер платежа в платёжной системе. Тот же номер
    второй раз не проходит: уведомления приходят по два раза, и это
    обычное дело.
    """
    if external_id:
        already = db.query(AccountPayment).filter(
            AccountPayment.external_id == external_id).first()
        if already is not None:
            return already

    now = paid_at or shop_now()
    start = account.paid_until if (account.paid_until
                                   and account.paid_until > now) else now

    if until is not None:
        finish = until
    else:
        # Месяц считаем в днях: 31-го числа «плюс месяц» иначе
        # превращается в спор о том, какое это число
        finish = start + timedelta(days=30 * max(1, int(months)))

    payment = AccountPayment(
        account_id=account.id,
        amount=float(amount or 0),
        paid_at=now,
        period_from=start,
        period_to=finish,
        method=method,
        external_id=external_id,
        comment=comment)

    db.add(payment)
    account.paid_until = finish

    # Оплата снимает ручное закрытие: деньги пришли — работаем
    account.blocked_at = None
    account.block_reason = None

    db.commit()
    db.refresh(payment)
    return payment


def block(db, account, reason=None):
    """Закрыть доступ вручную — по решению, а не за неоплату."""
    account.blocked_at = shop_now()
    account.block_reason = (reason or '')[:255] or None
    db.commit()
    return account


def unblock(db, account):
    account.blocked_at = None
    account.block_reason = None
    db.commit()
    return account


def expiring(db, days=3):
    """
    У кого срок кончается на днях.

    Пригодится, когда дойдут руки до напоминаний: счёт лучше выставить
    до того, как человек упёрся в закрытый дашборд.
    """
    now = shop_now()
    limit = now + timedelta(days=days)

    return db.query(Account).filter(
        Account.is_active.is_(True),
        Account.blocked_at.is_(None),
        Account.paid_until.isnot(None),
        Account.paid_until >= now,
        Account.paid_until <= limit).order_by(Account.paid_until).all()


def overdue(db):
    """Кто не заплатил и отсрочку уже прожил."""
    edge = shop_now() - timedelta(days=grace_days())

    return db.query(Account).filter(
        Account.is_active.is_(True),
        Account.blocked_at.is_(None),
        Account.paid_until.isnot(None),
        Account.paid_until < edge).order_by(Account.paid_until).all()
