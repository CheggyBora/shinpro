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

# Насколько вперёд разрешаем занимать место. Час — горизонт, на
# котором ещё можно считать: работы известны, записи известны. Дальше
# это уже не очередь, а запись на время, и для неё есть запись
AHEAD_KEY = 'queue_ahead_minutes'
AHEAD_DEFAULT = 60

# За сколько до своего черёда человек должен быть на месте. Запас не
# только на дорогу: приёмщику надо увидеть машину и оформить
LEAD_KEY = 'queue_lead_minutes'
LEAD_DEFAULT = 20

# Переносов даём один. Не приехал или не успевает — уходит в конец,
# и это единственный раз. Второй — снимаем: место держат люди, которые
# стоят рядом, а ходить по кругу до вечера нельзя
MAX_MOVES = 1


class QueueError(Exception):
    """Понятная человеку причина, почему встать в очередь не вышло."""


# ----------------------------------------------------------------------
# Сколько постов и чем они заняты
# ----------------------------------------------------------------------

def posts_for(db, shop):
    """Сколько постов выделено онлайн-очереди. Это пол, а не потолок."""
    return max(0, shop_settings.get_int(db, 'queue_posts', shop=shop))


def ahead_minutes(db, shop):
    return max(10, shop_settings.get_int(db, AHEAD_KEY, shop=shop)
               or AHEAD_DEFAULT)


def lead_minutes(db, shop):
    return max(0, shop_settings.get_int(db, LEAD_KEY, shop=shop))


def posts_now(db, shop):
    """
    Сколько постов очередь может занять прямо сейчас.

    Выделенный пост — гарантия. Но если живой очереди нет, а общие
    посты свободны, машины из онлайна встают и туда: держать человека
    при пустом боксе незачем.

    Считаем по тому, что цех прислал последним: сколько постов открыто
    и сколько машин в работе. Живая очередь приоритетнее онлайна на
    общих постах, поэтому пока она есть — общие посты не наши.
    """
    from app.models import QueueSnapshot

    mine = posts_for(db, shop)

    last = db.query(QueueSnapshot).filter(
        QueueSnapshot.shop_id == shop.id).order_by(
        QueueSnapshot.taken_at.desc()).first()

    if last is None or not last.shift_is_open:
        return mine

    if last.cars_waiting:
        return mine        # живая очередь впереди нас на общих постах

    free = (last.open_posts or 0) - (last.cars_in_work or 0)
    return max(mine, mine + max(0, free - mine))


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
    posts = max(1, posts_now(db, shop))

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


def _say(db, shop, ticket, text):
    """
    Сказать человеку. Молча проглатываем неудачу.

    Уведомление — не повод уронить работу очереди: приёмщик всё равно
    видит человека на экране и позовёт голосом.
    """
    from app.models import Account, KIND_QUEUE
    from app.services import notices

    if ticket.client is None:
        return False

    account = db.query(Account).filter(Account.id == shop.account_id).first()

    try:
        return bool(notices.send_now(db, ticket.client, account, KIND_QUEUE,
                                     text, about='queue', about_id=ticket.id))
    except Exception as e:
        log.warning('Не сказали клиенту про очередь: %s', e)
        return False


def when_text(db, shop, moment):
    """
    Во сколько подъезжать. Называем время приезда, а не черёд.

    Человеку нужно знать, когда выезжать, а не когда освободится пост:
    разницу в двадцать минут он должен держать не в голове, а видеть
    в сообщении.
    """
    lead = lead_minutes(db, shop)
    return (moment - timedelta(minutes=lead)).strftime('%H:%M')


def tell_joined(db, shop, ticket, now=None):
    """Встал в очередь — сразу говорим, когда подъезжать."""
    times = forecast(db, shop, now)
    turn = times.get(ticket.id)
    if turn is None:
        return False

    ticket.promised_at = turn
    db.commit()

    name = shop_settings.title(db, shop)
    return _say(db, shop, ticket,
                f'<b>{name}</b>\n'
                f'Вы в очереди. Подъезжайте к {when_text(db, shop, turn)}.\n'
                f'Время примерное — если сдвинется, сообщим.')


