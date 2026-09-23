"""
Запись — через сервер.

Запись меняют оба: и приёмщик в цеху, и клиент в приложении. Поэтому
она живёт в одном месте, а не двумя копиями: копиям нечему помешать
разойтись, и разбирать это пришлось бы руками. Программа цеха
обращается к серверу по сети, как и приложение.

Цена решения принята осознанно: **без интернета записать нельзя.**
Показать — можно: последний полученный ответ складывается в местную
таблицу, и приёмщик видит, кого ждёт сегодня, даже когда связь моргнула.
Создать, отменить, отметить приезд в это время не даём и честно
говорим об этом, а не делаем вид, что сохранили.

Всё остальное — наряды, оплата, зарплата, печать — интернета не
касается вообще и работает, даже если связи нет неделю.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from logger import log
from utils import get_moscow_time, as_naive, normalize_plate, normalize_phone

TIMEOUT_SECONDS = 12

MIN_POSTS = 1
MAX_POSTS = 3
DEFAULT_POSTS = 1


class Offline(Exception):
    """
    Нет связи с сервером.

    Отдельный тип, чтобы интерфейс мог сказать «нет связи», а не
    вывалить человеку текст сетевой ошибки.
    """


class BookingError(Exception):
    """Сервер отказал по делу — например, время уже занято."""


class BookingApi:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------
    # Связь
    # ------------------------------------------------------------------

    def _sync(self):
        from services.sync_service import SyncService
        return SyncService(self.db)

    def is_configured(self):
        return self._sync().is_enabled()

    def _call(self, method, path, payload=None):
        sync = self._sync()
        if not sync.is_enabled():
            raise Offline('Обмен с сервером не настроен')

        url = sync.get_url()
        request = urllib.request.Request(
            f'{url}{path}',
            data=json.dumps(payload, ensure_ascii=False,
                            default=_encode).encode('utf-8')
            if payload is not None else None,
            headers={'Content-Type': 'application/json',
                     'X-Sync-Key': sync.get_key()},
            method=method)

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
                return json.loads(answer.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = json.loads(e.read().decode('utf-8')).get('detail', '')
            except Exception:
                pass
            # Отказ по делу — это не потеря связи: показывать надо разное
            raise BookingError(detail or f'Сервер отклонил запрос: {e}')
        except urllib.error.URLError as e:
            raise Offline(f'Нет связи с сервером: {e.reason}')
        except Exception as e:
            raise Offline(f'Не удалось обратиться к серверу: {e}')

    # ------------------------------------------------------------------
    # Время работ
    # ------------------------------------------------------------------

    def duration_for_wheels(self, wheels_assembled):
        """Считается на месте: настройки те же, что уходят на сервер."""
        from services.settings_service import SettingsService

        settings = SettingsService(self.db)
        if wheels_assembled is True:
            return settings.get_int('booking_minutes_assembled')
        if wheels_assembled is False:
            return settings.get_int('booking_minutes_tires')
        return settings.get_int('booking_minutes_unknown')

    # ------------------------------------------------------------------
    # День
    # ------------------------------------------------------------------

    def get_day(self, day):
        """
        Записи на день.

        Возвращает словарь с записями, числом постов и признаком того,
        свежие ли данные. Нет связи — отдаём последнее, что успели
        получить, и честно помечаем, когда это было.
        """
        try:
            answer = self._call('GET', f'/sync/appointments?day={day.isoformat()}')
        except (Offline, BookingError) as e:
            log.warning(f"Записи на {day:%d.%m} не получены: {e}")
            return self._from_cache(day, reason=str(e))

        rows = self._store(day, answer)
        return {
            'day': day,
            'posts': answer.get('posts', DEFAULT_POSTS),
            'is_closed': answer.get('is_closed', False),
            'appointments': rows,
            'online': True,
            'fetched_at': get_moscow_time(),
            'reason': None,
        }

    def _store(self, day, answer):
        """Перезаписать кэш дня целиком: правку строк потом всё равно затрёт."""
        from models import Appointment

        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)
        self.db.query(Appointment).filter(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < end).delete(synchronize_session=False)
        self.db.commit()

        # Новые строки займут те же номера, что удалённые. Пока прежние
        # объекты помнятся сессией, SQLAlchemy справедливо ругается на
        # двух разных жильцов одного адреса — отпускаем их
        self.db.expunge_all()

        now = get_moscow_time()
        rows = []
        for item in answer.get('appointments', []):
            row = Appointment(
                server_id=item['id'],
                scheduled_at=_decode_time(item['scheduled_at']),
                duration_minutes=item.get('duration_minutes') or 60,
                license_plate=item.get('license_plate'),
                client_name=item.get('client_name'),
                client_phone=item.get('client_phone'),
                status=item.get('status') or 'scheduled',
                source=item.get('source') or 'phone',
                comment=item.get('comment'),
                post_column=item.get('column', 0),
                fetched_at=now)
            self.db.add(row)
            rows.append(row)

        self.db.commit()
        for row in rows:
            self.db.refresh(row)
        return rows

    def _from_cache(self, day, reason):
        from models import Appointment

        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)
        rows = self.db.query(Appointment).filter(
            Appointment.scheduled_at >= start,
            Appointment.scheduled_at < end).order_by(
            Appointment.scheduled_at).all()

        fetched = max((as_naive(row.fetched_at) for row in rows
                       if row.fetched_at), default=None)

        return {
            'day': day,
            'posts': self._cached_posts(day),
            'is_closed': False,
            'appointments': rows,
            'online': False,
            'fetched_at': fetched,
            'reason': reason,
        }

    def _cached_posts(self, day):
        from models import BookingPosts

        row = self.db.query(BookingPosts).filter(BookingPosts.day == day).first()
        return row.posts if row else DEFAULT_POSTS

    # ------------------------------------------------------------------
    # Действия — только при связи
    # ------------------------------------------------------------------

    def create(self, scheduled_at, duration_minutes, license_plate=None,
               client_name=None, client_phone=None, wheels_assembled=None,
               comment=None, force=True):
        """
        Записать клиента. Возвращает ответ сервера.

        force=True — приёмщик может записать сверх постов: он видит бокс
        и решает сам. Но занятость сервер всё равно вернёт, и программа
        предупредит до сохранения.
        """
        return self._call('POST', '/sync/appointments', {
            'scheduled_at': as_naive(scheduled_at),
            'duration_minutes': duration_minutes,
            'license_plate': normalize_plate(license_plate) or None,
            'client_name': (client_name or '').strip() or None,
            'client_phone': normalize_phone(client_phone) or None,
            'wheels_assembled': wheels_assembled,
            'comment': (comment or '').strip() or None,
            'force': force,
        })

    def update(self, server_id, **fields):
        payload = {}
        for key in ('scheduled_at', 'duration_minutes', 'license_plate',
                    'client_name', 'client_phone', 'status', 'comment'):
            if key in fields:
                value = fields[key]
                if key == 'scheduled_at' and value is not None:
                    value = as_naive(value)
                payload[key] = value
        return self._call('PATCH', f'/sync/appointments/{server_id}', payload)

    def cancel(self, server_id):
        return self.update(server_id, status='cancelled')

    def mark_arrived(self, server_id):
        return self.update(server_id, status='arrived')

    def mark_no_show(self, server_id):
        return self.update(server_id, status='no_show')

    # ------------------------------------------------------------------
    # Посты
    # ------------------------------------------------------------------

    @staticmethod
    def clamp_posts(posts):
        try:
            posts = int(posts)
        except (TypeError, ValueError):
            return DEFAULT_POSTS
        return max(MIN_POSTS, min(MAX_POSTS, posts))

    def get_posts_for_day(self, day):
        """Постов на день. Без связи — из кэша, чтобы лента не сломалась."""
        try:
            answer = self._call('GET', f'/sync/posts?day={day.isoformat()}&days=1')
            posts = self.clamp_posts(answer.get(day.isoformat(), DEFAULT_POSTS))
            self._cache_posts({day: posts})
            return posts
        except (Offline, BookingError):
            return self._cached_posts(day)

    def get_posts_map(self, start_day, days):
        try:
            answer = self._call(
                'GET', f'/sync/posts?day={start_day.isoformat()}&days={days}')
        except (Offline, BookingError):
            return {start_day + timedelta(days=i): self._cached_posts(
                start_day + timedelta(days=i)) for i in range(max(1, days))}

        result = {}
        for offset in range(max(1, days)):
            day = start_day + timedelta(days=offset)
            result[day] = self.clamp_posts(
                answer.get(day.isoformat(), DEFAULT_POSTS))
        self._cache_posts(result)
        return result

    def set_posts_for_days(self, start_day, days, posts):
        posts = self.clamp_posts(posts)
        days = max(1, int(days))
        self._call('PUT', '/sync/posts', {
            'day': start_day.isoformat(), 'days': days, 'posts': posts})

        self._cache_posts({start_day + timedelta(days=offset): posts
                           for offset in range(days)})
        return posts

    def _cache_posts(self, values):
        """Помнить постов по дням, чтобы офлайн лента рисовалась правильно."""
        from models import BookingPosts

        for day, posts in values.items():
            row = self.db.query(BookingPosts).filter(
                BookingPosts.day == day).first()
            if row is None:
                row = BookingPosts(day=day)
                self.db.add(row)
            row.posts = posts
        self.db.commit()


def _encode(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    raise TypeError(f'Не знаю, как отправить {type(value)}')


def _decode_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return as_naive(value)
    try:
        return as_naive(datetime.fromisoformat(str(value).replace('Z', '')))
    except ValueError:
        return None
