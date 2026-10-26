"""
Раздел «Календарь»: неделя сверху, задачи выбранного дня ниже.

Фильтры по разделам — чтобы склад, покраска и шины не путались между
собой: Рабочая, Хранение, Шины, Покраска, Все (docs/calendar.md). Выбор
запоминается на этом компьютере.
"""
import tkinter as tk
from datetime import timedelta
from tkinter import ttk, messagebox

import styles
from models.calendar import CATEGORIES, CATEGORY_TITLES, categories_of
from services.calendar_service import CalendarService
from ui.task_dialog import open_task, CATEGORY_COLORS, WHO
from utils import get_moscow_time, as_naive

FILTER_KEY = 'calendar_filter'
WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
WEEKDAYS_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
          'сентября', 'октября', 'ноября', 'декабря']
DANGER = ('#b91c1c', '#fee2e2')
WARN = ('#92400e', '#fef3c7')


def day_title(day):
    return f'{WEEKDAYS_FULL[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}'


class CalendarTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = CalendarService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        today = self._today()
        self.selected = today
        self.week_start = today - timedelta(days=today.weekday())
        # Слой календаря: шиномонтаж или мойка — его выбирает переключатель
        # сверху (главное окно зовёт set_direction)
        self.direction = 'tire'
        self.filters = self._load_filters()
        # Главное окно ставит сюда «что-то поменялось» — обновить ленту
        self.on_changed = None
        self._build()
        self.load()

    @staticmethod
    def _today():
        return as_naive(get_moscow_time()).date()

    # ------------------------------------------------------------------
    # Фильтры
    # ------------------------------------------------------------------

    def _settings(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db)

    def _filter_key(self):
        # У каждого слоя свой выбор фильтров
        return FILTER_KEY if self.direction == 'tire' else f'{FILTER_KEY}_{self.direction}'

    def _load_filters(self):
        raw = self._settings().get(self._filter_key(), '') or ''
        chosen = {c for c in raw.split(',') if c in categories_of(self.direction)}
        return chosen

    def _save_filters(self):
        self._settings().set(self._filter_key(), ','.join(
            c for c in categories_of(self.direction) if c in self.filters))

    def set_direction(self, direction):
        self.direction = direction
        self.filters = self._load_filters()
        self.load()

    def toggle_filter(self, key):
        if key == 'all':
            self.filters = set()
        elif not self.filters:
            self.filters = {key}
        elif key in self.filters:
            self.filters.discard(key)
        else:
            self.filters.add(key)
        if self.filters == set(categories_of(self.direction)):
            self.filters = set()
        self._save_filters()
        self.load()

    def categories(self):
        return self.filters or None

    # ------------------------------------------------------------------
    # Каркас
    # ------------------------------------------------------------------

    def _build(self):
        card = styles.create_card_frame(self.frame)
        card.pack(fill='both', expand=True, padx=15, pady=15)
        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=16, pady=14)

        top = ttk.Frame(inner, style='White.TFrame')
        top.pack(fill='x')
        self.range_label = styles.create_label(top, '', 'CardHeading.TLabel')
        self.range_label.pack(side='left')
        styles.create_button(top, '+ Задача', self.new_task, 'Primary.TButton').pack(side='right')
        later = styles.create_button(top, '›', lambda: self.shift_week(1), 'Secondary.TButton')
        later.config(width=3)
        later.pack(side='right', padx=(0, 10))
        styles.create_button(top, 'Сегодня', self.go_today,
                             'Secondary.TButton').pack(side='right', padx=(0, 4))
        earlier = styles.create_button(top, '‹', lambda: self.shift_week(-1), 'Secondary.TButton')
        earlier.config(width=3)
        earlier.pack(side='right', padx=(0, 4))

        self.filter_row = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.filter_row.pack(fill='x', pady=(12, 8))

        self.week_row = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.week_row.pack(fill='x')
        for i in range(7):
            self.week_row.columnconfigure(i, weight=1, uniform='day')

        self.day_label = styles.create_label(inner, '', 'CardHeading.TLabel')
        self.day_label.pack(anchor='w', pady=(14, 6))

        holder = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        holder.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(holder, bg=styles.COLORS['bg_card'], highlightthickness=0)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        self.day_list = tk.Frame(self.canvas, bg=styles.COLORS['bg_card'])
        self.day_list.bind('<Configure>', lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox('all')))
        self._list_window = self.canvas.create_window((0, 0), window=self.day_list, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(
            self._list_window, width=e.width))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

    def _chip(self, parent, text, colors, bold=False, **pack):
        fg, bg = colors
        label = tk.Label(parent, text=text, bg=bg, fg=fg, padx=6, pady=1,
                         font=(styles.DEFAULT_FONT, 9, 'bold' if bold else 'normal'))
        label.pack(**pack)
        return label

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------

    def load(self):
        try:
            self._draw_filters()
            self._draw_week()
            self._draw_day()
        except Exception as e:
            self.db.rollback()
            from logger import log
            log.error(f'Календарь не нарисовался: {e}')

    def _draw_filters(self):
        for child in self.filter_row.winfo_children():
            child.destroy()
        for key in categories_of(self.direction) + ['all']:
            on = (not self.filters) if key == 'all' else (not self.filters or key in self.filters)
            fg, bg = CATEGORY_COLORS.get(key, (styles.COLORS['text'], styles.COLORS['bg_subtle']))
            text = 'Все' if key == 'all' else CATEGORY_TITLES[key]
            chip = tk.Label(self.filter_row, text=('● ' if key != 'all' else '') + text,
                            cursor='hand2', padx=12, pady=4,
                            font=(styles.DEFAULT_FONT, 10, 'bold' if on else 'normal'),
                            bg=bg if on else styles.COLORS['bg_card'],
                            fg=fg if on else styles.COLORS['text_secondary'],
                            relief='solid', borderwidth=1)
            chip.pack(side='left', padx=(0, 6))
            chip.bind('<Button-1>', lambda e, k=key: self.toggle_filter(k))

    def _draw_week(self):
        for child in self.week_row.winfo_children():
            child.destroy()
        end = self.week_start + timedelta(days=6)
        if self.week_start.month == end.month:
            self.range_label.config(text=f'{self.week_start.day}–{end.day} {MONTHS[end.month - 1]}')
        else:
            self.range_label.config(text=f'{self.week_start.day} {MONTHS[self.week_start.month - 1]} – '
                                         f'{end.day} {MONTHS[end.month - 1]}')
        week = self.service.week(self.week_start, self.categories(), self.direction)
        today = self._today()
        for i, (day, tasks) in enumerate(week.items()):
            chosen = day == self.selected
            box = tk.Frame(self.week_row, bg=styles.COLORS['primary_soft'] if chosen else styles.COLORS['bg_card'],
                           highlightthickness=2 if chosen else 1,
                           highlightbackground=styles.COLORS['primary'] if chosen else styles.COLORS['border'],
                           cursor='hand2', height=96)
            box.grid(row=0, column=i, sticky='nsew', padx=2)
            box.pack_propagate(False)
            head = tk.Label(box, text=f'{WEEKDAYS[i]} {day.day}', anchor='w',
                            bg=box['bg'], font=(styles.DEFAULT_FONT, 9, 'bold' if day == today else 'normal'),
                            fg=styles.COLORS['primary'] if day == today else styles.COLORS['text_secondary'])
            head.pack(fill='x', padx=4, pady=(3, 1))
            widgets = [box, head]
            for task in tasks[:3]:
                colors = CATEGORY_COLORS.get(task.category, CATEGORY_COLORS['work'])
                if task.done_at:
                    colors = (styles.COLORS['text_secondary'], styles.COLORS['bg_subtle'])
                text = (f'{task.due_time} ' if task.due_time else '') + task.title
                label = tk.Label(box, text=text[:22], anchor='w', bg=colors[1], fg=colors[0],
                                 font=(styles.DEFAULT_FONT, 8))
                label.pack(fill='x', padx=3, pady=1)
                widgets.append(label)
            if len(tasks) > 3:
                more = tk.Label(box, text=f'+{len(tasks) - 3}', anchor='w', bg=box['bg'],
                                fg=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 8))
                more.pack(fill='x', padx=4)
                widgets.append(more)
            for widget in widgets:
                widget.bind('<Button-1>', lambda e, d=day: self.select_day(d))

    def _draw_day(self):
        for child in self.day_list.winfo_children():
            child.destroy()
        self.day_label.config(text=day_title(self.selected))
        rows = []
        if self.selected == self._today():
            rows += [(t, True) for t in self.service.overdue(self.selected, self.categories(), self.direction)]
        rows += [(t, False) for t in self.service.day(self.selected, self.categories(), self.direction)]
        if not rows:
            ttk.Label(self.day_list, text='На этот день задач нет. «+ Задача» — поставить.',
                      font=styles.FONTS['normal'], foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card']).pack(anchor='w', pady=8)
        for task, overdue in rows:
            self._task_row(task, overdue)

    def _task_row(self, task, overdue):
        border = DANGER[0] if overdue else styles.COLORS['border']
        row = tk.Frame(self.day_list, bg=styles.COLORS['bg_card'], highlightthickness=1,
                       highlightbackground=border, cursor='hand2')
        row.pack(fill='x', pady=3)
        done = bool(task.done_at)
        box = tk.Label(row, text='☑' if done else '☐', font=(styles.DEFAULT_FONT, 16),
                       bg=styles.COLORS['bg_card'], cursor='hand2',
                       fg=styles.COLORS['success'] if done else styles.COLORS['text_secondary'])
        box.pack(side='right', padx=10)
        box.bind('<Button-1>', lambda e, t=task: self.toggle_done(t))
        time_text = task.due_time or '—'
        if overdue:
            time_text = f'{task.due_date:%d.%m}'
        tk.Label(row, text=time_text, width=6, anchor='w', bg=styles.COLORS['bg_card'],
                 fg=DANGER[0] if overdue else styles.COLORS['text_secondary'],
                 font=(styles.DEFAULT_FONT, 10)).pack(side='left', padx=(8, 4), pady=6, anchor='n')
        text = tk.Frame(row, bg=styles.COLORS['bg_card'])
        text.pack(side='left', fill='x', expand=True, pady=5)
        line = tk.Frame(text, bg=styles.COLORS['bg_card'])
        line.pack(fill='x')
        self._chip(line, CATEGORY_TITLES.get(task.category, task.category),
                   CATEGORY_COLORS.get(task.category, CATEGORY_COLORS['work']), side='left')
        if overdue:
            self._chip(line, 'просрочено', DANGER, side='left', padx=(4, 0))
        title = tk.Label(line, text=task.title, bg=styles.COLORS['bg_card'], anchor='w',
                         fg=styles.COLORS['text_secondary'] if done else styles.COLORS['text'],
                         font=(styles.DEFAULT_FONT, 10, 'overstrike' if done else 'normal'))
        title.pack(side='left', padx=(6, 0))
        widgets = [row, text, line, title]
        if task.license_plate:
            plate = tk.Label(line, text=task.license_plate, bg=styles.COLORS['bg_card'],
                             fg=styles.COLORS['primary'], cursor='hand2',
                             font=(styles.DEFAULT_FONT, 10, 'underline'))
            plate.pack(side='left', padx=(8, 0))
            plate.bind('<Button-1>', lambda e, p=task.license_plate: self.open_car(p))
        sub = []
        party = self.service.counterparty(task.counterparty_uid)
        if party is not None:
            sub.append(party.name)
        if task.client_name and task.license_plate:
            sub.append(task.client_name)
        if task.note:
            sub.append(task.note.splitlines()[0][:90])
        if task.amount:
            sub.append(f'{task.amount:,.0f} ₽'.replace(',', ' '))
        if done:
            sub.append(f'сделано · {task.done_by or ""} {as_naive(task.done_at):%H:%M}')
        if sub:
            note = tk.Label(text, text=' · '.join(sub), bg=styles.COLORS['bg_card'], anchor='w',
                            fg=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 9))
            note.pack(fill='x')
            widgets.append(note)
        for widget in widgets:
            widget.bind('<Button-1>', lambda e, t=task: self.edit(t))

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def select_day(self, day):
        self.selected = day
        self.load()

    def shift_week(self, weeks):
        self.week_start += timedelta(days=7 * weeks)
        self.selected = self.week_start if not (
            self.week_start <= self._today() < self.week_start + timedelta(days=7)) else self._today()
        self.load()

    def go_today(self):
        today = self._today()
        self.selected = today
        self.week_start = today - timedelta(days=today.weekday())
        self.load()

    def _changed(self):
        self.load()
        if self.on_changed:
            self.on_changed()

    def new_task(self):
        open_task(self.frame, self.db, on_saved=self._changed, due_date=self.selected,
                  category=next(iter(self.filters)) if len(self.filters) == 1 else 'work',
                  direction=self.direction)

    def edit(self, task):
        open_task(self.frame, self.db, task, on_saved=self._changed)

    def toggle_done(self, task):
        try:
            self.service.set_done(task, not task.done_at, by=WHO)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Задача', f'Не удалось отметить: {e}')
            return
        self._changed()

    def open_car(self, plate):
        from ui.car_info import open_car_info
        open_car_info(self.frame, self.db, plate)
