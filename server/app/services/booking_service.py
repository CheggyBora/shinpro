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
from app.services import branding, shop_settings
from app.utils import normalize_plate, now as shop_now

# Состояния, при которых машина занимает пост
BUSY_STATUSES = ('scheduled', 'arrived')

# Один ответ на все случаи: цех, кабинет, перенос. Двух машин на один
# пост в одно время не бывает, и кто сохранил первым — того и время.
# Разные формулировки на одно событие заставляли бы человека думать,
# что это разные запреты
SLOT_TAKEN = 'На это время уже кто-то записался. Выберите другое время'

STATUS_TITLES = {
    'scheduled': 'Ожидается',
    'arrived': 'Вы приехали',
    'cancelled': 'Отменена',
    'no_show': 'Не приехали',
}



DIAMETERS = [f'R{n}' for n in range(13, 25)]


def clean_diameter(value):
    """«R16» — или None, если пусто или не из списка."""
    value = (value or '').strip().upper()
    return value if value in DIAMETERS else None


# Направления записи (docs/booking_wash.md). Всё, что было до мойки, —
# шиномонтаж: поэтому пустое и есть шиномонтаж
TIRE = 'tire'
WASH = 'wash'
DIRECTIONS = (TIRE, WASH)

# Класс машины для мойки — в этом порядке их показывает кабинет
WASH_CLASSES = {
    'sedan': 'Седан',
    'crossover': 'Кроссовер',
    'jeep': 'Джип',
    'minivan': 'Минивэн',
}


def clean_direction(value):
    """
    «tire» или «wash». Пусто — шиномонтаж; непонятное — None.

    Непонятное не превращаем в шиномонтаж молча: человек, нажавший
    «Мойка», не должен оказаться записанным на шиномонтаж из-за опечатки
    в запросе — вызывающий скажет об ошибке.
    """
    value = (value or '').strip().lower()
    if not value:
        return TIRE
    return value if value in DIRECTIONS else None


def clean_wash_class(value):
    """«sedan» и т.п. — или None, если пусто или не из списка."""
    value = (value or '').strip().lower()
    return value if value in WASH_CLASSES else None


class BookingError(Exception):
    """Понятная клиенту причина, почему записаться не вышло."""


WASH_OFF = 'Запись на мойку здесь не принимается. Позвоните нам, пожалуйста'


def service_for(db, shop, direction=None):
    """
    Расчёт записи для кабинета: шиномонтаж или мойка.

    Мойку отдаём, только если точка её записывает: иначе кабинет
    показал бы окна мойки, которой нет, — по старой ссылке или
    набранному руками адресу.
    """
    cleaned = clean_direction(direction)
    if cleaned is None:
        raise BookingError('Не понятно, куда записываться: '
                           'шиномонтаж или мойка')
    if cleaned == WASH and not shop_settings.wash_booking_on(db, shop):
        raise BookingError(WASH_OFF)
    return BookingService(db, shop, cleaned)


