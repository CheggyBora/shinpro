"""
Календарь задач: обмен с цехом, дашборд, задачи из кабинета, сводка.

Задача одна на цех и сервер (docs/calendar.md). Меняют её с двух
сторон, поэтому правило одно на всех: побеждает более поздняя правка.
При равенстве сервер свою строку не трогает — пришло то же самое.

Сервер ставит задачи и сам: клиент заказал комплект со склада из
кабинета — кладовщику нужна задача «Привезти со склада» к дате, а не
только сообщение в Telegram, которое пролистают. Такие задачи получают
предсказуемый uid («cab-appt-12»): повторный запрос находит ту же
задачу и не ставит вторую.
"""
import html
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone

from app.models import Task, Counterparty, CATEGORY_TITLES, SOURCES
from app.models.task import (SOURCE_CABINET, SOURCE_DASHBOARD, SOURCE_SHOP,
                             STORAGE, TIRE, WASH, DIRECTIONS,
                             DIRECTION_CATEGORIES)
from app.utils import (normalize_plate, normalize_phone, now as shop_now,
                       MOSCOW_OFFSET_HOURS)

log = logging.getLogger('tire_server')

# Первый обмен: сколько дней назад брать задачи. Старше — дело прошлое,
# и тащить в цех весь архив за годы незачем
FIRST_SYNC_DAYS = 60

# Запас при выборке «изменённых после». Правка из дашборда могла
# получить время чуть раньше, чем обмен прочитал базу, а записаться
# чуть позже — без запаса цех её бы пропустил навсегда. Повтор той же
# строки цеху не вредит: он просто перезапишет её тем же
SINCE_OVERLAP = timedelta(seconds=5)

# Длины полей — по колонкам таблицы. Лишнее обрезаем, а не отказываем:
# цех не должен застрять на обмене из-за длинной заметки
LIMITS = {
    'uid': 40, 'title': 200, 'note': 4000, 'license_plate': 20,
    'client_name': 200, 'client_phone': 20, 'counterparty_uid': 40,
    'storage_ref': 100, 'done_by': 100, 'created_by': 100, 'source': 20,
}
COUNTERPARTY_LIMITS = {
    'uid': 40, 'name': 200, 'kind': 200, 'contact': 200, 'phone': 40,
    'email': 200, 'address': 300, 'inn': 20, 'note': 4000,
}


class TaskError(ValueError):
    """Понятная человеку причина, почему задачу не приняли."""


# ----------------------------------------------------------------------
# Разбор присланного
# ----------------------------------------------------------------------

def _stamp(row, now):
    """
    Отметить правку. Время правки — строго позже прошлой: обмен решает,
    чья версия новее, по секундам, и две правки в одну секунду (поставили
    и тут же отметили) иначе выглядели бы как одна — вторая потерялась бы.
    """
    now = (now or shop_now()).replace(microsecond=0)
    if row.updated_at is not None and now <= row.updated_at:
        now = row.updated_at.replace(microsecond=0) + timedelta(seconds=1)
    row.updated_at = now


def _text(value, limit):
    if value is None:
        return None
    value = str(value).strip()
    return value[:limit] or None


def parse_moment(value):
    """
    ISO-строка в московское время без пояса.

    Цех шлёт московское без пояса. Если пояс всё же указан — переводим
    в московское: сравнивать «12:00+00:00» с «12:00» как одно и то же
    значило бы ошибиться на три часа в том, чья правка новее.
    """
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        raw = str(value).strip()
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return None

    if moment.tzinfo is not None:
        moment = (moment.astimezone(timezone.utc).replace(tzinfo=None)
                  + timedelta(hours=MOSCOW_OFFSET_HOURS))
    return moment


