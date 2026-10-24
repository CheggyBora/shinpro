"""
Календарь задач (docs/calendar.md).

Задачи ставят приёмщик, владелец из дашборда, сама программа (склад,
покраска) и кабинет клиента. Здесь — всё, что с ними делают: завести,
поправить, перенести, отметить, показать на день и неделю, ленту на
сегодня и подсказку в наряде, обмен с сервером.

Напоминания — без окон: следить за ними некому, а нажимать «ОК» на
каждое в сезон никто не будет. Поэтому неотмеченная задача прошлых дней
не прячется, а остаётся в ленте красной, пока её не отметят.
"""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from models.calendar import (CalendarTask, Counterparty, CATEGORIES, CATEGORY_TITLES,
                             WORK, STORAGE, PAINT, SOURCE_SHOP, SOURCE_AUTO, new_uid)
from utils import get_moscow_time, as_naive, normalize_plate

# За сколько минут до времени задача в ленте желтеет
SOON_MINUTES = 30

# Главное окно ставит сюда «выйти на связь поскорее»: задача из цеха
# должна появиться в дашборде сразу, а не через 20 секунд. Вызывается
# только из окна — из потока обмена не трогаем
ON_CHANGE = None

TASK_FIELDS = ('category', 'due_date', 'due_time', 'title', 'note', 'license_plate',
               'client_name', 'client_phone', 'counterparty_uid', 'storage_ref',
               'amount', 'done_at', 'done_by', 'deleted', 'source', 'created_by')
COUNTERPARTY_FIELDS = ('name', 'kind', 'contact', 'phone', 'email', 'address',
                       'inn', 'note', 'deleted')


class TaskError(ValueError):
    """Понятная человеку причина, почему не вышло."""


def clean_time(value):
    """«9:5», «0930», «09.30» → «09:30»; пусто — None; непонятное — ошибка."""
    text = str(value or '').strip().replace('.', ':').replace('-', ':')
    if not text:
        return None
    if ':' not in text and text.isdigit() and len(text) in (3, 4):
        text = f'{text[:-2]}:{text[-2:]}'
    try:
        hours, minutes = (int(part) for part in text.split(':')[:2])
    except ValueError:
        raise TaskError(f'«{value}» — не время. Нужно ЧЧ:ММ, например 10:30')
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        raise TaskError(f'«{value}» — не время. Нужно ЧЧ:ММ, например 10:30')
    return f'{hours:02d}:{minutes:02d}'


