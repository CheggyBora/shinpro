"""
Откуда берутся записи: из своей базы или с сервера.

У программы два режима, и переключает их одна галочка в настройках.

**Сервер не настроен** — всё как раньше: записи лежат в своей базе,
интернет не нужен вообще. Программа самодостаточна, и шиномонтаж
без приложения работает ровно так же, как работал.

**Сервер настроен** — записи переезжают на сервер целиком. Их меняют
оба, приёмщик и клиент из приложения, поэтому копий быть не должно:
копиям нечему помешать разойтись. Плата за это — без интернета
записать нельзя; видеть сегодняшних записанных можно, они лежат
в местном кэше с отметкой, когда получены.

Экран записи про это не знает: он спрашивает у шлюза, а тот сам решает,
идти в свою базу или в сеть.
"""
from datetime import timedelta

from utils import get_moscow_time

MIN_POSTS = 1
MAX_POSTS = 3
DEFAULT_POSTS = 1


def get_booking(db):
    """Тот способ работы с записями, который сейчас настроен."""
    from services.sync_service import SyncService

    if SyncService(db).is_enabled():
        return RemoteBooking(db)
    return LocalBooking(db)


class LocalBooking:
    """Записи в своей базе. Интернет не нужен."""

    is_remote = False

    def __init__(self, db):
        from services.appointment_service import AppointmentService

        self.db = db
        self.service = AppointmentService(db)

    @staticmethod
    def key_of(row):
        return row.id

    def load_day(self, day):
        return {
            'placed': self.service.layout_day(day),
            'posts': self.service.get_posts_for_day(day),
            # Своя база всегда «на связи»: она лежит на этом же диске
            'online': True,
            'fetched_at': get_moscow_time(),
            'reason': None,
        }

    def duration_for_wheels(self, wheels_assembled):
        return self.service.duration_for_wheels(wheels_assembled)

    def check_capacity(self, at, duration, exclude_id=None):
        return self.service.check_capacity(at, duration, exclude_id=exclude_id)

    def create(self, **fields):
        from models import Appointment

        appointment = self.service.create(
            scheduled_at=fields['scheduled_at'],
            duration_minutes=fields['duration_minutes'],
            client_name=fields.get('client_name'),
            client_phone=fields.get('client_phone'),
            license_plate=fields.get('license_plate'),
            wheels_assembled=fields.get('wheels_assembled'),
            comment=fields.get('comment'),
            source=fields.get('source', Appointment.SOURCE_PHONE))
        return appointment.id

    def update(self, key, **fields):
        fields.pop('wheels_assembled', None)
        return self.service.update(key, **fields)

    def get(self, key):
        return self.service.get(key)

    def cancel(self, key):
        return self.service.cancel(key)

    def mark_arrived(self, key):
        return self.service.mark_arrived(key)

    def mark_no_show(self, key):
        return self.service.mark_no_show(key)

    def get_posts_for_day(self, day):
        return self.service.get_posts_for_day(day)

    def get_posts_map(self, start_day, days):
        return self.service.get_posts_map(start_day, days)

    def set_posts_for_days(self, start_day, days, posts):
        return self.service.set_posts_for_days(start_day, days, posts)


class RemoteBooking:
    """Записи на сервере. Без связи — только смотреть."""

    is_remote = True

    def __init__(self, db):
        from services.booking_api import BookingApi

        self.db = db
        self.api = BookingApi(db)

    @staticmethod
    def key_of(row):
        return row.server_id

    def load_day(self, day):
        answer = self.api.get_day(day)
        posts = answer['posts']

        # Колонку посчитал сервер — цех и приложение должны рисовать
        # одинаково, иначе спорить будут о том, кто где стоит
        placed = [(row, row.post_column if row.post_column is not None else posts)
                  for row in answer['appointments']]

        return {
            'placed': placed,
            'posts': posts,
            'online': answer['online'],
            'fetched_at': answer['fetched_at'],
            'reason': answer['reason'],
        }

    def duration_for_wheels(self, wheels_assembled):
        return self.api.duration_for_wheels(wheels_assembled)

    def check_capacity(self, at, duration, exclude_id=None):
        """
        Занятость считает сервер при сохранении.

        Заранее спрашивать не идём: пока приёмщик заполняет форму,
        окно могли занять, и ответ всё равно устареет. Сервер вернёт
        занятость вместе с созданием.
        """
        posts = self.api.get_posts_for_day(at.date())
        return True, 0, posts

    def create(self, **fields):
        answer = self.api.create(
            scheduled_at=fields['scheduled_at'],
            duration_minutes=fields['duration_minutes'],
            license_plate=fields.get('license_plate'),
            client_name=fields.get('client_name'),
            client_phone=fields.get('client_phone'),
            wheels_assembled=fields.get('wheels_assembled'),
            comment=fields.get('comment'))
        return answer['id']

    def update(self, key, **fields):
        return self.api.update(key, **fields)

    def get(self, key):
        from models import Appointment

        return self.db.query(Appointment).filter(
            Appointment.server_id == key).first()

    def cancel(self, key):
        return self.api.cancel(key)

    def mark_arrived(self, key):
        return self.api.mark_arrived(key)

    def mark_no_show(self, key):
        return self.api.mark_no_show(key)

    def get_posts_for_day(self, day):
        return self.api.get_posts_for_day(day)

    def get_posts_map(self, start_day, days):
        return self.api.get_posts_map(start_day, days)

    def set_posts_for_days(self, start_day, days, posts):
        return self.api.set_posts_for_days(start_day, days, posts)
