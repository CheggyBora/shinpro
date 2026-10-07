"""
Напоминания, которые сервер придумывает сам.

Остальные уведомления вызваны действием: записались — подтвердили,
перенесли — сказали. Эти два рождаются от календаря, и о них никто не
попросит, если сервер промолчит.

**Заканчивается хранение.** Комплект лежит оплаченный срок. Молчать до
последнего дня нельзя: человек либо приедет забирать в спешке, либо
узнает о долге постфактум. Предупреждаем заранее — за столько дней,
сколько сказал цех.

**Пора переобуваться.** Осенью зовём заранее: когда ляжет снег, запись
будет на неделю вперёд, и человек либо отстоит очередь, либо поедет на
летней по гололёду. Весной наоборот, позже — переобувшийся в марте
попадёт под возвратные заморозки и приедет второй раз.

**Кому пишем.** Тем, чей комплект у нас лежит, и тем, кто обслуживался
за последний год. Человек, пропавший на три года, скорее всего продал
машину или нашёл другой шиномонтаж; письмо ему — не забота, а реклама,
после которой он отключит напоминания совсем.

**Каждое — один раз.** Повтор определяется по уже стоящей в очереди
строке: о комплекте предупреждаем однажды, о сезоне — раз в год.
Иначе задача, запускаемая каждые пять минут, завалила бы человека
одинаковыми сообщениями.
"""
import logging
from datetime import timedelta

from app.models import (Client, Notice, Shop, StoredSet, Visit,
                        KIND_SEASON, KIND_STORAGE,
                        ABOUT_AUTUMN, ABOUT_SPRING, SKIPPED)
from app.services import notices, shop_settings
from app.utils import now as shop_now

log = logging.getLogger('tire_server')

# Насколько давно человек был, чтобы считаться нашим. Год: сезон
# бывает раз в полгода, и пропустивший один визит ещё не ушёл
ACTIVE_DAYS = 365

# Сколько дней после назначенной даты мы ещё готовы позвать. Сервер мог
# лежать, цех мог не включить — но звать переобуваться в декабре, если
# дата была в октябре, уже поздно и глупо
CATCH_UP_DAYS = 14


# ----------------------------------------------------------------------
# Заканчивается срок хранения
# ----------------------------------------------------------------------

def storage_text(shop_name, stored, days):
    what = ' '.join(part for part in [stored.storage_type, stored.diameter]
                    if part) or 'комплект'

    when = (f'истекает {stored.expires_at.strftime("%d.%m")}' if days >= 0
            else f'истёк {stored.expires_at.strftime("%d.%m")}')

    return (f'<b>{shop_name}</b>\n'
            f'Срок хранения вашего комплекта {when}.\n'
            f'{what}'
            + (f', {stored.license_plate}' if stored.license_plate else '')
            + '\n\nПродлить или забрать — запишитесь в кабинете или '
              'позвоните нам.')


def plan_storage(db, shop):
    """Предупредить тех, у кого заканчивается хранение."""
    warn_days = _int(shop_settings.get(db, 'storage_warn_days', shop=shop), 7)

    edge = shop_now() + timedelta(days=warn_days)
    name = _shop_name(db, shop)

    rows = db.query(StoredSet).filter(
        StoredSet.shop_id == shop.id,
        StoredSet.status == 'stored',
        StoredSet.client_id.isnot(None),
        StoredSet.expires_at.isnot(None),
        StoredSet.expires_at <= edge).all()

    made = []
    for stored in rows:
        if _already(db, 'storage', stored.id):
            continue

        client = db.query(Client).filter(Client.id == stored.client_id).first()
        if client is None:
            continue

        days = (stored.expires_at - shop_now()).days
        notice = notices.add(db, client, KIND_STORAGE,
                             storage_text(name, stored, days),
                             about='storage', about_id=stored.id)

        # Строку оставляем даже пропущенной: по ней видно, что
        # предупредить было нечем, и второй раз мы не пробуем
        if notice.state != SKIPPED:
            made.append(notice)

    return made


# ----------------------------------------------------------------------
# Пора переобуваться
# ----------------------------------------------------------------------

