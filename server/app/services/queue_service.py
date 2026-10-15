"""
Онлайн-очередь: кто за кем и когда примерно подойдёт черёд.

Правила, которые тут держатся, в порядке важности.

**Порядок — по времени прибытия, а не по времени нажатия.** Человек
говорит, через сколько будет. Тот, кто приедет раньше, и обслужится
раньше. Иначе житель соседнего дома ждёт того, кто едет час, а пост
всё это время стоит пустым.

**Звать можно только того, кто на месте.** Подошла очередь, а машины
у ворот нет — берём следующего, кто приехал. Место не сгорает:
человек смещается на позицию, а не вылетает. Два промаха — снимаем,
потому что рядом стоят живые люди.

**Пост под очередь не простаивает.** Нет никого из онлайна — туда
встаёт живая очередь, приёмщик это отмечает, и прогноз сдвигается на
время её работ. Простой поста хуже, чем сдвинутый прогноз.

**Запись сюда не относится вовсе.** Она идёт на свои посты и вне
очереди: записанный на 14:00 встаёт в 14:00.
"""
import logging
from datetime import timedelta

from app.models import (CALLED, CANCELLED, EXPIRED, OPEN_STATES, QueueTicket,
                        SERVED, TICKET_WAITING)
from app.services import shop_settings
from app.utils import now as shop_now, normalize_plate, normalize_phone

log = logging.getLogger('tire_server')

# Насколько вперёд разрешаем занимать место. Полдня — уже не очередь,
# а запись, и для неё есть запись
MAX_AHEAD_HOURS = 6

# Сколько промахов терпим, прежде чем снять талон
MAX_MISSED = 2

# Сколько ждём человека после того, как позвали
CALL_PATIENCE_MINUTES = 15


class QueueError(Exception):
    """Понятная человеку причина, почему встать в очередь не вышло."""


# ----------------------------------------------------------------------
# Сколько постов и чем они заняты
# ----------------------------------------------------------------------

def posts_for(db, shop):
    """Сколько постов отдано онлайн-очереди."""
    return max(0, shop_settings.get_int(db, 'queue_posts', shop=shop))


def enabled(db, shop):
    return posts_for(db, shop) > 0


def busy_until(db, shop, now=None):
    """
    Когда освободится пост очереди, если его заняли не из очереди.

    Цех присылает, какие машины сейчас в работе. Если приёмщик отметил,
    что на пост очереди встала машина из живой, — до её окончания звать
    из онлайна некого, и прогноз надо сдвинуть. Молчать об этом нельзя:
    человек приедет к названному времени и будет стоять.
    """
    from app.models import OpenOrder

    now = now or shop_now()
    rows = db.query(OpenOrder).filter(
        OpenOrder.shop_id == shop.id,
        OpenOrder.on_queue_post.is_(True),
        OpenOrder.state == 'work').all()

    if not rows:
        return None

    # Берём самое позднее окончание: пост занят, пока не закончится
    # последняя вставшая на него машина
    latest = None
    for row in rows:
        ends = (row.started_at or now) + timedelta(
            minutes=row.planned_minutes or 0)
        if latest is None or ends > latest:
            latest = ends

    return latest if latest and latest > now else None


# ----------------------------------------------------------------------
# Очередь
# ----------------------------------------------------------------------

def line(db, shop, now=None):
    """
    Очередь по порядку: кто первый, тот и раньше приедет.

    На месте и ждёт — вперёд тех, кто ещё едет и обещает быть позже.
    Сравниваем именно по обещанному времени, иначе порядок зависел бы
    от того, кто быстрее нажал кнопку.
    """
    now = now or shop_now()

    rows = db.query(QueueTicket).filter(
        QueueTicket.shop_id == shop.id,
        QueueTicket.state.in_(OPEN_STATES)).all()

    def order(ticket):
        # Позванный — всегда первый: его уже ждут на посту
        if ticket.state == CALLED:
            return (0, ticket.called_at or now)

        # Приехавший считается прибывшим сейчас, а не когда обещал:
        # он уже здесь, и держать его за обещание «через час» нелепо
        when = ticket.arrived_at or ticket.eta_at

        # Приехали в одно время — первым идёт тот, кто встал раньше.
        # Без этого порядок двоих, обещавших «через 15 минут», зависел
        # бы от того, как база вернула строки
        return (1, when, ticket.created_at)

    return sorted(rows, key=order)


