"""
Без открытой смены наряд не создаётся, не меняется и не пробивается
(правило владельца 27.10.2026). Смену открывают руками, закрывается она
каждое утро в 9:05, если не закрыли раньше, — и всё, что сделано с
нарядом, относится к смене, которая идёт.
"""
import functools
from tkinter import messagebox

SHIFT_CLOSED = ("Смена закрыта. Откройте смену: без неё наряды не создаются, "
                "не меняются и не пробиваются.")


def shift_open(db):
    from services.shift_service import ShiftService
    return ShiftService(db).get_current_shift() is not None


def needs_shift(method):
    """Действие с нарядом — только при открытой смене, иначе подсказка."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not shift_open(self.db):
            messagebox.showwarning("Смена закрыта", SHIFT_CLOSED)
            return None
        return method(self, *args, **kwargs)
    return wrapper