def tell_moved(db, shop, ticket, now=None):
    """Ушёл в конец — говорим новое время, а не просто «вы последний»."""
    if not ticket.is_open:
        return _say(db, shop, ticket,
                    f'<b>{shop_settings.title(db, shop)}</b>\n'
                    f'Место в очереди закрыто: перенести ещё раз нельзя. '
                    f'Встаньте в очередь заново или запишитесь на время.')

    times = forecast(db, shop, now)
    turn = times.get(ticket.id)
    if turn is None:
        return False

    ticket.promised_at = turn
    db.commit()

    name = shop_settings.title(db, shop)
    return _say(db, shop, ticket,
                f'<b>{name}</b>\n'
                f'Вы перенесены в конец очереди. '
                f'Подъезжайте к {when_text(db, shop, turn)}.\n'
                f'Перенести ещё раз не получится.')


def tell_called(db, shop, ticket):
    """Позвали на пост."""
    return _say(db, shop, ticket,
                f'<b>{shop_settings.title(db, shop)}</b>\n'
                f'Ваша очередь. Проезжайте на пост.')


def offer_sooner(db, shop, now=None, limit=2):
    """
    Освободилось раньше — предложить ближайшим.

    Предложить, а не передвинуть: человек мог не выехать и не смотреть
    в телефон, и построить на нём расчёт нельзя. Кто ответит «готов» —
    того и ждём.

    Зовём несколько человек сразу: один может не ответить вовсе, и
    пост будет стоять, пока мы его дожидаемся.
    """
    name = shop_settings.title(db, shop)
    asked = 0

    for ticket in line(db, shop, now):
        if asked >= limit:
            break
        if ticket.is_here or ticket.offered_at is not None:
            continue

        if _say(db, shop, ticket,
                f'<b>{name}</b>\n'
                f'Освободилось раньше. Успеете подъехать сейчас?\n'
                f'Ответьте в кабинете — если да, место ваше.'):
            ticket.offered_at = shop_now()
            asked += 1

    db.commit()
    return asked


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
    limit = ahead_minutes(db, shop)
    if minutes > limit:
        raise QueueError(
            f'Занять место можно не больше чем за {limit // 60} ч. '
            f'Хотите приехать к определённому времени — запишитесь')

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


def move_back(db, shop, ticket, now=None):
    """
    Не приехал или не успевает — в конец очереди.

    Смещать на одну позицию не стали намеренно: человеку трудно
    объяснить, почему он то второй, то третий, и путаницы от этого
    больше, чем пользы. Правило одно и понятное: не успел — в конец.

    Перенос даём один. Второй раз снимаем: ходить по кругу до вечера
    нельзя, место держат те, кто стоит рядом.

    Чужое время от этого не двигается. Тому, кому назвали 14:30, так
    и идти к 14:30: он на это рассчитывал.
    """
    now = now or shop_now()

    if ticket.moves >= MAX_MOVES:
        return leave(db, ticket, EXPIRED)

    others = [row for row in line(db, shop, now) if row.id != ticket.id]
    last = max((row.eta_at for row in others), default=now)

    ticket.moves += 1
    ticket.state = TICKET_WAITING
    ticket.called_at = None
    ticket.arrived_at = None

    # Встаём за последним, но не раньше, чем через минуту от сейчас:
    # «ваше время — прямо сейчас» после «вы не успели» выглядит
    # издевательством
    ticket.eta_at = max(last, now) + timedelta(minutes=1)

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
    edge = now - timedelta(minutes=ahead_minutes(db, shop))

    gone = 0
    for ticket in db.query(QueueTicket).filter(
            QueueTicket.shop_id == shop.id,
            QueueTicket.state.in_(OPEN_STATES),
            QueueTicket.arrived_at.is_(None),
            QueueTicket.eta_at < edge).all():
        leave(db, ticket, EXPIRED)
        gone += 1

    return gone
