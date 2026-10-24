"""
Поле номера машины с подсказкой — как в нарядах.

Нужно в задаче календаря и в покраске: номер набирают, программа
предлагает знакомые машины и, выбрав, подставляет владельца. Новый
номер тоже годится — машина заведётся, когда по ней откроют наряд.
"""
import tkinter as tk
from tkinter import ttk

import styles
from utils import normalize_plate, format_phone


class PlatePicker:
    def __init__(self, parent, db, on_pick=None, width=16):
        self.db = db
        self.on_pick = on_pick
        self.frame = ttk.Frame(parent, style='White.TFrame')
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self.frame, textvariable=self.var, width=width,
                               font=styles.FONTS['normal'])
        self.entry.pack(anchor='w')
        self.listbox_frame = tk.Frame(self.frame, bg='white', relief='solid', borderwidth=1)
        self.listbox = tk.Listbox(self.listbox_frame, height=5, font=styles.FONTS['normal'],
                                  exportselection=False)
        self.listbox.pack(fill='both', expand=True)
        self._plates = None
        self.entry.bind('<KeyRelease>', self._typed)
        self.entry.bind('<Down>', self._down)
        self.entry.bind('<Return>', self._enter)
        self.entry.bind('<FocusOut>', lambda e: self.frame.after(200, self._hide))
        self.listbox.bind('<ButtonRelease-1>', self._chosen)
        self.listbox.bind('<Return>', self._chosen)

    def plates(self):
        if self._plates is None:
            from services.order_service import OrderService
            self._plates = OrderService(self.db).get_all_license_plates()
        return self._plates

    def get(self):
        return normalize_plate(self.var.get())

    def set(self, plate):
        self.var.set(normalize_plate(plate or ''))

    def _typed(self, event):
        if event.keysym in ('Down', 'Up', 'Return', 'Escape', 'Tab'):
            return
        typed = normalize_plate(self.var.get())
        self.listbox.delete(0, tk.END)
        if not typed:
            self._hide()
            return
        starts = [p for p in self.plates() if normalize_plate(p).startswith(typed)]
        contains = [p for p in self.plates() if typed in normalize_plate(p) and p not in starts]
        found = (starts + contains)[:30]
        if not found:
            self._hide()
            return
        for plate in found:
            self.listbox.insert(tk.END, plate)
        self.listbox_frame.pack(fill='x')

    def _hide(self):
        self.listbox_frame.pack_forget()

    def _down(self, event):
        if self.listbox.size():
            self.listbox.focus_set()
            self.listbox.selection_set(0)
            self.listbox.activate(0)
        return 'break'

    def _enter(self, event):
        if self.listbox.size() and self.listbox_frame.winfo_ismapped():
            self.pick(self.listbox.get(0))
        else:
            self.pick(self.var.get())
        return 'break'

    def _chosen(self, event=None):
        chosen = self.listbox.curselection()
        if chosen:
            self.pick(self.listbox.get(chosen[0]))

    def pick(self, plate):
        self.set(plate)
        self._hide()
        if self.on_pick:
            self.on_pick(self.get())


def owner_of(db, plate):
    """Владелец машины: из самой машины, иначе из последнего наряда."""
    from services.order_service import OrderService
    service = OrderService(db)
    car = service.get_car_by_license_plate(plate)
    owner = car.client if car is not None else None
    if owner is None:
        last = service.get_last_order_for_car(plate)
        owner = last.client if last is not None else None
    return car, owner


def owner_text(owner):
    if owner is None:
        return ''
    parts = [owner.name or 'без имени']
    if owner.phone:
        parts.append(format_phone(owner.phone))
    return ' · '.join(parts)
