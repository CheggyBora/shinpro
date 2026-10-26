"""
Всё по машине на одном экране: владелец, комплекты на хранении,
задачи, история нарядов и покраски.

Открывается из задачи календаря, из наряда и из подсказки номера. В
задаче «привезти комплект Петрову» приёмщику нужно не искать по трём
вкладкам, а увидеть сразу: что лежит, когда был, что делали.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from models import TireStorage, WorkOrder, CalendarTask
from services.calendar_service import CalendarService, storage_title
from ui.plate_picker import owner_of
from utils import normalize_plate, format_phone, as_naive
from services.arrival_service import cover_file, load_image, show_full

# Главное окно ставит сюда «открыть наряд на этот номер»
ON_NEW_ORDER = None

VEHICLE_TITLES = {'car': 'Легковой', 'suv': 'Джип/кроссовер', 'truck': 'Коммерческий'}


def open_car_info(parent, db, plate):
    return CarInfo(parent, db, plate)


class CarInfo:
    def __init__(self, parent, db, plate):
        self.db = db
        self.plate = normalize_plate(plate)
        self.car, self.owner = owner_of(db, self.plate)

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f'Машина {self.plate}')
        self.dialog.geometry('760x640')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())

        outer = ttk.Frame(self.dialog, style='White.TFrame')
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, bg=styles.COLORS['bg_card'], highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas, style='White.TFrame')
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=body, anchor='nw', width=730)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True, padx=(16, 0), pady=14)
        scroll.pack(side='right', fill='y')
        self.body = body
        self._build()

        styles.center_window(self.dialog, parent.winfo_toplevel())

    # ------------------------------------------------------------------

    def _section(self, title):
        styles.create_label(self.body, title, 'CardHeading.TLabel').pack(anchor='w', pady=(14, 4))

    def _line(self, left, right, muted=False, cover=None):
        row = ttk.Frame(self.body, style='White.TFrame')
        row.pack(fill='x', pady=1)
        ttk.Label(row, text=left, width=11, font=styles.FONTS['small'],
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(side='left', anchor='n')
        # У визита со снимком — маленькая обложка, щелчок — крупно
        image = load_image(cover, 40, 30) if cover else None
        if image is not None:
            thumb = tk.Label(row, image=image, cursor='hand2', bd=0, bg=styles.COLORS['bg_card'])
            thumb.image = image
            thumb.pack(side='left', padx=(0, 8))
            thumb.bind('<Button-1>', lambda e, p=cover: show_full(self.dialog, p, self.plate))
        ttk.Label(row, text=right, font=styles.FONTS['normal'], wraplength=600, justify='left',
                  foreground=styles.COLORS['text_secondary'] if muted else styles.COLORS['text'],
                  background=styles.COLORS['bg_card']).pack(side='left', anchor='w')

    def _build(self):
        head = ttk.Frame(self.body, style='White.TFrame')
        head.pack(fill='x')
        tk.Label(head, text=self.plate, font=(styles.DEFAULT_FONT, 18, 'bold'),
                 bg=styles.COLORS['bg_card'], fg=styles.COLORS['text'],
                 relief='solid', borderwidth=2, padx=10).pack(side='left')
        if self.car is not None:
            facts = [VEHICLE_TITLES.get(self.car.vehicle_type, self.car.vehicle_type or ''),
                     self.car.wheel_diameter or '']
            if getattr(self.car, 'wheels_assembled', None) is not None:
                facts.append('колёса в сборе' if self.car.wheels_assembled else 'только шины')
            ttk.Label(head, text=' · '.join(f for f in facts if f), font=styles.FONTS['normal'],
                      foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card']).pack(side='left', padx=12)

        # Последний снимок машины — крупно: видно, в каком виде она
        # приезжала (docs/order_photo.md)
        from services.arrival_service import ArrivalService
        if self.car is not None:
            shot_order, shot = ArrivalService(self.db).latest_for_car(self.car.id)
            image = load_image(shot, 280, 210) if shot else None
            if image is not None:
                when = as_naive(shot_order.created_at)
                photo = tk.Label(self.body, image=image, cursor='hand2', bd=0,
                                 bg=styles.COLORS['bg_card'])
                photo.image = image
                photo.pack(anchor='w', pady=(10, 0))
                photo.bind('<Button-1>', lambda e, p=shot: show_full(self.dialog, p, self.plate))
                ttk.Label(self.body, text=f'Последнее фото — {when:%d.%m.%Y}' if when else 'Последнее фото',
                          font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                          background=styles.COLORS['bg_card']).pack(anchor='w')

        self._section('Владелец')
        if self.owner is None:
            self._line('', 'не записан', muted=True)
        else:
            self._line('Имя', self.owner.name or 'без имени')
            self._line('Телефон', format_phone(self.owner.phone) if self.owner.phone else '—')
            self._line('Водительское', self.owner.driver_license or '—')

        self._section('На хранении')
        sets = self.db.query(TireStorage).filter(
            TireStorage.car_number == self.plate).order_by(
            TireStorage.status.desc(), TireStorage.accepted_date.desc()).limit(8).all()
        if not sets:
            self._line('', 'комплектов нет', muted=True)
        for row in sets:
            accepted = as_naive(row.accepted_date)
            if row.status == 'stored':
                when = f'с {accepted:%d.%m.%Y}' if accepted else ''
                if row.expires_at:
                    when += f' · до {as_naive(row.expires_at):%d.%m.%Y}'
                self._line(f'№{row.id}', f'{storage_title(row)} · {when}')
            else:
                released = as_naive(row.released_date)
                self._line(f'№{row.id}', f'{storage_title(row)} · выдан '
                           f'{released:%d.%m.%Y}' if released else storage_title(row), muted=True)

        self._section('Задачи')
        service = CalendarService(self.db)
        tasks = self.db.query(CalendarTask).filter(
            CalendarTask.license_plate == self.plate,
            CalendarTask.deleted.is_(False)).order_by(CalendarTask.due_date.desc()).limit(12).all()
        if not tasks:
            self._line('', 'задач нет', muted=True)
        for task in tasks:
            text = f'{service.title_of(task.category)} · {task.title}'
            if task.amount:
                text += f' · {task.amount:,.0f} ₽'.replace(',', ' ')
            self._line(f'{task.due_date:%d.%m.%y}', text + (' — сделано' if task.done_at else ''),
                       muted=bool(task.done_at))

        self._section('История нарядов')
        orders = []
        if self.car is not None:
            orders = self.db.query(WorkOrder).filter(
                WorkOrder.car_id == self.car.id,
                WorkOrder.is_deleted.isnot(True)).order_by(
                WorkOrder.created_at.desc()).limit(30).all()
        if not orders:
            self._line('', 'нарядов нет', muted=True)
        for order in orders:
            names = ', '.join(sorted({item.service.name for item in order.items
                                      if getattr(item, 'service', None)}))
            when = as_naive(order.created_at)
            total = f' · {order.total_amount:,.0f} ₽'.replace(',', ' ') if order.total_amount else ''
            state = '' if order.status == 'paid' else ' · не оплачен'
            self._line(f'{when:%d.%m.%y}' if when else '', f'№{order.id} · {names or "без услуг"}{total}{state}',
                       cover=cover_file(order, self.db))

        buttons = ttk.Frame(self.body, style='White.TFrame')
        buttons.pack(fill='x', pady=(16, 8))
        if ON_NEW_ORDER is not None:
            styles.create_button(buttons, 'Создать наряд', self.new_order,
                                 'Primary.TButton').pack(side='left')
        if self.owner is not None:
            styles.create_button(buttons, 'Карточка клиента', self.client_card,
                                 'Secondary.TButton').pack(side='left', padx=(8, 0))
        styles.create_button(buttons, 'Закрыть', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right')

    def new_order(self):
        self.dialog.destroy()
        ON_NEW_ORDER(self.plate)

    def client_card(self):
        from ui.client_card import open_client_card
        try:
            open_client_card(self.dialog, self.db, self.owner.id)
        except Exception as e:
            messagebox.showerror('Клиент', f'Не удалось открыть карточку: {e}', parent=self.dialog)