def forecast(db, shop, now=None):
    """
    Когда примерно подойдёт очередь каждого. Возвращает {id: время}.

    Считаем по-простому: берём время работ каждого впереди стоящего и
    складываем. Хитрее считать нечем — в шиномонтаже время работ
    известно заранее, а неожиданности одинаково ломают любую формулу.
    """
    now = now or shop_now()
    posts = max(1, posts_for(db, shop))

    # Пост мог быть занят машиной из живой очереди
    occupied = busy_until(db, shop, now)
    free_at = [occupied or now] * posts

    answer = {}
    for ticket in line(db, shop, now):
        soonest = min(free_at)
        index = free_at.index(soonest)

        # Раньше, чем человек доедет, его не позовут. Приехавший
        # считается готовым сейчас, ждущий — к обещанному времени
        ready = now if ticket.is_here else ticket.eta_at
        starts = max(soonest, ready, now)
        answer[ticket.id] = starts

        free_at[index] = starts + timedelta(minutes=_minutes_for(db, shop, ticket))

    return answer


def _minutes_for(db, shop, ticket):
    """Сколько займёт работа. Те же числа, что при записи."""
    if ticket.wheels_assembled is True:
        key = 'booking_minutes_assembled'
    elif ticket.wheels_assembled is False:
        key = 'booking_minutes_tires'
    else:
        key = 'booking_minutes_unknown'

    return max(5, shop_settings.get_int(db, key, shop=shop))


def remember_promise(db, shop, now=None, tolerance_minutes=10):
    """
    Запомнить названное время и сказать тем, у кого оно уехало.

    Человеку называют время, и он строит на нём планы: выехать,
    отпроситься, отвезти ребёнка. Молча сдвинуть его — это заставить
    его стоять и гадать.

    Небольшой сдвиг не трогаем: работа идёт живыми людьми, и сообщение
    «ваше время сдвинулось на три минуты» раздражает, а не помогает.

    Возвращает тех, кому надо сказать.
    """
    now = now or shop_now()
    times = forecast(db, shop, now)
    slipped = []

    for ticket in line(db, shop, now):
        fresh = times.get(ticket.id)
        if fresh is None:
            continue

        was = ticket.promised_at
        ticket.promised_at = fresh

        if was is None:
            continue

        # Назад время двигаем молча: «приезжайте раньше» — не новость,
        # ради которой стоит будить человека, а обещание, которое мы
        # не сможем держать, если он уже выехал
        if fresh - was >= timedelta(minutes=tolerance_minutes):
            slipped.append((ticket, was, fresh))

    db.commit()
    return slipped


def tell_slipped(db, shop, now=None):
    """
    Сказать тем, у кого уехало время.

    Отдельно от расчёта: считать время надо на каждый показ экрана, а
    беспокоить человека — только когда есть о чём. Зовётся из цеха,
    когда приёмщик смотрит очередь, и при обмене.
    """
    from app.models import Account, KIND_QUEUE
    from app.services import notices

    account = db.query(Account).filter(Account.id == shop.account_id).first()
    name = shop_settings.title(db, shop)

    told = 0
    for ticket, was, fresh in remember_promise(db, shop, now):
        if ticket.client is None:
            continue

        text = (f'<b>{name}</b>\n'
                f'Очередь сдвинулась: теперь примерно '
                f'{fresh.strftime("%H:%M")} вместо {was.strftime("%H:%M")}.'
                + (f'\n{ticket.license_plate}'
                   if ticket.license_plate else ''))

        try:
            sent = notices.send_now(db, ticket.client, account, KIND_QUEUE,
                                    text, about='queue', about_id=ticket.id)
        except Exception as e:
            log.warning('Не сказали о сдвиге очереди: %s', e)
            continue

        if sent:
            ticket.promise_told_at = shop_now()
            told += 1

    db.commit()
    return told


def place_of(db, shop, ticket, now=None):
    """Какой он по счёту. Единица — следующий."""
    for number, row in enumerate(line(db, shop, now), start=1):
        if row.id == ticket.id:
            return number
    return None


# ----------------------------------------------------------------------
# Встать, отметиться, уйти
# ----------------------------------------------------------------------