class BookingService:
    def __init__(self, db, shop=None, direction=TIRE):
        """
        shop — точка, о которой идёт речь.

        Без неё считать нечего: посты, часы работы и занятость у каждой
        точки свои. Когда точка одна, её подставляет вызывающий —
        сервер не угадывает.

        direction — шиномонтаж или мойка. У каждого свои посты, часы и
        окна, и занятость считается раздельно: запись на мойку не
        занимает пост шиномонтажа и наоборот (docs/booking_wash.md).
        """
        self.db = db
        self.shop = shop
        self.shop_id = getattr(shop, 'id', shop)
        self.direction = WASH if direction == WASH else TIRE

    @property
    def is_wash(self):
        return self.direction == WASH

    # ------------------------------------------------------------------
    # Расчёт окон
    # ------------------------------------------------------------------

    def duration_for(self, wheels_assembled=None):
        if self.is_wash:
            # Мойка занимает одно и то же время, колёса тут ни при чём
            return max(1, shop_settings.get_int(self.db, 'wash_booking_minutes',
                                                shop=self.shop))
        if wheels_assembled is True:
            return shop_settings.get_int(self.db, 'booking_minutes_assembled', shop=self.shop)
        if wheels_assembled is False:
            return shop_settings.get_int(self.db, 'booking_minutes_tires', shop=self.shop)
        return shop_settings.get_int(self.db, 'booking_minutes_unknown', shop=self.shop)

    def day_settings(self, day):
        """Посты и рабочие часы дня. Чего цех не прислал — то по умолчанию."""
        if self.is_wash:
            # У мойки отдельной настройки по дням нет: посты и часы —
            # из её настроек. Дни в booking_days — это посты шиномонтажа,
            # и перенести их на мойку значило бы выдумать ей расписание
            return {'posts': max(1, shop_settings.get_int(
                        self.db, 'wash_booking_posts', shop=self.shop)),
                    'opens_at': shop_settings.get(
                        self.db, 'wash_booking_opens_at', shop=self.shop),
                    'closes_at': shop_settings.get(
                        self.db, 'wash_booking_closes_at', shop=self.shop),
                    'is_closed': False}

        row = self.db.query(BookingDay).filter(
            BookingDay.day == day,
            BookingDay.shop_id == self.shop_id).first()
        if row is None:
            # День, который в цеху отдельно не настраивали: берём общее
            # число постов из настроек — то же, по которому считает сама
            # программа шиномонтажа
            return {'posts': self._default_posts(),
                    'opens_at': self._default_opens(),
                    'closes_at': self._default_closes(), 'is_closed': False}
        return {'posts': max(1, row.posts),
                'opens_at': row.opens_at or self._default_opens(),
                'closes_at': row.closes_at or self._default_closes(),
                'is_closed': row.is_closed}

    def _default_posts(self):
        return max(1, shop_settings.get_int(self.db, 'booking_posts',
                                            shop=self.shop))

    def _default_opens(self):
        return shop_settings.get(self.db, 'booking_opens_at', shop=self.shop)

    def _default_closes(self):
        return shop_settings.get(self.db, 'booking_closes_at', shop=self.shop)

    def _busy_at(self, day, exclude_id=None):
        """
        Записи дня, занимающие посты, отрезками времени.

        exclude_id — не считать саму переносимую запись. Иначе сдвиг
        на четверть часа упёрся бы в собственный хвост.

        Считаем только записи своего направления: машина на мойке не
        держит пост шиномонтажа, и наоборот.
        """
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)

        query = self.db.query(Appointment).filter(
            Appointment.shop_id == self.shop_id,
            Appointment.direction == self.direction,
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < end,
            Appointment.status.in_(BUSY_STATUSES),
        )
        if exclude_id is not None:
            query = query.filter(Appointment.id != exclude_id)
        rows = query.all()

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

    def hourly(self):
        """
        Запись «N машин в час», без постов (решение владельца 28.10.2026):
        цех прислал booking_mode = hourly. N — то же число, что посты под
        запись (1–3). Машины физически к постам не привязаны: сколько
        записались на этот час — столько и приедет, примут мастера.
        """
        return (not self.is_wash
                and shop_settings.get(self.db, 'booking_mode', shop=self.shop) == 'hourly')

    def _taken(self, busy, at, finish):
        """Сколько мест занято: по постам — наложения, по часам — записи этого часа."""
        if self.hourly():
            hour = at.replace(minute=0, second=0, microsecond=0)
            return sum(1 for start, _end in busy
                       if start.replace(minute=0, second=0, microsecond=0) == hour)
        return sum(1 for start, end in busy if start < finish and at < end)

    def free_slots(self, day, duration_minutes, now=None):
        """
        Свободные окна дня.

        Окно годится, если работа успевает закончиться до закрытия
        и если на всё её время хватает свободного поста. Проверяем
        именно весь отрезок, а не момент начала: иначе клиента можно
        записать на 20:30 при закрытии в 21:00 на полуторачасовую работу.
        """
        now = now or shop_now()
        settings = self.day_settings(day)
        if settings['is_closed']:
            return []

        midnight = datetime.combine(day, time.min)
        opens = midnight + timedelta(
            minutes=self._minutes_of(settings['opens_at'], 7 * 60))
        closes = midnight + timedelta(
            minutes=self._minutes_of(settings['closes_at'], 24 * 60))
        step = timedelta(minutes=max(1, self.slot_step()))
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
            overlapping = self._taken(busy, moment, finish)
            if overlapping < posts:
                slots.append({'at': moment, 'free_posts': posts - overlapping})
            moment += step

        return slots

    def slot_step(self):
        """Шаг сетки окон: у мойки свой, короче — мойка быстрее."""
        key = 'wash_booking_slot_step' if self.is_wash else 'booking_slot_step'
        return shop_settings.get_int(self.db, key, shop=self.shop)

    def days_ahead(self):
        return max(1, shop_settings.get_int(self.db, 'booking_days_ahead', shop=self.shop))

    def storage_lead_days(self):
        """
        За сколько дней записываться, если просят комплект со склада.

        Комплект надо найти на хранении, привезти и подготовить. В тот
        же день это не делается, и показать человеку завтрашнее утро —
        значит либо обмануть его, либо сорвать работу склада.
        """
        return max(0, shop_settings.get_int(self.db, 'storage_lead_days',
                                            shop=self.shop))

    def storage_ready_from(self, now=None):
        """С какого дня можно записываться с выдачей со склада."""
        lead = self.storage_lead_days()
        if not lead:
            return None
        return ((now or shop_now()) + timedelta(days=lead)).date()

    def calendar(self, wheels_assembled=None, now=None, with_storage=False):
        """
        Ближайшие дни со свободными окнами — то, что рисует приложение.

        Если человек просит комплект со склада, ближайшие дни закрыты:
        комплект к ним не успеют привезти. Закрываем, а не прячем —
        иначе непонятно, почему запись начинается с четверга.
        """
        now = now or shop_now()
        duration = self.duration_for(wheels_assembled)
        # Мойке комплект со склада не нужен — и закрывать дни незачем
        ready_from = (self.storage_ready_from(now)
                      if with_storage and not self.is_wash else None)

        days = []
        for offset in range(self.days_ahead()):
            day = (now + timedelta(days=offset)).date()
            settings = self.day_settings(day)

            too_soon = ready_from is not None and day < ready_from
            days.append({
                'day': day,
                'is_closed': settings['is_closed'] or too_soon,
                'opens_at': settings['opens_at'],
                'closes_at': settings['closes_at'],
                'posts': settings['posts'],
                'slots': [] if too_soon else self.free_slots(day, duration,
                                                             now=now),
                # Чтобы приложение сказало человеку, почему день закрыт,
                # а не оставило его гадать
                'storage_too_soon': too_soon,
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

    def check_wash_class(self, wash_class):
        """
        Класс машины для мойки — без него запись на мойку не принимаем.

        От класса зависит цена, и приёмщик должен знать её заранее, а не
        выяснять у ворот. Заодно проверяем, что мойку здесь записывают:
        запрос приходит из интернета, а не только из нашей страницы.
        """
        if not shop_settings.wash_booking_on(self.db, self.shop):
            raise BookingError(WASH_OFF)
        cleaned = clean_wash_class(wash_class)
        if cleaned is None:
            raise BookingError('Выберите класс машины')
        return cleaned

    def book(self, client, at, license_plate, wheels_assembled=None,
             comment=None, now=None, storage_ids=None, wheel_diameter=None,
             wash_class=None):
        """Принять заявку на запись. Проверяет всё, что может пойти не так."""
        now = now or shop_now()

        if self.is_wash:
            # Мойке не нужны ни колёса, ни диаметр, ни комплекты со
            # склада: присланное по ошибке не должно попасть ни в запись,
            # ни в карточку машины
            wash_class = self.check_wash_class(wash_class)
            wheels_assembled = None
            wheel_diameter = None
            storage_ids = None
        else:
            wash_class = None

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
        if wheels_assembled is None and not self.is_wash:
            wheels_assembled = car.wheels_assembled

        duration = self.duration_for(wheels_assembled)

        settings = self.day_settings(at.date())
        if settings['is_closed']:
            raise BookingError('В этот день мойка не работает' if self.is_wash
                               else 'В этот день шиномонтаж не работает')

        # Приложение такие дни не показывает, но полагаться на это
        # нельзя: запрос приходит из интернета, а не из нашей страницы
        if stored:
            ready_from = self.storage_ready_from(now)
            if ready_from is not None and at.date() < ready_from:
                lead = self.storage_lead_days()
                raise BookingError(
                    f'Комплект со склада привезут не раньше чем через '
                    f'{lead} дн. Выберите день с '
                    f'{ready_from.strftime("%d.%m")}')

        if not self._slot_is_free(at, duration, settings['posts']):
            raise BookingError(SLOT_TAKEN)

        if self._already_booked(client, at):
            raise BookingError('У вас уже есть запись на это время')

        appointment = Appointment(
            shop_id=self.shop_id,
            client_id=client.id,
            car_id=car.id,
            scheduled_at=at,
            duration_minutes=duration,
            license_plate=plate,
            client_name=client.name,
            client_phone=client.phone,
            wheels_assembled=wheels_assembled,
            comment=(comment or '').strip() or None,
            wheel_diameter=clean_diameter(wheel_diameter),
            direction=self.direction,
            wash_class=wash_class,
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

        # Подтверждение сейчас, напоминание накануне. Кладём в очередь,
        # а не шлём здесь: человек должен увидеть «записали» сразу, не
        # дожидаясь, пока ответит телеграм
        try:
            from app.services import notices, shop_settings

            name = (shop_settings.get(self.db, 'shop_name', shop=self.shop)
                    or (self.shop.name if self.shop else 'Шиномонтаж'))
            notices.plan_for_appointment(self.db, client, name, appointment)
        except Exception as e:
            # Не сумели запланировать напоминание — запись всё равно
            # состоялась, и терять её из-за этого нельзя
            import logging
            logging.getLogger('tire_server').warning(
                'Напоминание не запланировано: %s', e)

        if stored:
            self._task_for_storage(appointment, stored, client)
            self._tell_the_shop(appointment, stored, client)

        return appointment

    def _task_for_storage(self, appointment, stored, client):
        """
        Задача кладовщику в календарь: привезти комплекты к записи.

        Сообщение в Telegram пролистают, а задача висит в ленте цеха,
        пока её не отметят. Не вышло — запись всё равно состоялась.
        """
        try:
            from app.services import tasks

            tasks.for_appointment(self.db, appointment, stored, client)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            import logging
            logging.getLogger('tire_server').warning(
                'Задача на комплект не поставлена: %s', e)

    @staticmethod
    def _tell_the_shop(appointment, stored, client):
        """
        Сообщить в Telegram, что к записи нужно достать комплект.

        Ждать следующего обмена нельзя: между записью и приездом может
        быть меньше суток, а комплект надо найти на складе.
        """
        from app.services import notify
        from app.services.tasks import set_number, set_title
        from app.utils import format_phone

        # Номер — тот, под которым комплект лежит на полке в цеху
        sets = '\n'.join(f'• № {set_number(row)} — {set_title(row)}'
                         for row in stored)

        notify.send_in_background(
            f'<b>Достать комплект со склада</b>\n\n'
            f'{appointment.scheduled_at:%d.%m.%Y} в '
            f'{appointment.scheduled_at:%H:%M}\n'
            f'{appointment.license_plate} · {client.name or "без имени"} · '
            f'{format_phone(client.phone)}\n\n'
            f'{sets}',
            shop=appointment.shop_id, kind=notify.KIND_STORAGE)

    def _ensure_car(self, client, plate, wheels_assembled):
        # Машина принадлежит аккаунту: в сети из трёх точек это одна и
        # та же машина, а у чужого шиномонтажа — своя
        car = self.db.query(Car).filter(
            Car.license_plate == plate,
            Car.account_id == client.account_id).first()
        if car is None:
            car = Car(license_plate=plate, client_id=client.id,
                      account_id=client.account_id)
            self.db.add(car)
            self.db.flush()

        if car.client_id is None:
            car.client_id = client.id

        # Про колёса пишем в карточку, только если там пусто: мастер
        # видел машину своими глазами, клиент по памяти может ошибиться
        if wheels_assembled is not None and car.wheels_assembled is None:
            car.wheels_assembled = wheels_assembled

        return car

    def _slot_is_free(self, at, duration_minutes, posts, exclude_id=None):
        finish = at + timedelta(minutes=duration_minutes)
        overlapping = self._taken(self._busy_at(at.date(), exclude_id), at, finish)
        return overlapping < posts

    def _already_booked(self, client, at):
        """
        Одна машина — одна запись на время.

        Без этой проверки нажатие кнопки дважды подряд создаёт две
        записи, и цех держит два поста под одного человека.

        Смотрим своё направление: шиномонтаж в десять и мойка в
        одиннадцать — не двойное нажатие, а обычный день человека.
        """
        window_start = at - timedelta(hours=1)
        window_end = at + timedelta(hours=1)
        return self.db.query(Appointment).filter(
            Appointment.client_id == client.id,
            Appointment.shop_id == self.shop_id,
            Appointment.direction == self.direction,
            Appointment.status == 'scheduled',
            Appointment.scheduled_at >= window_start,
            Appointment.scheduled_at <= window_end,
        ).first() is not None

    # ------------------------------------------------------------------

    def my_appointments(self, client, include_past=False, now=None):
        now = now or shop_now()
        # Здесь точку не сужаем намеренно: человек записался в одну
        # точку сети, а смотрит в приложении все свои записи сразу
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
        now = now or shop_now()

        appointment = self.db.query(Appointment).filter(
            Appointment.id == appointment_id,
            Appointment.client_id == client.id).first()

        if appointment is None:
            raise BookingError('Запись не найдена')

        if appointment.status != 'scheduled':
            raise BookingError('Эту запись уже нельзя отменить')

        hours = shop_settings.get_int(self.db, 'booking_cancel_hours', shop=self.shop)
        if appointment.scheduled_at - now < timedelta(hours=hours):
            raise BookingError(
                f'До записи меньше {hours} ч. Позвоните в шиномонтаж, '
                f'чтобы отменить')

        appointment.status = 'cancelled'

        # Напоминание «завтра приезжать» теперь ни к чему. Отменил сам
        # человек — и сообщать ему об этом не надо: он только что нажал
        # кнопку и видел ответ
        try:
            from app.services import notices

            notices.cancel_about(self.db, 'appointment', appointment.id)
        except Exception:
            pass
        # Комплект со склада к этой записи больше не нужен — задача
        # кладовщику снимается вместе с записью
        from app.services import tasks

        tasks.follow_appointment(self.db, appointment)

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
        # Мойка или шиномонтаж: в «Моих записях» человек должен видеть,
        # куда записан, — «Мойка · Кроссовер» или «Шиномонтаж · R16»
        'direction': appointment.direction or TIRE,
        'wash_class': appointment.wash_class,
        'wash_class_title': WASH_CLASSES.get(appointment.wash_class or ''),
        'wheel_diameter': appointment.wheel_diameter,
        # Живая очередь: нажал «Я на месте», позвали ли на пост
        'on_site': appointment.on_site_at is not None,
        # Не сезон — постов не раздаём, «Я на месте» не нужно
        'can_check_in': can_check_in(appointment) and _queue_on(appointment),
        'called_post': appointment.called_post,
        # Схема — только для площадки, с которой нарисована
        'scene': branding.parking_scene(appointment, appointment.called_post),
    }


# «Я на месте» можно нажать незадолго до записи и пока она не прошла
CHECK_IN_BEFORE_MINUTES = 60
CHECK_IN_AFTER_MINUTES = 60


def _queue_on(appointment):
    from sqlalchemy.orm import object_session
    db = object_session(appointment)
    return db is None or shop_settings.live_queue_on(db, appointment.shop_id)


def can_check_in(appointment, now=None):
    # Живой очереди у мойки нет — некому давать «первый свободный пост»,
    # и «Я на месте» там ничего бы не значило (docs/booking_wash.md)
    if appointment.direction == WASH:
        return False
    if appointment.status != 'scheduled' or appointment.on_site_at is not None:
        return False
    now = now or shop_now()
    at = appointment.scheduled_at
    return (at - timedelta(minutes=CHECK_IN_BEFORE_MINUTES) <= now
            <= at + timedelta(minutes=CHECK_IN_AFTER_MINUTES))
