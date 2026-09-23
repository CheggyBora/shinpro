"""
Предварительная запись клиентов.

Записать можно по телефонному звонку, лично или из приложения клиента.
Сервис следит за загрузкой постов: если на выбранное время уже записано
столько машин, сколько есть работающих постов, приёмщик об этом узнает
до того, как пообещает клиенту время.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_

from models import Appointment, Client, Car, BookingPosts
from utils import normalize_plate, normalize_phone, as_naive, get_moscow_time

# Записи, которые занимают пост: клиент либо едет, либо уже приехал.
# Приехавшего тоже считаем — машина стоит на посту, и записать на это
# время ещё одну было бы обманом. Отменённые и не приехавшие пост
# освобождают и из ленты дня пропадают.
ACTIVE_STATUSES = (Appointment.STATUS_SCHEDULED, Appointment.STATUS_ARRIVED)

# Постов под запись: больше трёх на шиномонтаже не бывает, а меньше
# одного означало бы «не записывать вообще»
MIN_POSTS = 1
MAX_POSTS = 3

# День, на который посты не настраивали, считается однопостовым:
# пообещать клиенту время и не успеть хуже, чем открыть ещё один
# пост в середине дня
DEFAULT_POSTS = 1


class AppointmentService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Создание и изменение
    # ------------------------------------------------------------------

    def create(self, scheduled_at, duration_minutes=30, client_name=None,
               client_phone=None, license_plate=None, services_note=None,
               comment=None, source=Appointment.SOURCE_PHONE, client_id=None,
               wheels_assembled=None, create_client=True):
        """
        Записать клиента.

        Клиент и машина ищутся по госномеру и телефону. Если их в базе нет,
        они заводятся прямо здесь: приёмщик не должен идти в другой раздел,
        пока человек ждёт на телефоне. Отдельная карточка не создаётся,
        только когда create_client=False — так приходят записи из
        приложения, где данные ещё не проверены человеком.

        wheels_assembled — колёса в сборе (True) или только шины (False).
        Записывается в карточку машины, если там про это ещё не знают:
        от этого втрое отличается время работы.
        """
        if scheduled_at is None:
            raise ValueError("Не указано время записи")

        if duration_minutes is None or duration_minutes <= 0:
            raise ValueError("Продолжительность должна быть больше нуля")

        plate = normalize_plate(license_plate)
        phone = normalize_phone(client_phone)
        name = (client_name or '').strip() or None

        # Привязываем к существующим клиенту и машине, если они известны
        client = None
        if client_id:
            client = self.db.query(Client).filter(Client.id == client_id).first()
        elif phone:
            client = self.db.query(Client).filter(Client.phone == phone).first()

        car = None
        if plate:
            car = self.db.query(Car).filter(Car.license_plate == plate).first()
            if car and client is None and car.client_id:
                client = car.client

        if create_client:
            client, car = self._ensure_client_and_car(
                client, car, plate, name, phone, wheels_assembled)

        appointment = Appointment(
            scheduled_at=as_naive(scheduled_at),
            duration_minutes=int(duration_minutes),
            client_id=client.id if client else None,
            car_id=car.id if car else None,
            client_name=name or (client.name if client else None),
            client_phone=phone or (client.phone if client else None),
            license_plate=plate or None,
            services_note=(services_note or '').strip() or None,
            comment=(comment or '').strip() or None,
            source=source,
            status=Appointment.STATUS_SCHEDULED,
        )
        self.db.add(appointment)
        self.db.commit()
        self.db.refresh(appointment)
        return appointment

    def _ensure_client_and_car(self, client, car, plate, name, phone,
                               wheels_assembled):
        """
        Завести клиента и машину, которых ещё нет, и связать их.

        Клиент заводится, только если есть за что зацепиться — имя или
        телефон. Звонок «запишите Ниссан на завтра» без контактов создаст
        запись, но не пустую карточку клиента в базе.
        """
        if client is None and (name or phone):
            from services.client_service import ClientService
            client, _ = ClientService(self.db).get_or_create(name=name, phone=phone)

        if plate and car is None:
            car = Car(license_plate=plate)
            self.db.add(car)
            self.db.flush()

        if car is not None:
            # Машина без владельца достаётся тому, кто записывается
            if client is not None and car.client_id is None:
                car.client_id = client.id
            # Про колёса пишем в карточку только когда там пусто:
            # запись по телефону не должна переписывать то, что мастер
            # видел своими глазами
            if wheels_assembled is not None and car.wheels_assembled is None:
                car.wheels_assembled = bool(wheels_assembled)

        return client, car

    def update(self, appointment_id, **fields):
        """Изменить поля записи. Передаются только те, что нужно поменять."""
        appointment = self.get(appointment_id)
        if not appointment:
            raise ValueError(f"Запись №{appointment_id} не найдена")

        if 'license_plate' in fields:
            fields['license_plate'] = normalize_plate(fields['license_plate']) or None
        if 'client_phone' in fields:
            fields['client_phone'] = normalize_phone(fields['client_phone']) or None
        if 'scheduled_at' in fields:
            fields['scheduled_at'] = as_naive(fields['scheduled_at'])

        for key, value in fields.items():
            setattr(appointment, key, value)

        self.db.commit()
        return appointment

    def cancel(self, appointment_id, reason=None):
        appointment = self.get(appointment_id)
        if not appointment:
            raise ValueError(f"Запись №{appointment_id} не найдена")

        appointment.status = Appointment.STATUS_CANCELLED
        if reason:
            appointment.comment = ((appointment.comment or '') + f"\nОтменена: {reason}").strip()
        self.db.commit()
        return appointment

    def mark_no_show(self, appointment_id):
        appointment = self.get(appointment_id)
        if appointment:
            appointment.status = Appointment.STATUS_NO_SHOW
            self.db.commit()
        return appointment

    def mark_arrived(self, appointment_id, work_order_id=None):
        """Клиент приехал. Если завели наряд — связываем с записью."""
        appointment = self.get(appointment_id)
        if not appointment:
            raise ValueError(f"Запись №{appointment_id} не найдена")

        appointment.status = Appointment.STATUS_ARRIVED
        if work_order_id:
            appointment.work_order_id = work_order_id
        self.db.commit()
        return appointment

    # ------------------------------------------------------------------
    # Чтение
    # ------------------------------------------------------------------

    def get(self, appointment_id):
        return self.db.query(Appointment).filter(Appointment.id == appointment_id).first()

    def get_for_day(self, day, include_cancelled=True):
        """Все записи на указанную дату, по возрастанию времени."""
        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)

        query = self.db.query(Appointment).filter(
            and_(Appointment.scheduled_at >= start, Appointment.scheduled_at < end)
        )
        if not include_cancelled:
            query = query.filter(Appointment.status.in_(ACTIVE_STATUSES))

        return query.order_by(Appointment.scheduled_at).all()

    def get_upcoming(self, limit=50):
        """Ближайшие ожидаемые записи начиная с текущего момента."""
        return self.db.query(Appointment).filter(
            Appointment.scheduled_at >= get_moscow_time(),
            Appointment.status == Appointment.STATUS_SCHEDULED
        ).order_by(Appointment.scheduled_at).limit(limit).all()

    def search_by_phone(self, phone):
        normalized = normalize_phone(phone)
        if not normalized:
            return []
        return self.db.query(Appointment).filter(
            Appointment.client_phone == normalized
        ).order_by(Appointment.scheduled_at.desc()).all()

    # ------------------------------------------------------------------
    # Загрузка постов
    # ------------------------------------------------------------------

    def duration_for_wheels(self, wheels_assembled):
        """
        Сколько времени закладывать на запись.

        При записи по телефону услуги ещё неизвестны, спрашивать их
        бессмысленно — человек и сам не знает. Но колёса в сборе или
        россыпью известно почти всегда, и это главная разница по времени:
        перекидка готовых колёс против разбортовки каждого.
        """
        from services.settings_service import SettingsService

        settings = SettingsService(self.db)
        if wheels_assembled is True:
            return settings.get_int('booking_minutes_assembled')
        if wheels_assembled is False:
            return settings.get_int('booking_minutes_tires')
        return settings.get_int('booking_minutes_unknown')

    @staticmethod
    def clamp_posts(posts):
        """Привести число постов к допустимому: от одного до трёх."""
        try:
            posts = int(posts)
        except (TypeError, ValueError):
            return DEFAULT_POSTS
        return max(MIN_POSTS, min(MAX_POSTS, posts))

    def get_posts_for_day(self, day):
        """
        Сколько постов открыто под запись на этот день.

        День, который не настраивали, считается однопостовым — так
        приёмщик не пообещает больше, чем сможет сделать.
        """
        day = self._as_date(day)
        row = self.db.query(BookingPosts).filter(BookingPosts.day == day).first()
        return self.clamp_posts(row.posts) if row else DEFAULT_POSTS

    def set_posts_for_day(self, day, posts):
        """Задать число постов на один день."""
        day = self._as_date(day)
        posts = self.clamp_posts(posts)

        row = self.db.query(BookingPosts).filter(BookingPosts.day == day).first()
        if row:
            row.posts = posts
        else:
            self.db.add(BookingPosts(day=day, posts=posts))
        self.db.commit()
        return posts

    def set_posts_for_days(self, start_day, days, posts):
        """
        Задать число постов сразу на несколько дней подряд.

        Нужно, чтобы не тыкать в каждый день по отдельности: «на неделю
        вперёд два поста» — одно действие.
        """
        start_day = self._as_date(start_day)
        posts = self.clamp_posts(posts)
        days = max(1, int(days))

        for offset in range(days):
            self.set_posts_for_day(start_day + timedelta(days=offset), posts)
        return posts

    def get_posts_map(self, start_day, days):
        """Постов по дням для указанного отрезка — для подписей в календаре."""
        start_day = self._as_date(start_day)
        return {start_day + timedelta(days=offset):
                self.get_posts_for_day(start_day + timedelta(days=offset))
                for offset in range(max(1, int(days)))}

    @staticmethod
    def _as_date(value):
        """Принять и дату, и момент времени — вернуть дату."""
        return value.date() if isinstance(value, datetime) else value

    def get_posts_count(self):
        """Постов под запись на сегодня. Оставлено для старых вызовов."""
        return self.get_posts_for_day(get_moscow_time().date())

    def count_overlapping(self, scheduled_at, duration_minutes, exclude_id=None):
        """
        Сколько записей пересекается по времени с предполагаемой.

        Две записи считаются пересекающимися, если их отрезки времени
        накладываются хотя бы частично: обе займут пост одновременно.
        """
        start = as_naive(scheduled_at)
        end = start + timedelta(minutes=int(duration_minutes))

        # Берём записи того же дня — их немного, пересечения считаем в Python
        same_day = self.get_for_day(start.date(), include_cancelled=False)

        overlapping = 0
        for other in same_day:
            if exclude_id and other.id == exclude_id:
                continue
            other_start = as_naive(other.scheduled_at)
            other_end = other_start + timedelta(minutes=other.duration_minutes or 0)
            if other_start < end and start < other_end:
                overlapping += 1
        return overlapping

    def check_capacity(self, scheduled_at, duration_minutes, exclude_id=None):
        """
        Хватает ли свободных постов на это время.

        Возвращает (свободно, занято, всего_постов). Свободно=False означает,
        что все посты в это время уже заняты записями.
        """
        posts = self.get_posts_for_day(as_naive(scheduled_at).date())
        busy = self.count_overlapping(scheduled_at, duration_minutes, exclude_id)
        return busy < posts, busy, posts

    def layout_day(self, day, include_cancelled=False):
        """
        Разложить записи дня по колонкам-постам.

        Возвращает список (запись, номер_колонки). Колонка выбирается
        первая свободная на это время — так карточки не наезжают друг
        на друга, а пересечения сразу видны глазом.

        Записи, которым не хватило колонок (в день добавили постов меньше,
        чем уже записано), получают номер за пределами сетки — вызывающий
        покажет их отдельно, а не потеряет.
        """
        appointments = self.get_for_day(day, include_cancelled=include_cancelled)
        posts = self.get_posts_for_day(day)

        # Когда каждая колонка освободится
        free_at = [None] * posts
        placed = []

        for appointment in appointments:
            start = as_naive(appointment.scheduled_at)
            end = start + timedelta(minutes=appointment.duration_minutes or 0)

            column = None
            for index in range(posts):
                if free_at[index] is None or free_at[index] <= start:
                    column = index
                    free_at[index] = end
                    break

            if column is None:
                # Все посты заняты — запись всё равно должна быть видна
                column = posts
            placed.append((appointment, column))

        return placed

    def suggest_free_time(self, day, duration_minutes, work_start_hour=9,
                          work_end_hour=21, step_minutes=30):
        """
        Предложить ближайшее свободное время в указанный день.

        Нужно, когда приёмщик говорит клиенту по телефону: «на 14:00 всё
        занято, могу записать на 15:30».
        """
        start = datetime(day.year, day.month, day.day, work_start_hour, 0)
        end = datetime(day.year, day.month, day.day, work_end_hour, 0)

        slot = start
        while slot + timedelta(minutes=duration_minutes) <= end:
            free, _, _ = self.check_capacity(slot, duration_minutes)
            if free:
                return slot
            slot += timedelta(minutes=step_minutes)
        return None