def join(db, shop, client, minutes_away, plate=None, wheels_assembled=None,
         comment=None, now=None):
    """
    Встать в очередь. minutes_away — через сколько человек будет на месте.
    """
    now = now or shop_now()

    if not enabled(db, shop):
        raise QueueError('Онлайн-очередь сейчас не работает. '
                         'Запишитесь на время или подъезжайте')

    try:
        minutes = int(minutes_away)
    except (TypeError, ValueError):
        raise QueueError('Непонятно, через сколько вы будете')

    if minutes < 0:
        minutes = 0
    if minutes > MAX_AHEAD_HOURS * 60:
        raise QueueError(
            f'Занять место можно не больше чем за {MAX_AHEAD_HOURS} ч. '
            f'На более дальнее время есть запись')

    already = db.query(QueueTicket).filter(
        QueueTicket.shop_id == shop.id,
        QueueTicket.client_id == client.id,
        QueueTicket.state.in_(OPEN_STATES)).first()

    if already is not None:
        raise QueueError('Вы уже в очереди')

    ticket = QueueTicket(
        shop_id=shop.id,
        client_id=client.id,
        license_plate=normalize_plate(plate) or None,
        client_name=client.name,
        client_phone=normalize_phone(client.phone),
        wheels_assembled=wheels_assembled,
        comment=(comment or '').strip() or None,
        eta_at=now + timedelta(minutes=minutes),
        arrived_at=now if minutes == 0 else None,
        state=TICKET_WAITING)

    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def arrived(db, shop, ticket, now=None):
    """Отметить, что человек на месте. Без этого звать его нельзя."""
    if not ticket.is_open:
        raise QueueError('Это место уже закрыто')

    if ticket.arrived_at is None:
        ticket.arrived_at = now or shop_now()
        db.commit()

    return ticket


def leave(db, ticket, reason=CANCELLED):
    """Уйти из очереди — сам или по решению приёмщика."""
    ticket.state = reason
    ticket.closed_at = shop_now()
    db.commit()
    return ticket


# ----------------------------------------------------------------------
# Что делает приёмщик
# ----------------------------------------------------------------------

def next_up(db, shop, now=None):
    """
    Кого звать следующим. Только того, кто на месте.

    Машины у ворот нет — звать некого: пост простоит, пока человек
    едет. Берём следующего приехавшего, а пропущенный смещается.
    """
    for ticket in line(db, shop, now):
        if ticket.state == CALLED:
            return ticket
        if ticket.is_here:
            return ticket
    return None


def call(db, shop, ticket, now=None):
    """Позвать на пост."""
    now = now or shop_now()

    if not ticket.is_here:
        raise QueueError('Человека ещё нет на месте')

    ticket.state = CALLED
    ticket.called_at = now
    db.commit()
    return ticket


def miss(db, ticket):
    """
    Не подошёл. Смещаем, а не выгоняем.

    Два промаха — снимаем: место держат люди, которые стоят рядом.
    """
    ticket.missed += 1
    ticket.state = TICKET_WAITING
    ticket.called_at = None

    if ticket.missed >= MAX_MISSED:
        return leave(db, ticket, EXPIRED)

    db.commit()
    return ticket


def served(db, ticket, order_local_id=None):
    """Машину взяли в работу — дальше обычный наряд."""
    ticket.state = SERVED
    ticket.order_local_id = order_local_id
    ticket.closed_at = shop_now()
    db.commit()
    return ticket


def drop_stale(db, shop, now=None):
    """
    Убрать тех, кто обещал и не приехал.

    Ждём с запасом после обещанного времени: пробки — это нормально,
    и выкидывать человека за десять минут опоздания нельзя. Но место
    в очереди не вечное, иначе список к вечеру состоит из тех, кто
    давно передумал.
    """
    now = now or shop_now()
    edge = now - timedelta(hours=MAX_AHEAD_HOURS)

    gone = 0
    for ticket in db.query(QueueTicket).filter(
            QueueTicket.shop_id == shop.id,
            QueueTicket.state.in_(OPEN_STATES),
            QueueTicket.arrived_at.is_(None),
            QueueTicket.eta_at < edge).all():
        leave(db, ticket, EXPIRED)
        gone += 1

    return gone
