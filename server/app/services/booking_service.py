"""
Онлайн-запись: какие окна показать клиенту и как принять заявку.

Главное правило: сервер не решает за цех. Он только считает по тем
постам и часам, которые цех прислал, и складывает заявку в очередь.
Запись из приложения помечена как неподтверждённая, пока программа
шиномонтажа её не забрала, — клиент видит «подтверждаем», а не
«записаны», и не приезжает на время, о котором цех ещё не знает.
"""
from datetime import datetime, timedelta, date, time

from app.models import Appointment, BookingDay, Car, Client, PENDING, TAKEN
from app.services import shop_settings
from app.utils import normalize_plate

# Состояния, при которых машина занимает пост
BUSY_STATUSES = ('scheduled', 'arrived')

STATUS_TITLES = {
    'scheduled': 'Ожидается',
    'arrived': 'Вы приехали',
    'cancelled': 'Отменена',
    'no_show': 'Не приехали',
}


class BookingError(Exception):
    """Понятная клиенту причина, почему записаться не вышло."""


class BookingService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Расчёт окон
    # ------------------------------------------------------------------

    def duration_for(self, wheels_assembled):
        if wheels_assembled is True:
            return shop_settings.get_int(self.db, 'booking_minutes_assembled')
        if wheels_assembled is False:
            return shop_settings.get_int(self.db, 'booking_minutes_tires')
        return shop_settings.get_int(self.db, 'booking_minutes_unknown')

    def day_settings(self, day):
        """Посты и рабочие часы дня. Чего цех не прислал — то по умолчанию."""
        row = self.db.query(BookingDay).filter(BookingDay.day == day).first()
        if row is None:
            # День, о котором цех не сказал ничего, считаем однопостовым —
            # так же, как это делает сама программа шиномонтажа
            return {'posts': 1, 'opens_at': self._default_opens(),
                    'closes_at': self._default_closes(), 'is_closed': False}
        return {'posts': max(1, row.posts),
                'opens_at': row.opens_at or self._default_opens(),
                'closes_at': row.closes_at or self._default_closes(),
                'is_closed': row.is_closed}

    def _default_opens(self):
        return shop_settings.get(self.db, 'booking_opens_at')

    def _default_closes(self):
        return shop_settings.get(self.db, 'booking_closes_at')

    def _busy_at(self, day):
        """Записи дня, занимающие посты, отрезками времени."""
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)

        rows = self.db.query(Appointment).filter(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < end,
            Appointment.status.in_(BUSY_STATUSES),
        ).all()

        return [(row.scheduled_at,
                 row.scheduled_at + timedelta(minutes=row.duration_minutes or 0))
                for row in rows]

    @staticmethod
    def _minutes_of(value, fallback_minutes):
        """
        «07:00» в минуты от полуночи.

        Отдельно понимаем «24:00»: это конец суток, а не их начало.
        Записывать до полуночи в сезон приходится, и «00:00» здесь
        читалось бы как «закрыто с самого утра».
        """
        try:
            hours, minutes = [int(part) for part in str(value).split(':')]
            if 0 <= hours <= 24 and 0 <= minutes <= 59:
                return hours * 60 + minutes
        except (ValueError, AttributeError, TypeError):
            pass
        return fallback_minutes

    def free_slots(self, day, duration_minutes, now=None):
        """
        Свободные окна дня.

        Окно годится, если работа успевает закончиться до закрытия
        и если на всё её время хватает свободного поста. Проверяем
        именно весь отрезок, а не момент начала: иначе клиента можно
        записать на 20:30 при закрытии в 21:00 на полуторачасовую работу.
        """
        now = now or datetime.now()
        settings = self.day_settings(day)
        if settings['is_closed']:
            return []

        midnight = datetime.combine(day, time.min)
        opens = midnight + timedelta(
            minutes=self._minutes_of(settings['opens_at'], 7 * 60))
        closes = midnight + timedelta(
            minutes=self._minutes_of(settings['closes_at'], 24 * 60))
        step = timedelta(minutes=shop_settings.get_int(self.db, 'booking_slot_step'))
        busy = self._busy_at(day)
        posts = settings['posts']

        slots = []
        moment = opens
        while moment + timedelta(minutes=duration_minutes) <= closes:
            if moment <= now:
                # Записаться на прошедшее время нельзя, даже сегодня
                moment += step
                continue

            finish = moment + timedelta(minutes=duration_minutes)
            overlapping = sum(1 for start, end in busy
                              if start < finish and moment < end)
            if overlapping < posts:
                slots.append({'at': moment, 'free_posts': posts - overlapping})
            moment += step

        return slots

    def days_ahead(self):
        return max(1, shop_settings.get_int(self.db, 'booking_days_ahead'))

    def calendar(self, wheels_assembled=None, now=None):
        """Ближайшие дни со свободными окнами — то, что рисует приложение."""
        now = now or datetime.now()
        duration = self.duration_for(wheels_assembled)

        days = []
        for offset in range(self.days_ahead()):
            day = (now + timedelta(days=offset)).date()
            settings = self.day_settings(day)
            days.append({
                'day': day,
                'is_closed': settings['is_closed'],
                'opens_at': settings['opens_at'],
                'closes_at': settings['closes_at'],
                'posts': settings['posts'],
                'slots': self.free_slots(day, duration, now=now),
            })
        return days

    # ------------------------------------------------------------------
    # Заявка клиента
    # ------------------------------------------------------------------

    def storage_sets(self, client, storage_ids):
        """
        Комплекты клиента, которые он просит достать со склада.

        Берём только его собственные: чужой номер комплекта в запросе
        не должен давать ничего, даже если его угадали.
        """
        from app.models import StoredSet

        if not storage_ids:
            return []

        return self.db.query(StoredSet).filter(
            StoredSet.id.in_(storage_ids),
            StoredSet.client_id == client.id,
            StoredSet.status == 'stored').all()

    @staticmethod
    def wheels_from_storage(sets):
        """
        Что именно лежит на складе — по этому и считаем время.

        Программа знает точнее клиента: комплект принимал мастер
        и записал, диски там или голые шины. Если хоть один без дисков,
        берём долгий вариант — иначе не уложимся.
        """
        if not sets:
            return None

        assembled = ['диск' in (row.storage_type or '').lower() for row in sets]
        if not all(assembled):
            return False
        return True

    def book(self, client, at, license_plate, wheels_assembled=None,
             comment=None, now=None, storage_ids=None):
        """Принять заявку на запись. Проверяет всё, что может пойти не так."""
        now = now or datetime.now()
        stored = self.storage_sets(client, storage_ids)
        if stored:
            wheels_assembled = self.wheels_from_storage(stored)

        plate = normalize_plate(license_plate)
        if not plate:
            raise BookingError('Не указан номер автомобиля')

        if at <= now:
            raise BookingError('Это время уже прошло')

        limit = now + timedelta(days=self.days_ahead())
        if at > limit:
            raise BookingError(
                f'Записаться можно не дальше чем на '
                f'{self.days_ahead()} дн. вперёд')

        # Машина могла ни разу не быть в цеху — тогда заводим её здесь
        # и привязываем к клиенту; при обмене цех подхватит
        car = self._ensure_car(client, plate, wheels_assembled)
        if wheels_assembled is None:
            wheels_assembled = car.wheels_assembled

        duration = self.duration_for(wheels_assembled)

        settings = self.day_settings(at.date())
        if settings['is_closed']:
            raise BookingError('В этот день шиномонтаж не работает')

        if not self._slot_is_free(at, duration, settings['posts']):
            raise BookingError('Это время только что заняли. Выберите другое')

        if self._already_booked(client, at):
            raise BookingError('У вас уже есть запись на это время')

        appointment = Appointment(
            client_id=client.id,
            car_id=car.id,
            scheduled_at=at,
            duration_minutes=duration,
            license_plate=plate,
            client_name=client.name,
            client_phone=client.phone,
            wheels_assembled=wheels_assembled,
            comment=(comment or '').strip() or None,
            status='scheduled',
            source='app',
            sync_state=PENDING,
        )
        self.db.add(appointment)

        # Заявка на комплекты: цех заберёт её при обмене, а кладовщик
        # узнает прямо сейчас — комплект надо найти на складе
        for row in stored:
            row.requested_for = at
            row.request_state = PENDING
            row.requested_at = now

        self.db.commit()
        self.db.refresh(appointment)

        if stored:
            self._tell_the_shop(appointment, stored, client)

        return appointment

    @staticmethod
    def _tell_the_shop(appointment, stored, client):
        """
        Сообщить в Telegram, что к записи нужно достать комплект.

        Ждать следующего обмена нельзя: между записью и приездом может
        быть меньше суток, а комплект надо найти на складе.
        """
        from app.services import notify
        from app.utils import format_phone

        def title(row):
            parts = [row.storage_type or 'Комплект']
            for value in (row.diameter, row.brand):
                if value:
                    parts.append(value)
            if row.wheel_type:
                parts.append(row.wheel_type.lower())
            return ' · '.join(parts)

        sets = '\n'.join(f'• № {row.id} — {title(row)}' for row in stored)

        notify.send_in_background(
            f'<b>Достать комплект со склада</b>\n\n'
            f'{appointment.scheduled_at:%d.%m.%Y} в '
            f'{appointment.scheduled_at:%H:%M}\n'
            f'{appointment.license_plate} · {client.name or "без имени"} · '
            f'{format_phone(client.phone)}\n\n'
            f'{sets}')

    def _ensure_car(self, client, plate, wheels_assembled):
        car = self.db.query(Car).filter(Car.license_plate == plate).first()
        if car is None:
            car = Car(license_plate=plate, client_id=client.id)
            self.db.add(car)
            self.db.flush()

        if car.client_id is None:
            car.client_id = client.id

        # Про колёса пишем в карточку, только если там пусто: мастер
        # видел машину своими глазами, клиент по памяти может ошибиться
        if wheels_assembled is not None and car.wheels_assembled is None:
            car.wheels_assembled = wheels_assembled

        return car

    def _slot_is_free(self, at, duration_minutes, posts):
        finish = at + timedelta(minutes=duration_minutes)
        overlapping = sum(1 for start, end in self._busy_at(at.date())
                          if start < finish and at < end)
        return overlapping < posts

    def _already_booked(self, client, at):
        """
        Одна машина — одна запись на время.

        Без этой проверки нажатие кнопки дважды подряд создаёт две
        записи, и цех держит два поста под одного человека.
        """
        window_start = at - timedelta(hours=1)
        window_end = at + timedelta(hours=1)
        return self.db.query(Appointment).filter(
            Appointment.client_id == client.id,
            Appointment.status == 'scheduled',
            Appointment.scheduled_at >= window_start,
            Appointment.scheduled_at <= window_end,
        ).first() is not None

    # ------------------------------------------------------------------

    def my_appointments(self, client, include_past=False, now=None):
        now = now or datetime.now()
        query = self.db.query(Appointment).filter(
            Appointment.client_id == client.id)

        if not include_past:
            query = query.filter(
                Appointment.scheduled_at >= now - timedelta(hours=3),
                Appointment.status.in_(BUSY_STATUSES))

        return query.order_by(Appointment.scheduled_at.desc()).all()

    def cancel(self, client, appointment_id, now=None):
        """
        Отменить свою запись.

        Незадолго до времени отменять в приложении не даём: цех уже
        держит под клиента пост, и такое лучше сказать голосом.
        """
        now = now or datetime.now()

        appointment = self.db.query(Appointment).filter(
            Appointment.id == appointment_id,
            Appointment.client_id == client.id).first()

        if appointment is None:
            raise BookingError('Запись не найдена')

        if appointment.status != 'scheduled':
            raise BookingError('Эту запись уже нельзя отменить')

        hours = shop_settings.get_int(self.db, 'booking_cancel_hours')
        if appointment.scheduled_at - now < timedelta(hours=hours):
            raise BookingError(
                f'До записи меньше {hours} ч. Позвоните в шиномонтаж, '
                f'чтобы отменить')

        appointment.status = 'cancelled'
        # Цех должен узнать об отмене так же, как узнаёт о записи
        appointment.sync_state = PENDING
        self.db.commit()
        return appointment


def to_public(appointment):
    """Запись в том виде, в каком её показывает приложение."""
    return {
        'id': appointment.id,
        'at': appointment.scheduled_at,
        'duration_minutes': appointment.duration_minutes,
        'license_plate': appointment.license_plate,
        'wheels_assembled': appointment.wheels_assembled,
        'status': appointment.status,
        'status_title': STATUS_TITLES.get(appointment.status, appointment.status),
        'is_confirmed': appointment.sync_state == TAKEN,
        'comment': appointment.comment,
    }