def season_text(shop_name, season, has_storage):
    if season == ABOUT_AUTUMN:
        body = ('Пора переобуваться в зимнюю. Запишитесь сейчас, пока нет '
                'очередей: когда ляжет снег, ближайшее окно будет через '
                'несколько дней.')
    else:
        body = ('Можно переобуваться в летнюю — заморозки позади. '
                'Запишитесь на удобное время в кабинете.')

    return (f'<b>{shop_name}</b>\n' + body
            + ('\n\nВаш комплект лежит у нас — доставим к приезду.'
               if has_storage else ''))


def season_due(db, shop, today=None):
    """
    Какой сезон пора объявить сегодня. None — ещё или уже не время.

    Дату назначает цех: в Мурманске и в Краснодаре снег ложится в
    разные месяцы, и выдумывать за них одно число нельзя.
    """
    if shop_settings.get(db, 'season_reminders_enabled',
                         shop=shop) not in ('1', 'true', 'yes'):
        return None

    today = (today or shop_now()).date()

    for about, key in ((ABOUT_AUTUMN, 'season_autumn_at'),
                       (ABOUT_SPRING, 'season_spring_at')):
        when = _day_month(shop_settings.get(db, key, shop=shop), today.year)
        if when is None:
            continue

        if 0 <= (today - when).days <= CATCH_UP_DAYS:
            return about

    return None


def plan_season(db, shop, today=None):
    """Позвать на перекидку тех, кто ещё наш."""
    season = season_due(db, shop, today)
    if season is None:
        return []

    year = (today or shop_now()).year
    name = _shop_name(db, shop)

    stored = {row.client_id: row for row in db.query(StoredSet).filter(
        StoredSet.shop_id == shop.id,
        StoredSet.status == 'stored',
        StoredSet.client_id.isnot(None)).all()}

    been = {row[0] for row in db.query(Visit.client_id).filter(
        Visit.shop_id == shop.id,
        Visit.client_id.isnot(None),
        Visit.is_deleted.is_(False),
        Visit.visited_at >= shop_now() - timedelta(days=ACTIVE_DAYS)
    ).distinct().all()}

    made = []
    for client_id in sorted(set(stored) | been):
        # Человек мог приезжать на обе точки — зовём один раз
        if _already(db, season, year, client_id=client_id):
            continue

        client = db.query(Client).filter(Client.id == client_id).first()
        if client is None:
            continue

        notice = notices.add(db, client, KIND_SEASON,
                             season_text(name, season, client_id in stored),
                             about=season, about_id=year)

        if notice.state != SKIPPED:
            made.append(notice)

    return made


# ----------------------------------------------------------------------
# Всё сразу
# ----------------------------------------------------------------------

def plan_all(db, today=None):
    """
    Пройти по точкам и разложить созревшее по очереди.

    Отправкой занимается `notices.send_due`: здесь только решается, что
    сказать и кому.
    """
    result = {'storage': 0, 'season': 0}

    for shop in db.query(Shop).filter(Shop.is_active.is_(True)).all():
        try:
            result['storage'] += len(plan_storage(db, shop))
            result['season'] += len(plan_season(db, shop, today))
        except Exception as e:
            # Одна сломанная точка не должна оставить без напоминаний
            # все остальные
            log.warning('Точка №%s: не вышло запланировать напоминания: %s',
                        shop.id, e)
            db.rollback()

    return result


# ----------------------------------------------------------------------
# Мелочи
# ----------------------------------------------------------------------

def _already(db, about, about_id, client_id=None):
    """Не говорили ли мы об этом уже. Состояние неважно: сказали — хватит."""
    query = db.query(Notice).filter(Notice.about == about,
                                    Notice.about_id == about_id)
    if client_id is not None:
        query = query.filter(Notice.client_id == client_id)

    return db.query(query.exists()).scalar()


def _shop_name(db, shop):
    return shop_settings.get(db, 'shop_name', shop=shop) or shop.name


def _int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _day_month(text, year):
    """«01.10» и год — в дату. Мусор в настройке молча пропускаем."""
    try:
        day, month = str(text).split('.')[:2]
        return shop_now().replace(year=year, month=int(month), day=int(day)).date()
    except (TypeError, ValueError):
        return None
