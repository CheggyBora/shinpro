"""
Посты мойки.

Свои, отдельно от постов шиномонтажа: сколько — в Настройках →
«Направления». Пост занят, пока на нём неоплаченный наряд с мойкой.
Забытый вчерашний черновик пост не держит — как и в шиномонтаже.
"""
from datetime import timedelta

from models import WorkOrder
from services import directions
from utils import get_moscow_time, as_naive

STALE_HOURS = 18


class WashPosts:
    def __init__(self, db):
        self.db = db

    def total(self):
        return directions.wash_posts(self.db)

    def _busy(self):
        since = as_naive(get_moscow_time()) - timedelta(hours=STALE_HOURS)
        rows = self.db.query(WorkOrder).filter(
            WorkOrder.wash_post_number.isnot(None),
            WorkOrder.status != 'paid',
            WorkOrder.is_deleted.isnot(True)).all()
        return {o.wash_post_number: o for o in rows
                if o.created_at is None or as_naive(o.created_at) >= since}

    def posts(self):
        busy = self._busy()
        return [{'post': n, 'state': 'busy' if n in busy else 'free', 'order': busy.get(n)}
                for n in range(1, self.total() + 1)]

    def first_free(self):
        return next((p['post'] for p in self.posts() if p['state'] == 'free'), None)

    def set_post(self, order, post):
        """Переставить мойку наряда на другой пост — только на свободный."""
        if post is not None:
            state = next((p for p in self.posts() if p['post'] == post), None)
            if state is None:
                raise ValueError(f'Поста мойки {post} нет — работает {self.total()}')
            if state['state'] == 'busy' and state['order'].id != order.id:
                raise ValueError(f'Пост мойки {post} занят')
        order.wash_post_number = post
        self.db.commit()
        return order