def parse_day(value):
    """«27.10.2026», «27.10», «2026-10-27» или date → date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    today = as_naive(get_moscow_time()).date()
    try:
        if '-' in text:
            return date.fromisoformat(text[:10])
        parts = [int(p) for p in text.split('.') if p]
        if len(parts) == 2:
            return date(today.year, parts[1], parts[0])
        if len(parts) == 3:
            year = parts[2] + 2000 if parts[2] < 100 else parts[2]
            return date(year, parts[1], parts[0])
    except ValueError:
        pass
    raise TaskError(f'«{value}» — не дата. Нужно ДД.ММ.ГГГГ, например 27.10.2026')


def _now():
    # Без долей секунды: на сервер время уходит с точностью до секунды,
    # и сравнивать «чья правка новее» надо одинаково с обеих сторон
    return as_naive(get_moscow_time()).replace(microsecond=0)


class CalendarService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Задачи
    # ------------------------------------------------------------------

    def get(self, task_id):
        task = self.db.query(CalendarTask).filter(CalendarTask.id == task_id).first()
        if task is None or task.deleted:
            raise TaskError('Задача не найдена')
        return task

    def by_uid(self, uid):
        return self.db.query(CalendarTask).filter(CalendarTask.uid == uid).first()

    def create(self, title, due_date, category=WORK, due_time=None, note=None,
               license_plate=None, client_name=None, client_phone=None,
               counterparty_uid=None, storage_ref=None, amount=None,
               source=SOURCE_SHOP, created_by=None, uid=None):
        title = (title or '').strip()
        if not title:
            raise TaskError('Напишите, что за задача')
        if category not in CATEGORIES:
            raise TaskError('Неизвестный раздел задачи')
        task = CalendarTask(
            uid=uid or new_uid(), category=category, due_date=parse_day(due_date),
            due_time=clean_time(due_time), title=title[:200], note=(note or '').strip() or None,
            license_plate=normalize_plate(license_plate) if license_plate else None,
            client_name=client_name or None, client_phone=client_phone or None,
            counterparty_uid=counterparty_uid or None, storage_ref=storage_ref,
            amount=amount, source=source, created_by=created_by,
            created_at=_now(), updated_at=_now())
        self.db.add(task)
        self.db.commit()
        self._changed()
        return task

    def update(self, task, **fields):
        if 'due_date' in fields:
            fields['due_date'] = parse_day(fields['due_date'])
        if 'due_time' in fields:
            fields['due_time'] = clean_time(fields['due_time'])
        if 'title' in fields:
            fields['title'] = (fields['title'] or '').strip()[:200]
            if not fields['title']:
                raise TaskError('Напишите, что за задача')
        if 'category' in fields and fields['category'] not in CATEGORIES:
            raise TaskError('Неизвестный раздел задачи')
        if 'license_plate' in fields:
            fields['license_plate'] = normalize_plate(fields['license_plate']) or None
        for key, value in fields.items():
            if key in TASK_FIELDS:
                setattr(task, key, value)
        task.updated_at = _later(task.updated_at)
        self.db.commit()
        self._changed()
        return task

    def move(self, task, days=0, hours=0, to_date=None, to_time=None):
        """
        Перенести. «+1 час» у задачи без времени ставит время от текущего
        часа: перенести «на час» что-то без времени — значит «через час».
        """
        if to_date is not None or to_time is not None:
            return self.update(task, due_date=to_date or task.due_date,
                               due_time=to_time if to_time is not None else task.due_time)
        when_day = task.due_date
        when_time = task.due_time
        if hours:
            if when_time:
                h, m = (int(p) for p in when_time.split(':'))
                moment = datetime.combine(when_day, datetime.min.time()) + timedelta(hours=h, minutes=m)
            else:
                moment = _now().replace(second=0, microsecond=0)
                # Просроченная без времени: «через час» — от сейчас, сегодня
            moment += timedelta(hours=hours)
            when_day, when_time = moment.date(), moment.strftime('%H:%M')
        if days:
            # Переносим от сегодняшнего дня, если задача уже в прошлом:
            # «завтра» у вчерашней — это завтра, а не сегодня
            base = max(when_day, _now().date()) if days > 0 else when_day
            when_day = base + timedelta(days=days)
        return self.update(task, due_date=when_day, due_time=when_time)

    def set_done(self, task, done=True, by=None):
        if done:
            return self.update(task, done_at=_now(), done_by=by)
        return self.update(task, done_at=None, done_by=None)

    def delete(self, task):
        return self.update(task, deleted=True)

    def _changed(self):
        if ON_CHANGE is not None:
            try:
                ON_CHANGE()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Что показать
    # ------------------------------------------------------------------

    def _alive(self, categories=None):
        query = self.db.query(CalendarTask).filter(CalendarTask.deleted.is_(False))
        if categories:
            query = query.filter(CalendarTask.category.in_(list(categories)))
        return query

    @staticmethod
    def _order(task):
        # Сначала со временем — по времени, без времени — в конце дня
        return (task.due_date, task.due_time is None, task.due_time or '', task.id)

    def day(self, day, categories=None):
        day = parse_day(day)
        rows = self._alive(categories).filter(CalendarTask.due_date == day).all()
        return sorted(rows, key=self._order)

    def overdue(self, today=None, categories=None):
        """Не отмеченные задачи прошлых дней — их нельзя потерять."""
        today = today or _now().date()
        rows = self._alive(categories).filter(
            CalendarTask.due_date < today, CalendarTask.done_at.is_(None)).all()
        return sorted(rows, key=self._order)

    def week(self, start, categories=None):
        """{день: [задачи]} на семь дней с понедельника той недели."""
        start = parse_day(start)
        start = start - timedelta(days=start.weekday())
        end = start + timedelta(days=7)
        rows = self._alive(categories).filter(
            CalendarTask.due_date >= start, CalendarTask.due_date < end).all()
        days = {start + timedelta(days=i): [] for i in range(7)}
        for task in sorted(rows, key=self._order):
            days[task.due_date].append(task)
        return days

    def state(self, task, now=None):
        """overdue / soon / later / done — цвет в ленте."""
        now = now or _now()
        if task.done_at:
            return 'done'
        if task.due_date < now.date():
            return 'overdue'
        if task.due_date > now.date():
            return 'later'
        if not task.due_time:
            return 'later'
        h, m = (int(p) for p in task.due_time.split(':'))
        at = datetime.combine(task.due_date, datetime.min.time()) + timedelta(hours=h, minutes=m)
        if at <= now:
            return 'overdue'
        if at - now <= timedelta(minutes=SOON_MINUTES):
            return 'soon'
        return 'later'

    def strip(self, now=None):
        """Лента над нарядами: просроченные и сегодняшние неотмеченные."""
        now = now or _now()
        today = [t for t in self.day(now.date()) if not t.done_at]
        return self.overdue(now.date()) + today

    def for_plate(self, plate, now=None, days_ahead=7):
        """Неотмеченные задачи по машине — подсказка в её наряде."""
        plate = normalize_plate(plate or '')
        if not plate:
            return []
        now = now or _now()
        rows = self._alive().filter(
            CalendarTask.license_plate == plate, CalendarTask.done_at.is_(None),
            CalendarTask.due_date <= now.date() + timedelta(days=days_ahead)).all()
        return sorted(rows, key=self._order)

    def overdue_count(self, now=None):
        now = now or _now()
        return sum(1 for t in self.strip(now) if self.state(t, now) == 'overdue')

    @staticmethod
    def title_of(category):
        return CATEGORY_TITLES.get(category, category)

    # ------------------------------------------------------------------
    # Контрагенты
    # ------------------------------------------------------------------

    def counterparties(self):
        return self.db.query(Counterparty).filter(
            Counterparty.deleted.is_(False)).order_by(Counterparty.name).all()

    def counterparty(self, uid):
        if not uid:
            return None
        return self.db.query(Counterparty).filter(Counterparty.uid == uid).first()

    def save_counterparty(self, counterparty=None, **fields):
        name = (fields.get('name') or '').strip()
        if not name:
            raise TaskError('Напишите название контрагента')
        if counterparty is None:
            counterparty = Counterparty(uid=new_uid(), name=name)
            self.db.add(counterparty)
        for key in COUNTERPARTY_FIELDS:
            if key in fields:
                value = fields[key]
                setattr(counterparty, key, value.strip() if isinstance(value, str) else value)
        counterparty.updated_at = _later(counterparty.updated_at)
        self.db.commit()
        self._changed()
        return counterparty

    def delete_counterparty(self, counterparty):
        counterparty.deleted = True
        counterparty.updated_at = _later(counterparty.updated_at)
        self.db.commit()
        self._changed()

    def tasks_of_counterparty(self, uid, limit=30):
        rows = self._alive().filter(CalendarTask.counterparty_uid == uid).order_by(
            CalendarTask.due_date.desc()).limit(limit).all()
        return rows

    # ------------------------------------------------------------------
    # Задачи, которые ставит сама программа
    # ------------------------------------------------------------------

    def storage_to_warehouse(self, storage, day, created_by=None):
        """Приняли на хранение — отвезти комплект на склад."""
        title = f'Отвезти на склад №{storage.id}'
        task = self.create(
            title=title, due_date=day, category=STORAGE,
            note=storage_title(storage), license_plate=storage.car_number,
            client_name=storage.client_name, client_phone=storage.client_phone,
            storage_ref=str(storage.id), source=SOURCE_AUTO, created_by=created_by)
        return task

    def storage_from_warehouse(self, storage, day, time=None, why=None, created_by=None):
        """Заказали комплект со склада к дате."""
        note = storage_title(storage) + (f'\n{why}' if why else '')
        return self.create(
            title=f'Привезти со склада №{storage.id}', due_date=day, due_time=time,
            category=STORAGE, note=note, license_plate=storage.car_number,
            client_name=storage.client_name, client_phone=storage.client_phone,
            storage_ref=str(storage.id), source=SOURCE_AUTO, created_by=created_by)

    def paint_job(self, plate, day, diameter, wheels, total, details=None,
                  client_name=None, client_phone=None, created_by=None):
        """Оформили покраску дисков — забрать готовые к дате."""
        title = f'Покраска {normalize_plate(plate)} · {diameter} × {wheels}'
        return self.create(
            title=title, due_date=day, category=PAINT, note=details,
            license_plate=plate, client_name=client_name, client_phone=client_phone,
            amount=total, source=SOURCE_AUTO, created_by=created_by)

    # ------------------------------------------------------------------
    # Обмен с сервером
    # ------------------------------------------------------------------

    @staticmethod
    def task_payload(task):
        return {
            'uid': task.uid, 'category': task.category,
            'due_date': task.due_date.isoformat(), 'due_time': task.due_time,
            'title': task.title, 'note': task.note,
            'license_plate': task.license_plate, 'client_name': task.client_name,
            'client_phone': task.client_phone, 'counterparty_uid': task.counterparty_uid,
            'storage_ref': task.storage_ref, 'amount': task.amount,
            'done_at': _iso(task.done_at), 'done_by': task.done_by,
            'deleted': bool(task.deleted), 'source': task.source,
            'created_by': task.created_by, 'created_at': _iso(task.created_at),
            'updated_at': _iso(task.updated_at),
        }

    @staticmethod
    def counterparty_payload(row):
        payload = {key: getattr(row, key) for key in COUNTERPARTY_FIELDS}
        payload.update(uid=row.uid, deleted=bool(row.deleted), updated_at=_iso(row.updated_at))
        return payload

    def unsent(self):
        tasks = [t for t in self.db.query(CalendarTask).all()
                 if t.synced_at is None or as_naive(t.updated_at) > as_naive(t.synced_at)]
        parties = [c for c in self.db.query(Counterparty).all()
                   if c.synced_at is None or as_naive(c.updated_at) > as_naive(c.synced_at)]
        return tasks, parties

    def apply_server(self, answer, sent_tasks=(), sent_parties=()):
        """
        Принять задачи и контрагентов с сервера. Новее наша правка —
        оставляем свою: она уйдёт со следующим обменом. Возвращает,
        сколько строк поменялось.
        """
        moment = _now()
        # Отданное помечаем тем временем правки, которое отдали: если
        # пока шёл обмен, строку поправили ещё раз, она уйдёт снова
        for row in list(sent_tasks) + list(sent_parties):
            row.synced_at = row.updated_at
        changed = 0
        for item in answer.get('tasks') or []:
            task = self.by_uid(item.get('uid'))
            theirs = _parse(item.get('updated_at'))
            if task is not None and theirs is not None and task.updated_at is not None \
                    and as_naive(task.updated_at) > theirs:
                continue
            if task is None:
                task = CalendarTask(uid=item['uid'])
                self.db.add(task)
            try:
                task.category = item.get('category') if item.get('category') in CATEGORIES else WORK
                task.due_date = parse_day(item.get('due_date'))
                task.due_time = clean_time(item.get('due_time'))
            except TaskError:
                continue
            for key in ('title', 'note', 'license_plate', 'client_name', 'client_phone',
                        'counterparty_uid', 'storage_ref', 'amount', 'done_by',
                        'source', 'created_by'):
                setattr(task, key, item.get(key))
            task.title = task.title or ''
            task.done_at = _parse(item.get('done_at'))
            task.deleted = bool(item.get('deleted'))
            task.created_at = _parse(item.get('created_at')) or task.created_at or moment
            task.updated_at = theirs or moment
            task.synced_at = moment
            changed += 1
        for item in answer.get('counterparties') or []:
            row = self.counterparty(item.get('uid'))
            theirs = _parse(item.get('updated_at'))
            if row is not None and theirs is not None and row.updated_at is not None \
                    and as_naive(row.updated_at) >= theirs:
                row.synced_at = moment
                continue
            if row is None:
                if not item.get('name'):
                    continue
                row = Counterparty(uid=item['uid'], name=item['name'])
                self.db.add(row)
            for key in COUNTERPARTY_FIELDS:
                if key in item:
                    setattr(row, key, item[key])
            row.deleted = bool(item.get('deleted'))
            row.updated_at = theirs or moment
            row.synced_at = moment
            changed += 1
        self.db.commit()
        return changed


def _later(previous):
    """
    Время правки — строго позже прошлой. Обмен решает, чья версия новее,
    по секундам: поставили задачу и тут же отметили — без этого вторая
    правка выглядела бы не новее первой и не дошла бы до сервера.
    """
    now = _now()
    if previous is not None and now <= as_naive(previous):
        return as_naive(previous).replace(microsecond=0) + timedelta(seconds=1)
    return now


def storage_title(storage):
    parts = [storage.storage_type or 'Комплект']
    for value in (storage.diameter, storage.brand):
        if value:
            parts.append(value)
    if storage.wheel_type:
        parts.append(storage.wheel_type.lower())
    return ' · '.join(parts)


def _iso(value):
    return as_naive(value).replace(microsecond=0).isoformat() if value else None


def _parse(value):
    if not value:
        return None
    try:
        return as_naive(datetime.fromisoformat(str(value)))
    except ValueError:
        return None
