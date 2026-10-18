"""
Живая очередь и раздача постов.

Договорённости — в docs/live_queue.md. Коротко:

  · встать в очередь можно только на месте: по QR у въезда или через
    приёмщика;
  · освободившийся пост сначала идёт записанным, и только если
    ближайшая запись останется обеспечена постами — первому в очереди;
  · следить за этим физически некому, поэтому решает программа:
    она знает, какой пост когда освободится (наряд: начало и плановое
    время), и не зовёт из очереди на пост, который нужен записи.

Всё считается в программе цеха и работает без интернета. Записи на день
берутся из копии, которую цех держит у себя (Appointment).
"""
import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import WorkOrder, Appointment, Service
from models.live_queue import (LiveQueueEntry, WAITING, CALLED, SERVING,
                               DONE, LEFT, ACTIVE)
from utils import get_moscow_time, as_naive, normalize_plate, normalize_phone

# Настройки и их значения по умолчанию
BUFFER_KEY = 'live_queue_buffer_minutes'        # запас на допы
BUFFER_DEFAULT = 20
CALL_WAIT_KEY = 'live_queue_call_wait_minutes'  # позвали — сколько ждём
LATE_KEY = 'booking_late_minutes'               # опоздал — пост не держим
LATE_DEFAULT = 10
AUTO_CALL_KEY = 'live_queue_auto_call'          # звать самой программе
# Посты и живая очередь — на сезон. Выключено: наряды открываются как
# раньше, без постов, программа никого не зовёт, по QR встать нельзя
ENABLED_KEY = 'live_queue_enabled'
# Наряд старше этого считается забытым черновиком, а не машиной на посту:
# иначе вчерашний неоплаченный наряд держал бы пост вечно
STALE_HOURS = 18
CALL_WAIT_DEFAULT = 5
MAX_MISSES = 2                                  # второй пропуск — выбывает

KIT_ASSEMBLED_KEY = 'kit_assembled'
KIT_TIRES_KEY = 'kit_tires'
KIT_ASSEMBLED_DEFAULT = ['Съем+Установка', 'Мойка', 'Балансировка']
KIT_TIRES_DEFAULT = ['Съем+Установка', 'Мойка', 'Балансировка', 'Шиномонтаж']

DIAMETERS = [f'R{n}' for n in range(13, 25)]


class QueueError(ValueError):
    """Понятная человеку причина, почему не вышло."""