def parse_day(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def parse_clock(value):
    """
    «9:5», «09:05», «09:05:00» → «09:05». Пусто — None.

    Неразборчивое — ошибка, а не «без времени»: задача, тихо потерявшая
    время, всплывёт не тогда, когда её ждут.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parts = [int(part) for part in raw.split(':')[:2]]
        hours, minutes = parts[0], parts[1] if len(parts) > 1 else 0
    except (ValueError, IndexError):
        raise TaskError('Время — как 09:00')
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise TaskError('Такого времени не бывает')
    return f'{hours:02d}:{minutes:02d}'


def _amount(value):
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise TaskError('Сумма — числом')
    return round(number, 2)


def parse_direction(value):
    """
    Направление задачи или контрагента: tire или wash.

    Пусто и непонятное — шиномонтаж: старый цех направления не присылает,
    и всё, что он ведёт, — шиномонтаж. Отказывать из-за этого нельзя,
    иначе обмен со старым цехом встал бы целиком.
    """
    value = str(value or '').strip().lower()
    return value if value in DIRECTIONS else TIRE


# Почему раздел не подходит — словами, которые видит владелец
CATEGORY_ERRORS = {
    TIRE: 'У шиномонтажа разделы: Рабочая, Хранение, Шины, Покраска '
          '(work, storage, tires, paint)',
    WASH: 'У мойки разделы: Рабочая и Поставки (work, supply)',
}


def clean_fields(data, partial=False, direction=None):
    """
    Поля задачи из присланного — проверенные и обрезанные.

    partial — правка: берём только то, что прислали. Иначе задача целиком,
    и раздел, дата и заголовок обязательны.

    direction — слой, в котором проверяем раздел. У правки это слой самой
    задачи: правкой задачу в другой слой не переносят. У целой задачи не
    задано — берём из присланного.
    """
    fields = {}

    def given(key):
        return key in data if partial else True

    if not partial:
        direction = direction or parse_direction(data.get('direction'))
        fields['direction'] = direction
    direction = direction or TIRE

    if given('category'):
        category = str(data.get('category') or '').strip().lower()
        # «Хранение» у мойки и «Поставки» у шиномонтажа — ошибка, а не
        # повод угадывать: задача попала бы в раздел, которого в этом
        # слое не показывают, и пропала бы с глаз
        if category not in DIRECTION_CATEGORIES[direction]:
            raise TaskError(CATEGORY_ERRORS[direction])
        fields['category'] = category

    if given('due_date'):
        day = parse_day(data.get('due_date'))
        if day is None:
            raise TaskError('Дата задачи — как 2026-10-27')
        fields['due_date'] = day

    if given('due_time'):
        fields['due_time'] = parse_clock(data.get('due_time'))

    if given('title'):
        title = _text(data.get('title'), LIMITS['title'])
        if not title:
            raise TaskError('Напишите, что за задача')
        fields['title'] = title

    for key in ('note', 'client_name', 'counterparty_uid', 'storage_ref'):
        if given(key):
            fields[key] = _text(data.get(key), LIMITS[key])

    if given('license_plate'):
        fields['license_plate'] = (
            normalize_plate(data.get('license_plate'))[:LIMITS['license_plate']]
            or None)

    if given('client_phone'):
        phone = data.get('client_phone')
        fields['client_phone'] = ((normalize_phone(phone)[:20] or _text(phone, 20))
                                  if phone else None)

    if given('amount'):
        fields['amount'] = _amount(data.get('amount'))

    return fields


# ----------------------------------------------------------------------
# Вид для обмена и дашборда
# ----------------------------------------------------------------------

def _iso(moment):
    return moment.isoformat(timespec='seconds') if moment else None


def to_dict(task):
    return {
        'uid': task.uid,
        'direction': task.direction or TIRE,
        'category': task.category,
        'due_date': task.due_date.isoformat() if task.due_date else None,
        'due_time': task.due_time,
        'title': task.title,
        'note': task.note,
        'license_plate': task.license_plate,
        'client_name': task.client_name,
        'client_phone': task.client_phone,
        'counterparty_uid': task.counterparty_uid,
        'storage_ref': task.storage_ref,
        'amount': task.amount,
        'done_at': _iso(task.done_at),
        'done_by': task.done_by,
        'deleted': bool(task.deleted),
        'source': task.source,
        'created_by': task.created_by,
        'created_at': _iso(task.created_at),
        'updated_at': _iso(task.updated_at),
    }


def counterparty_dict(row):
    return {
        'uid': row.uid,
        'direction': row.direction or TIRE,
        'name': row.name,
        'kind': row.kind,
        'contact': row.contact,
        'phone': row.phone,
        'email': row.email,
        'address': row.address,
        'inn': row.inn,
        'note': row.note,
        'deleted': bool(row.deleted),
        'updated_at': _iso(row.updated_at),
    }


# ----------------------------------------------------------------------
# Обмен с цехом
# ----------------------------------------------------------------------

def _newer(theirs, mine):
    """Присланное новее нашего? При равенстве — нет: это то же самое."""
    if mine is None:
        return True
    return theirs > mine


def _kept_direction(item, row):
    """
    Направление, если цех его не прислал: то, что уже стоит у строки.

    Старый цех направления не знает, но задачу мойки, поставленную из
    дашборда, получает и может отметить. Без этого его отметка тихо
    переносила бы задачу в шиномонтаж. Новой строке — None: её
    направление разберёт clean_fields, и пустое станет шиномонтажом.
    """
    if 'direction' in item or row is None:
        return None
    return row.direction or TIRE


def merge_tasks(db, shop, items, now=None):
    """
    Принять задачи из цеха. Возвращает uid тех, что принять нельзя.

    Негодную строку пропускаем, а не роняем весь обмен: одна задача с
    испорченной датой не должна останавливать все остальные.
    """
    now = now or shop_now()
    rejected = []

    for item in items or []:
        if not isinstance(item, dict):
            continue
        uid = _text(item.get('uid'), LIMITS['uid'])
        if not uid:
            continue

        row = db.query(Task).filter(Task.shop_id == shop.id,
                                    Task.uid == uid).first()

        try:
            fields = clean_fields(item, direction=_kept_direction(item, row))
        except TaskError as e:
            log.warning('Точка №%s: задача %s не принята: %s', shop.id, uid, e)
            rejected.append(uid)
            continue

        theirs = parse_moment(item.get('updated_at')) or now
        if row is not None and not _newer(theirs, row.updated_at):
            continue

        if row is None:
            row = Task(shop_id=shop.id, uid=uid,
                       created_at=parse_moment(item.get('created_at')) or now)
            db.add(row)

        for key, value in fields.items():
            setattr(row, key, value)
        row.done_at = parse_moment(item.get('done_at'))
        row.done_by = _text(item.get('done_by'), LIMITS['done_by'])
        row.deleted = bool(item.get('deleted'))
        source = str(item.get('source') or SOURCE_SHOP).strip().lower()
        row.source = source if source in SOURCES else SOURCE_SHOP
        row.created_by = _text(item.get('created_by'), LIMITS['created_by'])
        row.updated_at = theirs
        db.flush()

    return rejected


def merge_counterparties(db, shop, items, now=None):
    now = now or shop_now()
    rejected = []

    for item in items or []:
        if not isinstance(item, dict):
            continue
        uid = _text(item.get('uid'), COUNTERPARTY_LIMITS['uid'])
        if not uid:
            continue
        name = _text(item.get('name'), COUNTERPARTY_LIMITS['name'])
        if not name:
            rejected.append(uid)
            continue

        theirs = parse_moment(item.get('updated_at')) or now
        row = db.query(Counterparty).filter(
            Counterparty.shop_id == shop.id,
            Counterparty.uid == uid).first()
        if row is not None and not _newer(theirs, row.updated_at):
            continue

        if row is None:
            row = Counterparty(shop_id=shop.id, uid=uid)
            db.add(row)

        row.name = name
        # Не прислал направление — как у задач: у старой строки оставляем
        # своё, новая — шиномонтаж
        if 'direction' in item:
            row.direction = parse_direction(item.get('direction'))
        else:
            row.direction = row.direction or TIRE
        for key in ('kind', 'contact', 'phone', 'email', 'address', 'inn',
                    'note'):
            setattr(row, key, _text(item.get(key), COUNTERPARTY_LIMITS[key]))
        row.deleted = bool(item.get('deleted'))
        row.updated_at = theirs
        db.flush()

    return rejected


def changed_since(db, shop, since, today=None):
    """
    Что отдать цеху.

    Есть since — всё, что поменялось после него, включая удалённое:
    удаление тоже правка, и цех должен о ней узнать. since нет — первый
    обмен: живые задачи за последние два месяца и всё, что впереди.
    Удалённые цеху, у которого их никогда не было, ни к чему.
    """
    tasks = db.query(Task).filter(Task.shop_id == shop.id)
    people = db.query(Counterparty).filter(Counterparty.shop_id == shop.id)

    if since is None:
        today = today or shop_now().date()
        tasks = tasks.filter(
            Task.deleted.is_(False),
            Task.due_date >= today - timedelta(days=FIRST_SYNC_DAYS))
        people = people.filter(Counterparty.deleted.is_(False))
    else:
        edge = since - SINCE_OVERLAP
        tasks = tasks.filter(Task.updated_at > edge)
        people = people.filter(Counterparty.updated_at > edge)

    return (tasks.order_by(Task.updated_at, Task.id).all(),
            people.order_by(Counterparty.updated_at, Counterparty.id).all())


def exchange(db, shop, payload, now=None):
    """
    POST /sync/tasks целиком.

    «Сейчас» берём до того, как читать базу: правка, записанная после
    этого мгновения, уйдёт цеху следующим обменом, а не потеряется.
    """
    now = now or shop_now()
    payload = payload or {}

    raw_since = payload.get('since')
    since = parse_moment(raw_since) if raw_since else None

    rejected = merge_tasks(db, shop, payload.get('tasks'), now=now)
    rejected += merge_counterparties(db, shop, payload.get('counterparties'),
                                     now=now)
    db.commit()

    tasks, people = changed_since(db, shop, since, today=now.date())
    return {
        'now': _iso(now),
        'tasks': [to_dict(row) for row in tasks],
        'counterparties': [counterparty_dict(row) for row in people],
        # Чего не приняли — чтобы в цеху было видно, а не терялось молча
        'rejected': rejected,
    }


# ----------------------------------------------------------------------
# Дашборд
# ----------------------------------------------------------------------

def for_range(db, shop_ids, day_from, day_to, today=None, direction=TIRE):
    """
    Задачи на дни календаря — одного слоя: шиномонтажа или мойки.

    Если в показанные дни попадает сегодня, сверху ещё и неотмеченные
    прошлые: задача не исчезает оттого, что её день прошёл, — она висит
    красной, пока её не отметят (docs/calendar.md).
    """
    today = today or shop_now().date()
    base = db.query(Task).filter(Task.shop_id.in_(shop_ids),
                                 Task.direction == direction,
                                 Task.deleted.is_(False))

    rows = base.filter(Task.due_date >= day_from,
                       Task.due_date <= day_to).all()

    overdue = []
    if day_from <= today <= day_to:
        overdue = base.filter(Task.due_date < today,
                              Task.done_at.is_(None)).all()

    def order(row):
        return (row.due_date, row.due_time or '99:99', row.id)

    return sorted(overdue, key=order), sorted(rows, key=order)


def create(db, shop, data, author=None, now=None):
    now = now or shop_now()
    fields = clean_fields(data)

    row = Task(shop_id=shop.id, uid=str(uuid.uuid4()),
               source=SOURCE_DASHBOARD, created_by=_text(author, 100),
               created_at=now, updated_at=now, deleted=False, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def find(db, shop_ids, uid):
    return db.query(Task).filter(Task.shop_id.in_(shop_ids),
                                 Task.uid == uid).first()


def patch(db, row, data, author=None, now=None):
    """
    Поправить задачу из дашборда.

    Время правки двигаем всегда: по нему цех поймёт, что задача
    изменилась, и заберёт её при ближайшем обмене.

    Направление правкой не меняется: раздел проверяем в слое самой
    задачи, а присланное direction не трогаем.
    """
    now = now or shop_now()
    fields = clean_fields(data, partial=True, direction=row.direction or TIRE)
    for key, value in fields.items():
        setattr(row, key, value)

    if 'done' in data:
        if data.get('done'):
            if row.done_at is None:
                row.done_at = now
                row.done_by = _text(author, 100)
        else:
            row.done_at = None
            row.done_by = None

    if 'deleted' in data:
        row.deleted = bool(data.get('deleted'))

    _stamp(row, now)
    db.commit()
    db.refresh(row)
    return row


def counterparties(db, shop_ids, direction=None):
    """
    Живые контрагенты точек. direction — только этого слоя; не задано —
    все: названия нужны и задачам, у которых контрагент из другого слоя.
    """
    query = db.query(Counterparty).filter(
        Counterparty.shop_id.in_(shop_ids),
        Counterparty.deleted.is_(False))
    if direction is not None:
        query = query.filter(Counterparty.direction == direction)
    return query.order_by(Counterparty.name).all()


# ----------------------------------------------------------------------
# Задачи из кабинета клиента
# ----------------------------------------------------------------------

def set_number(row):
    """
    Номер комплекта, под которым его знают в цеху.

    Номер строки на сервере кладовщику ничего не скажет: на полке
    комплект лежит под номером из программы цеха.
    """
    return row.local_id or row.id


def set_title(row):
    parts = [row.storage_type or 'Комплект']
    for value in (row.diameter, row.brand):
        if value:
            parts.append(value)
    if row.wheel_type:
        parts.append(row.wheel_type.lower())
    return ' · '.join(parts)


def _numbers(sets):
    return ', '.join(f'№{set_number(row)}' for row in sets)


def _upsert(db, shop_id, uid, fields, now):
    """
    Поставить или обновить задачу сервера.

    Ту же самую задачу повторный запрос не двоит. Отметку «сделано»
    снимаем, только если поменялось время: человек нажал «заказать»
    второй раз — это та же заявка, и привезённый комплект второй раз
    не повезут.
    """
    row = db.query(Task).filter(Task.shop_id == shop_id,
                                Task.uid == uid).first()
    if row is None:
        row = Task(shop_id=shop_id, uid=uid, source=SOURCE_CABINET,
                   created_by='Кабинет клиента', created_at=now)
        db.add(row)
    elif (row.deleted or row.due_date != fields['due_date']
          or row.due_time != fields['due_time']):
        row.done_at = None
        row.done_by = None

    changed = row.id is None or row.deleted or any(
        getattr(row, key) != value for key, value in fields.items())
    if not changed:
        return row

    for key, value in fields.items():
        setattr(row, key, value)
    row.deleted = False
    _stamp(row, now)
    return row


def _drop(db, shop_id, uid, now=None):
    row = db.query(Task).filter(Task.shop_id == shop_id,
                                Task.uid == uid).first()
    if row is None or row.deleted:
        return None
    row.deleted = True
    _stamp(row, now or shop_now())
    return row


def appointment_uid(appointment_id):
    return f'cab-appt-{appointment_id}'


def request_uid(set_id):
    return f'cab-req-{set_id}'


def for_appointment(db, appointment, stored, client=None, now=None):
    """
    Клиент записался и попросил комплекты со склада — задача кладовщику
    привезти их к времени записи.
    """
    if not stored or appointment.shop_id is None:
        return None
    now = now or shop_now()
    at = appointment.scheduled_at
    lines = '\n'.join(f'№{set_number(row)} — {set_title(row)}'
                      for row in stored)

    return _upsert(db, appointment.shop_id, appointment_uid(appointment.id), {
        'category': STORAGE,
        'due_date': at.date(),
        'due_time': f'{at:%H:%M}',
        'title': f'Привезти со склада {_numbers(stored)}'[:200],
        'note': (f'К записи на {at:%d.%m} в {at:%H:%M}. '
                 f'Клиент заказал из кабинета.\n{lines}'),
        'license_plate': appointment.license_plate,
        'client_name': (client.name if client else None) or appointment.client_name,
        'client_phone': (client.phone if client else None) or appointment.client_phone,
        'storage_ref': ', '.join(str(set_number(row)) for row in stored)[:100],
    }, now)


def follow_appointment(db, appointment, now=None):
    """
    Запись отменили или перенесли — задача по ней тоже.

    Отменили — задача удаляется: везти комплект не к кому. Перенесли —
    едет следом: комплект нужен к новому времени, а не к старому.
    """
    if appointment.shop_id is None:
        return None
    now = now or shop_now()
    uid = appointment_uid(appointment.id)

    if appointment.status == 'cancelled':
        return _drop(db, appointment.shop_id, uid, now)

    row = db.query(Task).filter(Task.shop_id == appointment.shop_id,
                                Task.uid == uid,
                                Task.deleted.is_(False)).first()
    if row is None or appointment.status != 'scheduled':
        return row

    at = appointment.scheduled_at
    if row.due_date != at.date() or row.due_time != f'{at:%H:%M}':
        row.due_date = at.date()
        row.due_time = f'{at:%H:%M}'
        row.done_at = None
        row.done_by = None
        _stamp(row, now)
    return row


def for_storage_request(db, stored_set, now=None):
    """Клиент попросил привезти комплект к дате — задача кладовщику."""
    if stored_set.shop_id is None or stored_set.requested_for is None:
        return None
    now = now or shop_now()
    at = stored_set.requested_for
    client = stored_set.client
    # Полночь — значит, к дате без времени
    clock = None if at.time() == time.min else f'{at:%H:%M}'

    return _upsert(db, stored_set.shop_id, request_uid(stored_set.id), {
        'category': STORAGE,
        'due_date': at.date(),
        'due_time': clock,
        'title': f'Привезти со склада №{set_number(stored_set)}',
        'note': (f'№{set_number(stored_set)} — {set_title(stored_set)}\n'
                 f'Клиент заказал из кабинета.'),
        'license_plate': stored_set.license_plate,
        'client_name': client.name if client else None,
        'client_phone': client.phone if client else None,
        'storage_ref': str(set_number(stored_set)),
    }, now)


def drop_storage_request(db, stored_set, now=None):
    if stored_set.shop_id is None:
        return None
    return _drop(db, stored_set.shop_id, request_uid(stored_set.id), now)


# ----------------------------------------------------------------------
# Сводка владельцу
# ----------------------------------------------------------------------
#
# Утром — что на сегодня, вечером — что осталось не отмечено. Окон
# в программе нет намеренно (docs/calendar.md): напоминание приходит
# туда, где владелец и так смотрит, — в Telegram.

MORNING = 'morning'
EVENING = 'evening'
MAX_LINES = 30


def _minutes(value, fallback):
    try:
        hours, minutes = [int(part) for part in str(value).split(':')[:2]]
        if 0 <= hours <= 23 and 0 <= minutes <= 59:
            return hours * 60 + minutes
    except (ValueError, TypeError, AttributeError):
        pass
    return fallback


def _undone(db, shop_id, today):
    base = db.query(Task).filter(Task.shop_id == shop_id,
                                 Task.deleted.is_(False),
                                 Task.done_at.is_(None))
    order = (Task.due_date, Task.due_time, Task.id)
    for_today = base.filter(Task.due_date == today).order_by(*order).all()
    overdue = base.filter(Task.due_date < today).order_by(*order).all()

    def key(row):
        return (row.due_date, row.due_time or '99:99', row.id)

    return sorted(for_today, key=key), sorted(overdue, key=key)


def _line(task, with_date=False):
    parts = []
    if with_date:
        parts.append(f'{task.due_date:%d.%m}')
    parts.append(task.due_time or '—')
    parts.append(CATEGORY_TITLES.get(task.category, task.category))
    parts.append(task.title)
    if task.license_plate:
        parts.append(task.license_plate)
    line = ' · '.join(parts)
    # Сводка одна на точку, а «Рабочая» есть у обоих слоёв: без пометки
    # владелец не поймёт, чья это задача — мойки или шиномонтажа
    if task.direction == WASH:
        line = 'Мойка: ' + line
    return html.escape(line, quote=False)


def _lines(rows, with_date=False):
    shown = [_line(row, with_date) for row in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        shown.append(f'и ещё {len(rows) - MAX_LINES}')
    return shown


def _plural(count, one, few, many):
    n = abs(count) % 100
    n1 = n % 10
    if 10 < n < 20:
        return many
    if 1 < n1 < 5:
        return few
    if n1 == 1:
        return one
    return many


def morning_text(for_today, overdue):
    count = len(for_today)
    text = [f'<b>На сегодня: {count} '
            f'{_plural(count, "задача", "задачи", "задач")}</b>']
    text += _lines(for_today)
    if overdue:
        text.append('')
        text.append(f'Просрочено: {len(overdue)}')
    return '\n'.join(text)


def evening_text(for_today, overdue):
    rows = overdue + for_today
    text = [f'<b>Не отмечено: {len(rows)}</b>']
    text += _lines(rows, with_date=True)
    return '\n'.join(text)


def digest_for_shop(db, shop, now=None):
    """
    Разослать сводку одной точки, если пора. Возвращает, что ушло.

    Отметку «сегодня уже отправили» держим в настройках точки: таймер
    зовёт каждые пять минут, и без неё владелец получал бы сводку
    двенадцать раз в час. Отметку ставим и тогда, когда сказать нечего
    — иначе каждый следующий запуск снова проверял бы то же самое.
    """
    from app.services import notify, shop_settings

    now = now or shop_now()
    today = now.date()
    sent = []

    if not shop_settings.is_on(shop_settings.get(db, 'task_digest_enabled',
                                                 shop=shop)):
        return sent
    if not notify.is_configured(db, shop, notify.KIND_DIGEST):
        return sent

    clock = now.hour * 60 + now.minute
    morning = _minutes(shop_settings.get(db, 'task_digest_morning', shop=shop),
                       9 * 60)
    evening = _minutes(shop_settings.get(db, 'task_digest_evening', shop=shop),
                       20 * 60)
    stamp = today.isoformat()

    def due(name, start, until=None):
        if clock < start or (until is not None and clock >= until):
            return False
        mark = shop_settings.get(db, f'task_digest_sent_{name}', '', shop=shop)
        return mark != stamp

    def mark(name):
        shop_settings.set_value(db, f'task_digest_sent_{name}', stamp,
                                shop=shop)

    # Утро после вечера не шлём: сервер мог простоять весь день, и
    # «на сегодня» в девять вечера только запутает
    if due(MORNING, morning, evening if evening > morning else None):
        for_today, overdue = _undone(db, shop.id, today)
        mark(MORNING)
        # Нечего сказать — не пишем: пустая сводка каждое утро быстро
        # приучит её не читать
        if for_today or overdue:
            notify.send(db, morning_text(for_today, overdue), shop=shop,
                        kind=notify.KIND_DIGEST)
            sent.append(MORNING)

    if due(EVENING, evening):
        for_today, overdue = _undone(db, shop.id, today)
        mark(EVENING)
        if for_today or overdue:
            notify.send(db, evening_text(for_today, overdue), shop=shop,
                        kind=notify.KIND_DIGEST)
            sent.append(EVENING)

    return sent


def send_digests(db, now=None):
    """Пройти по работающим точкам и разослать созревшие сводки."""
    from app.models import Shop

    result = {MORNING: 0, EVENING: 0}
    for shop in db.query(Shop).filter(Shop.is_active.is_(True)).all():
        try:
            for name in digest_for_shop(db, shop, now=now):
                result[name] += 1
        except Exception as e:
            # Одна сломанная точка не должна оставить без сводки остальные
            log.warning('Точка №%s: сводка задач не отправлена: %s',
                        shop.id, e)
            db.rollback()
    return result