class LiveQueueService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------

    def _settings(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db)

    def buffer_minutes(self):
        return max(0, self._settings().get_int(BUFFER_KEY, BUFFER_DEFAULT))

    def late_minutes(self):
        return max(1, self._settings().get_int(LATE_KEY, LATE_DEFAULT))

    def call_wait_minutes(self):
        return max(1, self._settings().get_int(CALL_WAIT_KEY, CALL_WAIT_DEFAULT))

    def kit(self, wheels_assembled):
        """Какие услуги ставить в наряд: в сборе, только шины, не указано."""
        if wheels_assembled is None:
            return []
        key, default = ((KIT_ASSEMBLED_KEY, KIT_ASSEMBLED_DEFAULT)
                        if wheels_assembled else
                        (KIT_TIRES_KEY, KIT_TIRES_DEFAULT))
        raw = self._settings().get_raw(key)
        if raw is None:
            return list(default)
        try:
            names = json.loads(raw)
        except ValueError:
            return list(default)
        return [n for n in names if isinstance(n, str) and n]

    def set_kit(self, wheels_assembled, names):
        key = KIT_ASSEMBLED_KEY if wheels_assembled else KIT_TIRES_KEY
        clean = []
        for name in names:
            name = (name or '').strip()
            if name and name not in clean:
                clean.append(name)
        self._settings().set(key, json.dumps(clean, ensure_ascii=False))
        return clean

    # ------------------------------------------------------------------
    # Посты
    # ------------------------------------------------------------------

    def posts_total(self):
        """Сколько постов работает сейчас — по открытой смене."""
        from services.shift_service import ShiftService

        shift = ShiftService(self.db).get_current_shift()
        if shift and shift.open_posts:
            return int(shift.open_posts)
        return max(1, self._settings().get_int('default_posts', 2))

    def _open_orders_on_posts(self):
        """Наряды, которые сейчас стоят на постах: {пост: наряд}."""
        since = as_naive(get_moscow_time()) - timedelta(hours=STALE_HOURS)
        rows = self.db.query(WorkOrder).filter(
            WorkOrder.post_number.isnot(None),
            WorkOrder.status != 'paid',
            WorkOrder.is_deleted.isnot(True),
            WorkOrder.created_at >= since).all()
        busy = {}
        for order in rows:
            # На один пост двое не встают; если вдруг так — считаем
            # того, кто дольше
            current = busy.get(order.post_number)
            if current is None or self.order_free_at(order) > self.order_free_at(current):
                busy[order.post_number] = order
        return busy

    def order_free_at(self, order, now=None):
        """Когда, по плану, освободит пост этот наряд."""
        now = now or as_naive(get_moscow_time())
        planned = order.planned_minutes or 0
        if not planned:
            from services.order_service import OrderService
            planned = OrderService(self.db).calculate_planned_minutes(order.id)
        started = as_naive(order.started_at or order.created_at) or now
        free_at = started + timedelta(minutes=planned + (order.paused_minutes or 0))
        # Плановое время вышло, а наряд открыт — значит, вот-вот
        return max(free_at, now)

    def posts(self, now=None):
        """
        Состояние постов: [{'post', 'state', 'free_at', 'order', 'entry'}].

        state: 'busy' — стоит машина; 'called' — позвали, едет;
        'free' — свободен.
        """
        now = now or as_naive(get_moscow_time())
        busy = self._open_orders_on_posts()
        called = {e.post_number: e for e in self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.status == CALLED,
            LiveQueueEntry.post_number.isnot(None)).all()}
        booked = {a.called_post: a for a in self._today_bookings(now)
                  if a.called_post and a.status == Appointment.STATUS_SCHEDULED}

        result = []
        for post in range(1, self.posts_total() + 1):
            if post in busy:
                order = busy[post]
                result.append({'post': post, 'state': 'busy', 'order': order,
                               'entry': None,
                               'free_at': self.order_free_at(order, now)})
            elif post in called:
                entry = called[post]
                result.append({'post': post, 'state': 'called', 'order': None,
                               'entry': entry,
                               'free_at': now + timedelta(
                                   minutes=self.expected_minutes(entry))})
            elif post in booked:
                appointment = booked[post]
                result.append({'post': post, 'state': 'called', 'order': None,
                               'entry': None, 'booking': appointment,
                               'free_at': now + timedelta(minutes=(
                                   self.package_minutes(appointment.wheels_assembled)
                                   + self.buffer_minutes()))})
            else:
                result.append({'post': post, 'state': 'free', 'order': None,
                               'entry': None, 'free_at': now})
        return result

    # ------------------------------------------------------------------
    # Запись: сколько постов ей нужно
    # ------------------------------------------------------------------

    def _bookings_ahead(self, now, horizon):
        """
        Записи, которым ещё понадобится пост: от «сейчас» до горизонта.
        {время: сколько машин}.

        Ушедшие в наряд (arrived), отменённые и неявки поста уже не
        требуют. Запись, чьё время прошло, но человек ещё может
        подъехать, держим до её конца — она по-прежнему первая.
        """
        start = now - timedelta(hours=1)
        rows = self.db.query(Appointment).filter(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at <= horizon,
            Appointment.status == Appointment.STATUS_SCHEDULED).all()
        need = {}
        late = timedelta(minutes=self.late_minutes())
        for row in rows:
            at = as_naive(row.scheduled_at)
            end = at + timedelta(minutes=row.duration_minutes or 60)
            if end <= now:
                continue
            if row.called_post:
                continue        # уже позвали — его пост занят и так
            if row.on_site:
                continue        # на месте — получит пост первым и без держания
            # Опоздал больше чем на N минут и не на месте — пост отдаём
            # очереди; приедет — встанет первым на ближайший свободный
            if not row.on_site and now > at + late:
                continue
            at = max(at, now)
            need[at] = need.get(at, 0) + 1
        return need

    def booking_allows(self, minutes, post, now=None, planned=None):
        """
        Можно ли занять пост post на minutes минут и не подвести запись.

        Для каждого времени записи до конца этих работ: свободных к тому
        моменту постов (кроме занятого нами) должно хватить на всех
        записанных на это время.

        planned — {пост: когда освободится} для постов, которые мы уже
        мысленно отдали в этом же раунде подсказок.
        """
        now = now or as_naive(get_moscow_time())
        until = now + timedelta(minutes=minutes)
        need = self._bookings_ahead(now, until)
        if not need:
            return True, None

        planned = planned or {}
        free_at = [planned.get(s['post'], s['free_at'])
                   for s in self.posts(now) if s['post'] != post]
        for at in sorted(need):
            if at >= until:
                continue
            ready = sum(1 for moment in free_at if moment <= at)
            if ready < need[at]:
                return False, at
        return True, None

    # ------------------------------------------------------------------
    # Очередь
    # ------------------------------------------------------------------

    def line(self):
        """Кто в очереди сейчас: позванные, потом ждущие — по времени."""
        rows = self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.status.in_(ACTIVE)).all()
        return sorted(rows, key=lambda e: (e.status != CALLED,
                                           as_naive(e.joined_at)))

    def waiting(self):
        return [e for e in self.line() if e.status == WAITING]

    def find_active(self, plate):
        plate = normalize_plate(plate)
        return self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.license_plate == plate,
            LiveQueueEntry.status.in_(ACTIVE)).first()

    def add(self, license_plate, phone=None, wheel_diameter=None,
            wheels_assembled=None, vehicle_type='car', client_name=None,
            source='shop', server_id=None, joined_at=None):
        """
        Поставить машину в очередь.

        Одна машина — одно место: тот же номер с тем же телефоном
        возвращает его место, а не ставит в конец. С другим телефоном —
        отказ, иначе по чужому номеру можно было бы занять или снять место.
        """
        plate = normalize_plate(license_plate)
        if not plate:
            raise QueueError('Укажите номер машины')
        phone = normalize_phone(phone) if phone else None
        if wheel_diameter and wheel_diameter not in DIAMETERS:
            raise QueueError('Диаметр — от R13 до R24')

        existing = self.find_active(plate)
        if existing is not None:
            if existing.phone and phone and existing.phone != phone:
                raise QueueError(
                    f'Машина {plate} уже в очереди с другим телефоном')
            return existing

        if wheel_diameter is None or wheels_assembled is None:
            # Знакомая машина: подставим, что знаем
            from models import Car
            car = self.db.query(Car).filter(Car.license_plate == plate).first()
            if car is not None:
                wheel_diameter = wheel_diameter or car.wheel_diameter
                if wheels_assembled is None:
                    wheels_assembled = car.wheels_assembled
                vehicle_type = car.vehicle_type or vehicle_type

        entry = LiveQueueEntry(
            license_plate=plate, phone=phone, client_name=client_name,
            wheel_diameter=wheel_diameter, wheels_assembled=wheels_assembled,
            vehicle_type=vehicle_type or 'car', source=source,
            server_id=server_id,
            joined_at=joined_at or get_moscow_time(), status=WAITING)
        self.db.add(entry)
        self.db.commit()
        return entry

    def package_minutes(self, wheels_assembled):
        """
        Время пакета: на дисках — полчаса, только шины — час. Те же
        настройки, по которым считается запись, — время одно для всех.
        """
        settings = self._settings()
        if wheels_assembled is True:
            return settings.get_int('booking_minutes_assembled', 30)
        if wheels_assembled is False:
            return settings.get_int('booking_minutes_tires', 60)
        return settings.get_int('booking_minutes_unknown', 60)

    def expected_minutes(self, entry):
        """Сколько займёт машина: время пакета + запас на допы."""
        return self.package_minutes(entry.wheels_assembled) + self.buffer_minutes()

    def _service(self, name, vehicle_type):
        found = self.db.query(Service).filter(
            Service.name == name, Service.vehicle_type == vehicle_type,
            Service.is_active.isnot(False)).first()
        if found is None:
            found = self.db.query(Service).filter(
                Service.name == name, Service.vehicle_type == 'all',
                Service.is_active.isnot(False)).first()
        return found

    # ------------------------------------------------------------------
    # Кто следующий
    # ------------------------------------------------------------------

    def suggestion(self, now=None):
        """
        Что делать со свободными постами прямо сейчас.

        [{'post', 'entry' или None, 'hold_for' — время записи, ради
        которой пост держим}]
        """
        now = now or as_naive(get_moscow_time())
        free = [s['post'] for s in self.posts(now) if s['state'] == 'free']
        queue = self.waiting()
        result = []
        taken = set()
        planned = {}

        # Записанные, которые уже на месте, — первыми, по времени записи
        for appointment in self.bookings_on_site(now):
            if not free:
                break
            post = free.pop(0)
            result.append({'post': post, 'entry': None, 'booking': appointment,
                           'hold_for': None})
            planned[post] = now + timedelta(minutes=self.package_minutes(
                appointment.wheels_assembled) + self.buffer_minutes())

        for post in free:
            chosen, hold = None, None
            for entry in queue:
                if entry.id in taken:
                    continue
                minutes = self.expected_minutes(entry)
                ok, at = self.booking_allows(minutes, post, now, planned)
                if ok:
                    chosen = entry
                    planned[post] = now + timedelta(minutes=minutes)
                    break
                hold = hold or at
            if chosen is not None:
                taken.add(chosen.id)
            result.append({'post': post, 'entry': chosen, 'booking': None,
                           'hold_for': None if chosen else hold})
        return result

    def estimates(self, now=None):
        """
        Примерно когда подойдёт очередь каждого ждущего: {id: время}.

        Прикидка по тем же правилам, что и раздача: посты освобождаются
        по прогнозу, записанные занимают посты в своё время, ждущий
        встаёт на ближайший пост, только если не помешает записи.
        Точнее «плюс-минус» здесь не бывает — допы непредсказуемы.
        """
        now = now or as_naive(get_moscow_time())
        free = [[s['free_at'], s['post']] for s in self.posts(now)]
        if not free:
            return {}
        need = dict(self._bookings_ahead(now, now + timedelta(hours=10)))
        booking = timedelta(minutes=self.package_minutes(None))

        def serve_bookings_until(moment):
            # Записанные, чьё время уже наступило к moment, забирают
            # ближайшие посты — они первые
            for at in sorted(need):
                while need[at] > 0 and at <= moment:
                    free.sort()
                    start = max(free[0][0], at)
                    free[0][0] = start + booking
                    need[at] -= 1

        result = {}
        for entry in self.waiting():
            minutes = timedelta(minutes=self.expected_minutes(entry))
            for _ in range(50):
                free.sort()
                serve_bookings_until(free[0][0])
                free.sort()
                start = free[0][0]
                blocked = None
                for at in sorted(need):
                    if need[at] <= 0 or not (start < at < start + minutes):
                        continue
                    ready = sum(1 for moment, _ in free[1:] if moment <= at)
                    if ready < need[at]:
                        blocked = at
                        break
                if blocked is None:
                    result[entry.id] = start
                    free[0][0] = start + minutes
                    break
                # Этот пост уйдёт записи — ждущий встанет после неё
                free[0][0] = max(start, blocked) + booking
                need[blocked] -= 1
        return result

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def call(self, entry_id, post):
        entry = self._get(entry_id)
        if entry.status not in ACTIVE:
            raise QueueError('Этой машины уже нет в очереди')
        state = next((s for s in self.posts() if s['post'] == post), None)
        if state is None:
            raise QueueError(f'Поста {post} нет — работает {self.posts_total()}')
        if state['state'] != 'free' and not (
                state['state'] == 'called' and state['entry'].id == entry.id):
            raise QueueError(f'Пост {post} занят')
        entry.status = CALLED
        entry.post_number = post
        entry.called_at = get_moscow_time()
        self.db.commit()
        return entry

    def missed(self, entry_id):
        """
        Позвали, а машина не подъехала. В конец очереди; второй раз —
        выбывает: место держат те, кто стоит рядом.
        """
        entry = self._get(entry_id)
        entry.misses = (entry.misses or 0) + 1
        entry.post_number = None
        entry.called_at = None
        if entry.misses >= MAX_MISSES:
            entry.status = LEFT
            entry.closed_at = get_moscow_time()
        else:
            # В конец — строго после последнего ждущего: метки времени
            # могут совпасть до доли секунды, а порядок должен быть точным
            last = max((as_naive(e.joined_at) for e in self.db.query(LiveQueueEntry).filter(
                LiveQueueEntry.status.in_(ACTIVE),
                LiveQueueEntry.id != entry.id).all()), default=None)
            now = as_naive(get_moscow_time())
            entry.status = WAITING
            entry.joined_at = max(now, last + timedelta(milliseconds=1)) if last else now
        self.db.commit()
        return entry

    def expire_calls(self, now=None):
        """Позванные, кто не подъехал за отведённые минуты, — пропуск."""
        now = now or as_naive(get_moscow_time())
        limit = timedelta(minutes=self.call_wait_minutes())
        expired = []
        for entry in self.db.query(LiveQueueEntry).filter(
                LiveQueueEntry.status == CALLED).all():
            if entry.called_at and now - as_naive(entry.called_at) >= limit:
                expired.append(self.missed(entry.id))
        for appointment in self._today_bookings():
            if (appointment.status == 'scheduled' and appointment.called_post
                    and appointment.called_at
                    and now - as_naive(appointment.called_at) >= limit):
                self.release_booking(appointment)
                expired.append(appointment)
        return expired

    def leave(self, entry_id):
        entry = self._get(entry_id)
        entry.status = LEFT
        entry.closed_at = get_moscow_time()
        self.db.commit()
        return entry

    def open_order(self, entry_id, post=None):
        """
        Машина подъехала — открыть наряд, сразу заполненный: номер,
        телефон, диаметр, пост и услуги за комплект по колёсам.
        """
        from services.order_service import OrderService

        entry = self._get(entry_id)
        if entry.status not in ACTIVE:
            raise QueueError('Этой машины уже нет в очереди')
        post = post or entry.post_number
        if post is None:
            free = [s['post'] for s in self.posts() if s['state'] == 'free']
            if not free:
                raise QueueError('Свободных постов нет')
            post = free[0]

        orders = OrderService(self.db)
        order = orders.create_order(
            entry.license_plate, entry.wheel_diameter or 'R16',
            entry.vehicle_type or 'car',
            client_name=entry.client_name, client_phone=entry.phone,
            wheels_assembled=entry.wheels_assembled)
        order.post_number = post
        order.package_minutes = self.package_minutes(entry.wheels_assembled)
        self.db.commit()

        for name in self.kit(entry.wheels_assembled):
            service = self._service(name, order.vehicle_type)
            if service is not None:
                orders.add_service_to_order(order.id, service.id)
        order.planned_minutes = orders.calculate_planned_minutes(order.id)
        self.db.commit()

        entry.status = SERVING
        entry.post_number = post
        entry.order_id = order.id
        self.db.commit()
        return order

    def _today_bookings(self, now=None):
        now = now or as_naive(get_moscow_time())
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return self.db.query(Appointment).filter(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < start + timedelta(days=1)).all()

    def bookings_on_site(self, now=None):
        """Записанные, что нажали «Я на месте» и ещё ждут поста."""
        rows = [a for a in self._today_bookings(now)
                if a.on_site and not a.called_post
                and a.status == Appointment.STATUS_SCHEDULED]
        return sorted(rows, key=lambda a: as_naive(a.scheduled_at))

    def call_booking(self, appointment, post):
        """
        Позвать записанного на пост. Сервер скажет ему (Telegram или
        браузер) и покажет схему в кабинете. Без связи — копию отметим
        всё равно, а сказать придётся голосом: вернём причину.
        """
        state = next((s for s in self.posts() if s['post'] == post), None)
        if state is None or state['state'] != 'free':
            raise QueueError(f'Пост {post} занят')
        appointment.called_post = post
        appointment.called_at = get_moscow_time()
        self.db.commit()
        if not appointment.server_id:
            return None
        from services.booking_api import BookingApi
        api = BookingApi(self.db)
        try:
            api.call_to_post(appointment.server_id, post)
        except Exception as e:
            api.remember(appointment, call=post)
            return str(e)
        return None

    def release_booking(self, appointment):
        """
        Позвали записанного, а он не подъехал: пост отдаём дальше.
        «На месте» снимаем тоже — иначе программа звала бы его снова и
        снова, держа пост. Приедет — нажмёт «Я на месте» ещё раз.
        """
        appointment.called_post = None
        appointment.called_at = None
        appointment.on_site = False
        self.db.commit()
        if not appointment.server_id:
            return
        from services.booking_api import BookingApi
        api = BookingApi(self.db)
        try:
            api.update(appointment.server_id, on_site=False)
        except Exception:
            api.remember(appointment, on_site=False)

    def booking_diameter(self, appointment):
        """Диаметр для наряда по записи: из записи, иначе из карточки машины."""
        if appointment.wheel_diameter:
            return appointment.wheel_diameter
        from models import Car
        car = self.db.query(Car).filter(
            Car.license_plate == normalize_plate(appointment.license_plate or '')).first()
        return car.wheel_diameter if car is not None else None

    def open_booking_order(self, appointment, post=None):
        """
        Записанный приехал — наряд так же, как из очереди: свободный пост,
        клиент, диаметр, услуги и время пакета. Записанные идут первыми,
        поэтому пост берём любой свободный.
        """
        from services.order_service import OrderService

        diameter = self.booking_diameter(appointment)
        if not diameter:
            raise QueueError('В записи нет диаметра')
        if post is None:
            post = appointment.called_post
        if post is None:
            free = [s['post'] for s in self.posts() if s['state'] == 'free']
            post = free[0] if free else None

        wheels = appointment.wheels_assembled
        orders = OrderService(self.db)
        order = orders.create_order(
            appointment.license_plate, diameter, 'car',
            client_name=appointment.client_name,
            client_phone=appointment.client_phone,
            wheels_assembled=wheels)
        order.post_number = post
        order.package_minutes = self.package_minutes(wheels)
        self.db.commit()
        for name in self.kit(wheels):
            service = self._service(name, order.vehicle_type)
            if service is not None:
                orders.add_service_to_order(order.id, service.id)
        order.planned_minutes = orders.calculate_planned_minutes(order.id)
        self.db.commit()
        return order

    def enabled(self):
        return self._settings().is_on(ENABLED_KEY)

    def auto_call_enabled(self):
        return self._settings().is_on(AUTO_CALL_KEY)

    def auto_call(self, now=None):
        """
        Позвать самой: следить за постами физически некому. Свободный
        пост — тому, кому его предлагает подсказка: записанному на месте
        или первому в очереди, если запись это позволяет. Возвращает,
        скольких позвали.
        """
        if not self.enabled() or not self.auto_call_enabled():
            return 0
        called = 0
        for item in self.suggestion(now):
            try:
                if item.get('booking') is not None:
                    self.call_booking(item['booking'], item['post'])
                    called += 1
                elif item.get('entry') is not None:
                    self.call(item['entry'].id, item['post'])
                    called += 1
            except QueueError:
                continue
        return called

    def first_free_post(self):
        free = [s['post'] for s in self.posts() if s['state'] == 'free']
        return free[0] if free else None

    def set_order_post(self, order_id, post):
        """Переставить наряд на другой пост — только на свободный."""
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        if order is None:
            raise QueueError('Наряд не найден')
        if post is not None:
            state = next((s for s in self.posts() if s['post'] == post), None)
            if state is None:
                raise QueueError(f'Поста {post} нет — работает {self.posts_total()}')
            if state['state'] != 'free' and not (
                    state['state'] == 'busy' and state['order'].id == order.id):
                raise QueueError(f'Пост {post} занят')
        order.post_number = post
        self.db.commit()
        entry = self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.order_id == order_id).first()
        if entry is not None:
            entry.post_number = post
            self.db.commit()
        return order

    def order_removed(self, order_id):
        """Наряд удалили — место в очереди закрываем, пост свободен."""
        entry = self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.order_id == order_id).first()
        if entry is not None and entry.status == SERVING:
            entry.status = LEFT
            entry.closed_at = get_moscow_time()
            self.db.commit()
        return entry

    def order_closed(self, order_id):
        """Наряд оплачен — место в очереди закрыто."""
        entry = self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.order_id == order_id).first()
        if entry is not None and entry.status == SERVING:
            entry.status = DONE
            entry.closed_at = get_moscow_time()
            self.db.commit()
        return entry

    def _get(self, entry_id):
        entry = self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.id == entry_id).first()
        if entry is None:
            raise QueueError('Машина в очереди не найдена')
        return entry

    # ------------------------------------------------------------------
    # Обмен с сервером: места по QR
    # ------------------------------------------------------------------

    def server_payload(self, now=None):
        """
        Что сказать серверу о местах, взятых по QR: какой по счёту,
        примерно когда, позвали ли и на какой пост. Закрытые недавно —
        тоже, чтобы страница у человека показала «готово» или «ушёл».
        """
        now = now or as_naive(get_moscow_time())
        recent = now - timedelta(hours=3)
        rows = self.db.query(LiveQueueEntry).filter(
            LiveQueueEntry.server_id.isnot(None)).all()
        rows = [e for e in rows if e.status in ACTIVE or e.status == SERVING
                or (e.closed_at and as_naive(e.closed_at) >= recent)]
        etas = self.estimates(now)
        places = {e.id: i for i, e in enumerate(self.waiting(), start=1)}
        result = []
        for entry in rows:
            eta = etas.get(entry.id)
            result.append({
                'local_id': entry.id,
                'server_id': entry.server_id,
                'state': entry.status,
                'place': places.get(entry.id),
                'eta_at': eta.replace(microsecond=0).isoformat() if eta else None,
                'post_number': entry.post_number if entry.status in (CALLED, SERVING) else None,
            })
        return result

    def apply_server(self, answer):
        """
        Принять от сервера новые места по QR и тех, кто ушёл сам.
        Возвращает, сколько новых мест добавилось.
        """
        from datetime import datetime as _dt
        from logger import log

        added = 0
        # Не приняли (та же машина с другим телефоном) — сервер закроет
        # место, человеку на странице скажут подойти к приёмщику
        self.rejected = []
        today = as_naive(get_moscow_time()).date()
        for item in answer.get('new') or []:
            server_id = item.get('server_id')
            if server_id is None:
                continue
            if self.db.query(LiveQueueEntry).filter(
                    LiveQueueEntry.server_id == server_id).first() is not None:
                continue        # уже взяли, просто сервер ещё не узнал
            joined = None
            try:
                joined = _dt.fromisoformat(item.get('joined_at') or '')
            except ValueError:
                pass
            if joined is not None and joined.date() != today:
                joined = None   # вчерашнее время не ставит его первым
            try:
                entry = self.add(item.get('license_plate'), item.get('phone'),
                                 item.get('wheel_diameter'), item.get('wheels_assembled'),
                                 source='qr', server_id=server_id, joined_at=joined)
            except QueueError as e:
                log.warning(f"Место по QR не принято: {e}")
                self.rejected.append(server_id)
                continue
            if entry.server_id is None:
                # Приёмщик уже поставил эту машину вручную — связываем
                entry.server_id = server_id
                self.db.commit()
            added += 1

        for server_id in answer.get('left') or []:
            entry = self.db.query(LiveQueueEntry).filter(
                LiveQueueEntry.server_id == server_id).first()
            if entry is not None and entry.status in ACTIVE:
                self.leave(entry.id)
        return added
