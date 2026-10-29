"""
Раздел «Календарь»: месяц, неделя или день (решение владельца 29.10.2026).

Открывается всегда на месяце: справа — список выбранного дня, двойной
щелчок по дню — день по часам. Неделя и день — сетка по часам работы
точки; записи без времени — полосой «без времени» сверху.

В календаре два вида записей: задача (с галочкой, напоминает, краснеет,
переходит на завтра) и комментарий — просто запись на день.

Фильтры по разделам — чтобы склад, покраска и шины не путались между
собой: Рабочая, Хранение, Шины, Покраска, Комментарии, Все
(docs/calendar.md). Выбор запоминается на этом компьютере.
"""
import tkinter as tk
from datetime import date, timedelta
from tkinter import ttk, messagebox

import styles
from models.calendar import CATEGORY_TITLES, categories_of, KIND_NOTE, KIND_TASK
from services.calendar_service import CalendarService
from ui.task_dialog import open_task, CATEGORY_COLORS, NOTE_COLORS, WHO, time_text
from utils import get_moscow_time, as_naive

FILTER_KEY = 'calendar_filter'
DIRECTION_KEY = 'calendar_direction'
DIRECTION_TITLES = {'all': 'Все', 'tire': 'Шиномонтаж', 'wash': 'Мойка'}
DIRECTION_COLORS = {'tire': ('#1d4ed8', '#dbeafe'), 'wash': ('#0f766e', '#ccfbf1')}
WEEKDAYS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']
WEEKDAYS_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа',
          'сентября', 'октября', 'ноября', 'декабря']
MONTHS_NOM = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август',
              'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
DANGER = ('#b91c1c', '#fee2e2')
WARN = ('#92400e', '#fef3c7')
NOTE = KIND_NOTE
VIEWS = (('month', 'Месяц'), ('week', 'Неделя'), ('day', 'День'))
# В ячейке месяца — столько записей, остальное «ещё N»
MONTH_CELL_ITEMS = 3
SIDE_WIDTH = 400
TIME_COLUMN = 56
# Задача без «до» на сетке — полчаса
DEFAULT_MINUTES = 30


def day_title(day):
    return f'{WEEKDAYS_FULL[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}'


def _minutes(text):
    hours, minutes = (int(p) for p in text.split(':'))
    return hours * 60 + minutes


def _hour(text, fallback):
    try:
        return int(str(text).split(':')[0])
    except (TypeError, ValueError):
        return fallback


def is_note(task):
    return task.kind == KIND_NOTE


class CalendarTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = CalendarService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        today = self._today()
        self.selected = today
        # Открывается всегда на месяце — так решил владелец
        self.view = 'month'
        # Календарь один на шиномонтаж и мойку (решение владельца от
        # 26.10.2026). Фильтр направления: all / tire / wash
        self.direction = self._settings().get(DIRECTION_KEY, 'all') or 'all'
        if self.direction not in ('all', 'tire', 'wash'):
            self.direction = 'all'
        self.filters = self._load_filters()
        # Главное окно ставит сюда «что-то поменялось» — обновить ленту
        self.on_changed = None
        self._grid_items = {}
        # Выделенное время на сетке недели и дня: (день, «с», «до»).
        # «+ Задача» и «+ Комментарий» ставят запись туда
        self.slot = None
        self._cells = {}
        self._tip = None
        self._build()
        self.load()

    @staticmethod
    def _today():
        return as_naive(get_moscow_time()).date()

    @staticmethod
    def _now():
        return as_naive(get_moscow_time())

    # ------------------------------------------------------------------
    # Фильтры
    # ------------------------------------------------------------------

    def _settings(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db)

    def _wash(self):
        from services import directions
        return directions.wash_on(self.db)

    def shown_categories(self):
        """Разделы, которые сейчас можно выбрать: по фильтру направления."""
        if self.direction == 'all':
            found = categories_of('tire') + [c for c in categories_of('wash')
                                             if c not in categories_of('tire')]
            return found if self._wash() else categories_of('tire')
        return categories_of(self.direction)

    def filter_keys(self):
        """Разделы задач и «Комментарии» — всё, что можно отметить в фильтре."""
        return self.shown_categories() + [NOTE]

    def query_direction(self):
        return None if self.direction == 'all' else self.direction

    def _load_filters(self):
        raw = self._settings().get(FILTER_KEY, '') or ''
        return {c for c in raw.split(',') if c in self.filter_keys()}

    def _save_filters(self):
        self._settings().set(FILTER_KEY, ','.join(
            c for c in self.filter_keys() if c in self.filters))

    def set_direction_filter(self, direction):
        self.direction = direction
        self._settings().set(DIRECTION_KEY, direction)
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
        if self.filters == set(self.filter_keys()):
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
        inner.pack(fill='both', expand=True, padx=16, pady=12)
        self.inner = inner

        top = ttk.Frame(inner, style='White.TFrame')
        top.pack(fill='x')
        self.range_label = styles.create_label(top, '', 'CardHeading.TLabel')
        self.range_label.pack(side='left')

        # Месяц / Неделя / День
        views = tk.Frame(top, bg=styles.COLORS['border'], padx=1, pady=1)
        views.pack(side='left', padx=(24, 0))
        self.view_buttons = {}
        for index, (key, title) in enumerate(VIEWS):
            button = tk.Label(views, text=title, padx=16, pady=4, cursor='hand2',
                              font=(styles.DEFAULT_FONT, 10))
            button.pack(side='left', padx=(1 if index else 0, 0))
            button.bind('<Button-1>', lambda e, k=key: self.set_view(k))
            self.view_buttons[key] = button

        styles.create_button(top, '+ Задача', self.new_task, 'Primary.TButton').pack(side='right')
        styles.create_button(top, '+ Комментарий', self.new_note,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        later = styles.create_button(top, '›', lambda: self.shift(1), 'Secondary.TButton')
        later.config(width=3)
        later.pack(side='right', padx=(0, 14))
        styles.create_button(top, 'Сегодня', self.go_today,
                             'Secondary.TButton').pack(side='right', padx=(0, 4))
        earlier = styles.create_button(top, '‹', lambda: self.shift(-1), 'Secondary.TButton')
        earlier.config(width=3)
        earlier.pack(side='right', padx=(0, 4))

        # Направление — только когда мойка включена
        self.direction_row = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.direction_row.pack(fill='x', pady=(10, 0))
        self.filter_row = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.filter_row.pack(fill='x', pady=(8, 8))

        self.body = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.body.pack(fill='both', expand=True)

    def _chip(self, parent, text, colors, bold=False, **pack):
        fg, bg = colors
        label = tk.Label(parent, text=text, bg=bg, fg=fg, padx=6, pady=1,
                         font=(styles.DEFAULT_FONT, 9, 'bold' if bold else 'normal'))
        label.pack(**pack)
        return label

    def _scroll_list(self, parent):
        """Список с прокруткой — для дня справа в месяце."""
        holder = tk.Frame(parent, bg=styles.COLORS['bg_card'])
        holder.pack(fill='both', expand=True)
        canvas = tk.Canvas(holder, bg=styles.COLORS['bg_card'], highlightthickness=0)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
        inside = tk.Frame(canvas, bg=styles.COLORS['bg_card'])
        inside.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        window = canvas.create_window((0, 0), window=inside, anchor='nw')
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return inside

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------

    def load(self):
        self._hide_tip()
        try:
            self._draw_views()
            self._draw_filters()
            for child in self.body.winfo_children():
                child.destroy()
            {'month': self._draw_month, 'week': self._draw_week,
             'day': self._draw_day}[self.view]()
        except Exception as e:
            self.db.rollback()
            from logger import log
            log.error(f'Календарь не нарисовался: {e}')

    def _draw_views(self):
        for key, button in self.view_buttons.items():
            on = key == self.view
            button.config(bg=styles.COLORS['primary'] if on else styles.COLORS['bg_card'],
                          fg='white' if on else styles.COLORS['text_secondary'],
                          font=(styles.DEFAULT_FONT, 10, 'bold' if on else 'normal'))

    def _draw_filters(self):
        for child in self.direction_row.winfo_children():
            child.destroy()
        for child in self.filter_row.winfo_children():
            child.destroy()
        wash = self._wash()
        if wash:
            if not self.direction_row.winfo_manager():
                self.direction_row.pack(fill='x', pady=(10, 0), before=self.filter_row)
            tk.Label(self.direction_row, text='Направление:', bg=styles.COLORS['bg_card'],
                     fg=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 9)).pack(side='left', padx=(0, 6))
            for key in ('all', 'tire', 'wash'):
                on = key == self.direction
                fg, bg = DIRECTION_COLORS.get(key, (styles.COLORS['text'], styles.COLORS['bg_subtle']))
                chip = tk.Label(self.direction_row, text=DIRECTION_TITLES[key], cursor='hand2',
                                padx=12, pady=3, relief='solid', borderwidth=1,
                                font=(styles.DEFAULT_FONT, 10, 'bold' if on else 'normal'),
                                bg=bg if on else styles.COLORS['bg_card'],
                                fg=fg if on else styles.COLORS['text_secondary'])
                chip.pack(side='left', padx=(0, 6))
                chip.bind('<Button-1>', lambda e, k=key: self.set_direction_filter(k))
            tk.Label(self.filter_row, text='Разделы:', bg=styles.COLORS['bg_card'],
                     fg=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 9)).pack(side='left', padx=(0, 6))
        else:
            self.direction_row.pack_forget()
        for key in self.filter_keys() + ['all']:
            on = (not self.filters) if key == 'all' else (not self.filters or key in self.filters)
            if key == 'all':
                text, (fg, bg) = 'Все', (styles.COLORS['text'], styles.COLORS['bg_subtle'])
            elif key == NOTE:
                text, (fg, bg) = '✎ Комментарии', NOTE_COLORS
            else:
                text, (fg, bg) = '● ' + CATEGORY_TITLES[key], CATEGORY_COLORS[key]
            chip = tk.Label(self.filter_row, text=text, cursor='hand2', padx=12, pady=4,
                            font=(styles.DEFAULT_FONT, 10, 'bold' if on else 'normal'),
                            bg=bg if on else styles.COLORS['bg_card'],
                            fg=fg if on else styles.COLORS['text_secondary'],
                            relief='solid', borderwidth=1)
            chip.pack(side='left', padx=(0, 6))
            chip.bind('<Button-1>', lambda e, k=key: self.toggle_filter(k))

    def _late(self, task):
        """Неотмеченная задача прошлого дня — красная."""
        return not is_note(task) and not task.done_at and task.due_date < self._today()

    def _colors(self, task):
        if is_note(task):
            return NOTE_COLORS
        if task.done_at:
            return styles.COLORS['text_secondary'], styles.COLORS['bg_subtle']
        if self._late(task):
            return DANGER
        return CATEGORY_COLORS.get(task.category, CATEGORY_COLORS['work'])

    def _short(self, task):
        if is_note(task):
            return '✎ ' + task.title
        return (f'{task.due_time} ' if task.due_time else '') + task.title

    # ------------------------------------------------------------------
    # Месяц
    # ------------------------------------------------------------------

    def _month_start(self):
        first = self.selected.replace(day=1)
        return first - timedelta(days=first.weekday())

    def _draw_month(self):
        first = self.selected.replace(day=1)
        self.range_label.config(text=f'{MONTHS_NOM[first.month - 1]} {first.year}')
        start = self._month_start()
        next_month = (first + timedelta(days=32)).replace(day=1)
        weeks = ((next_month - start).days + 6) // 7
        found = self.service.days(start, weeks * 7, self.categories(), self.query_direction())
        today = self._today()

        side = tk.Frame(self.body, bg=styles.COLORS['bg_card'], width=SIDE_WIDTH)
        side.pack(side='right', fill='y', padx=(14, 0))
        side.pack_propagate(False)
        self._side = side
        self._cells = {}
        self._draw_day_list(side, self.selected)

        grid = tk.Frame(self.body, bg=styles.COLORS['bg_card'])
        grid.pack(side='left', fill='both', expand=True)
        for i in range(7):
            grid.columnconfigure(i, weight=1, uniform='day')
            tk.Label(grid, text=WEEKDAYS[i], bg=styles.COLORS['bg_card'], anchor='w',
                     fg=styles.COLORS['text_secondary'],
                     font=(styles.DEFAULT_FONT, 9)).grid(row=0, column=i, sticky='w', padx=4)
        for week in range(weeks):
            grid.rowconfigure(week + 1, weight=1, uniform='week')
            for i in range(7):
                day = start + timedelta(days=week * 7 + i)
                self._month_cell(grid, week + 1, i, day, found.get(day, []), first, today)

    def _month_cell(self, grid, row, column, day, tasks, first, today):
        chosen = day == self.selected
        box = tk.Frame(grid, bg=styles.COLORS['primary_soft'] if chosen else styles.COLORS['bg_card'],
                       highlightthickness=2 if chosen else 1, cursor='hand2',
                       highlightbackground=styles.COLORS['primary'] if chosen else styles.COLORS['border'])
        box.grid(row=row, column=column, sticky='nsew', padx=1, pady=1)
        box.pack_propagate(False)
        other = day.month != first.month
        head = tk.Label(box, text=str(day.day), anchor='w', bg=box['bg'],
                        font=(styles.DEFAULT_FONT, 9, 'bold' if day == today else 'normal'),
                        fg=(styles.COLORS['primary'] if day == today
                            else '#cbd5e1' if other else styles.COLORS['text_secondary']))
        head.pack(fill='x', padx=4, pady=(2, 1))
        empty = [box, head]
        for task in tasks[:MONTH_CELL_ITEMS]:
            fg, bg = self._colors(task)
            style = 'italic' if is_note(task) else ('overstrike' if task.done_at else 'normal')
            label = tk.Label(box, text=self._short(task), anchor='w', bg=bg, fg=fg,
                             font=(styles.DEFAULT_FONT, 8, style))
            label.pack(fill='x', padx=3, pady=1)
            # Щелчок по записи — сразу её окно, наведение — полный текст
            label.bind('<Button-1>', lambda e, t=task: self.edit(t))
            self._hover(label, task)
        more = None
        if len(tasks) > MONTH_CELL_ITEMS:
            more = tk.Label(box, text=f'ещё {len(tasks) - MONTH_CELL_ITEMS}', anchor='w',
                            bg=box['bg'], fg=styles.COLORS['text_secondary'],
                            font=(styles.DEFAULT_FONT, 8))
            more.pack(fill='x', padx=4)
            empty.append(more)
        # Пустое место: щелчок — выделить день, двойной — что поставить
        for widget in empty:
            widget.bind('<Button-1>', lambda e, d=day: self.select_day(d))
            widget.bind('<Double-1>', lambda e, d=day: self._choose(e, due_date=d))
        self._cells[day] = (box, [w for w in (head, more) if w is not None])

    def _draw_day_list(self, parent, day):
        styles.create_label(parent, day_title(day), 'CardHeading.TLabel').pack(anchor='w', pady=(0, 6))
        holder = self._scroll_list(parent)
        rows = []
        if day == self._today():
            rows += [(t, True) for t in self.service.overdue(day, self.categories(),
                                                             self.query_direction())]
        rows += [(t, self._late(t)) for t in self.service.day(day, self.categories(),
                                                              self.query_direction())]
        if not rows:
            ttk.Label(holder, text='На этот день записей нет.\n«+ Задача» или «+ Комментарий».',
                      font=styles.FONTS['normal'], foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card'], justify='left').pack(anchor='w', pady=8)
        for task, overdue in rows:
            self._task_row(holder, task, overdue)
        ttk.Label(parent, text='Щелчок по записи — открыть. Двойной щелчок по пустому месту '
                               'дня — задача или комментарий.', font=styles.FONTS['small'], wraplength=380,
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w', pady=(6, 0))

    def _task_row(self, parent, task, overdue):
        note = is_note(task)
        bg = NOTE_COLORS[1] if note else styles.COLORS['bg_card']
        border = DANGER[0] if overdue else styles.COLORS['border']
        row = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=border,
                       cursor='hand2')
        row.pack(fill='x', pady=3)
        done = bool(task.done_at)
        if not note:
            box = tk.Label(row, text='☑' if done else '☐', font=(styles.DEFAULT_FONT, 15),
                           bg=bg, cursor='hand2',
                           fg=styles.COLORS['success'] if done else styles.COLORS['text_secondary'])
            box.pack(side='right', padx=8)
            box.bind('<Button-1>', lambda e, t=task: self.toggle_done(t))
        when = time_text(task) or ('' if note else '—')
        if overdue and task.due_date != self.selected:
            when = f'{task.due_date:%d.%m}'
        tk.Label(row, text=when, width=11, anchor='w', bg=bg,
                 fg=DANGER[0] if overdue else styles.COLORS['text_secondary'],
                 font=(styles.DEFAULT_FONT, 9)).pack(side='left', padx=(8, 2), pady=6, anchor='n')
        text = tk.Frame(row, bg=bg)
        text.pack(side='left', fill='x', expand=True, pady=5)
        line = tk.Frame(text, bg=bg)
        line.pack(fill='x')
        widgets = [row, text, line]
        # Метка направления — когда мойка включена: календарь общий
        if self._wash():
            direction = task.direction or 'tire'
            widgets.append(self._chip(line, DIRECTION_TITLES[direction].upper(),
                                      DIRECTION_COLORS[direction], bold=True,
                                      side='left', padx=(0, 4)))
        if note:
            widgets.append(self._chip(line, 'комментарий', ('#475569', '#e2e8f0'), side='left'))
        else:
            widgets.append(self._chip(line, CATEGORY_TITLES.get(task.category, task.category),
                                      CATEGORY_COLORS.get(task.category, CATEGORY_COLORS['work']),
                                      side='left'))
        if overdue:
            widgets.append(self._chip(line, 'просрочено', DANGER, side='left', padx=(4, 0)))
        body = (task.note or task.title) if note else task.title
        title = tk.Label(text, text=body, bg=bg, anchor='w', justify='left', wraplength=250,
                         fg=styles.COLORS['text_secondary'] if done else styles.COLORS['text'],
                         font=(styles.DEFAULT_FONT, 10,
                               'italic' if note else 'overstrike' if done else 'normal'))
        title.pack(fill='x', pady=(2, 0))
        widgets.append(title)
        if task.license_plate:
            plate = tk.Label(text, text=task.license_plate, bg=bg, anchor='w',
                             fg=styles.COLORS['primary'], cursor='hand2',
                             font=(styles.DEFAULT_FONT, 9, 'underline'))
            plate.pack(fill='x')
            plate.bind('<Button-1>', lambda e, p=task.license_plate: self.open_car(p))
        sub = []
        if not note:
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
            more = tk.Label(text, text=' · '.join(sub), bg=bg, anchor='w', justify='left',
                            wraplength=250, fg=styles.COLORS['text_secondary'],
                            font=(styles.DEFAULT_FONT, 9))
            more.pack(fill='x')
            widgets.append(more)
        for widget in widgets:
            widget.bind('<Button-1>', lambda e, t=task: self.edit(t))

    # ------------------------------------------------------------------
    # Неделя и день — по часам
    # ------------------------------------------------------------------

    def _hours(self, tasks):
        """Сетка — по часам работы точки, но так, чтобы влезли все записи."""
        settings = self._settings()
        start = _hour(settings.get('booking_opens_at', '09:00'), 9)
        end = _hour(settings.get('booking_closes_at', '21:00'), 21)
        if end <= start:
            start, end = 9, 21
        for task in tasks:
            if task.due_time:
                start = min(start, _minutes(task.due_time) // 60)
                last = _minutes(task.end_time) if task.end_time else _minutes(task.due_time) + DEFAULT_MINUTES
                end = max(end, -(-last // 60))
        return start, min(end, 24)

    def _draw_week(self):
        start = self.selected - timedelta(days=self.selected.weekday())
        end = start + timedelta(days=6)
        if start.month == end.month:
            self.range_label.config(text=f'{start.day}–{end.day} {MONTHS[end.month - 1]}')
        else:
            self.range_label.config(text=f'{start.day} {MONTHS[start.month - 1]} – '
                                         f'{end.day} {MONTHS[end.month - 1]}')
        found = self.service.days(start, 7, self.categories(), self.query_direction())
        self._draw_hours(list(found), found)

    def _draw_day(self):
        """
        День по часам — тремя колонками: вчера, выбранный день (шире) и
        завтра. Соседние дни видно всегда (решение владельца 29.10.2026).
        """
        self.range_label.config(text=day_title(self.selected))
        start = self.selected - timedelta(days=1)
        found = self.service.days(start, 3, self.categories(), self.query_direction())
        if self.selected == self._today():
            # Просроченные прошлых дней — в полосу «без времени»: их нельзя потерять
            found[self.selected] = self.service.overdue(
                self.selected, self.categories(), self.query_direction()) + found[self.selected]
        self._draw_hours(list(found), found)

    def _weights(self, days):
        """Ширина колонок: в «Дне» выбранный день вдвое шире соседних."""
        if self.view == 'day':
            return [2 if day == self.selected else 1 for day in days]
        return [1] * len(days)

    def _draw_hours(self, days, found):
        today = self._today()
        weights = self._weights(days)
        if len(days) > 1:
            heads = tk.Frame(self.body, bg=styles.COLORS['bg_card'])
            heads.pack(fill='x')
            tk.Frame(heads, bg=styles.COLORS['bg_card'], width=TIME_COLUMN).pack(side='left')
            columns = tk.Frame(heads, bg=styles.COLORS['bg_card'])
            columns.pack(side='left', fill='x', expand=True)
            for i, day in enumerate(days):
                columns.columnconfigure(i, weight=weights[i], uniform='day')
                on = day == today
                main = self.view == 'day' and day == self.selected
                text = (day_title(day) if main
                        else f'{WEEKDAYS[day.weekday()]} {day.day}')
                head = tk.Label(columns, text=text, cursor='hand2',
                                bg=styles.COLORS['bg_card'],
                                fg=styles.COLORS['primary'] if on or main else styles.COLORS['text_secondary'],
                                font=(styles.DEFAULT_FONT, 10, 'bold' if on or main else 'normal'))
                head.grid(row=0, column=i, pady=(0, 4))
                head.bind('<Button-1>', lambda e, d=day: self.open_day(d))
                if self.view == 'day' and day != self.selected:
                    head.config(text=f'‹ {head.cget("text")}' if day < self.selected
                                else f'{head.cget("text")} ›')

        # Без времени — полосой сверху
        band = tk.Frame(self.body, bg=styles.COLORS['bg_card'])
        band.pack(fill='x', pady=(0, 4))
        left = tk.Frame(band, bg=styles.COLORS['bg_card'], width=TIME_COLUMN)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        tk.Label(left, text='без\nвремени', bg=styles.COLORS['bg_card'], justify='right',
                 fg=styles.COLORS['text_secondary'],
                 font=(styles.DEFAULT_FONT, 8)).pack(anchor='ne', padx=(0, 6))
        cells = tk.Frame(band, bg=styles.COLORS['bg_card'])
        cells.pack(side='left', fill='x', expand=True)
        for i, day in enumerate(days):
            cells.columnconfigure(i, weight=weights[i], uniform='day')
            cell = tk.Frame(cells, bg=styles.COLORS['bg_card'], highlightthickness=1,
                            highlightbackground=styles.COLORS['border'])
            cell.grid(row=0, column=i, sticky='nsew')
            loose = [t for t in found.get(day, []) if not t.due_time or t.due_date != day]
            for task in loose:
                fg, bg = self._colors(task)
                text = self._short(task)
                if task.due_date != day:
                    text = f'{task.due_date:%d.%m} {text}'
                label = tk.Label(cell, text=text, anchor='w', bg=bg, fg=fg, cursor='hand2',
                                 font=(styles.DEFAULT_FONT, 8 if len(days) > 1 else 9,
                                       'italic' if is_note(task)
                                       else 'overstrike' if task.done_at else 'normal'))
                label.pack(fill='x', padx=2, pady=1)
                label.bind('<Button-1>', lambda e, t=task: self.edit(t))
                self._hover(label, task)
            if not loose:
                tk.Label(cell, text=' ', bg=styles.COLORS['bg_card'],
                         font=(styles.DEFAULT_FONT, 8)).pack()

        timed = {day: [t for t in found.get(day, []) if t.due_time and t.due_date == day]
                 for day in days}
        hours = self._hours([t for rows in timed.values() for t in rows])
        canvas = tk.Canvas(self.body, bg=styles.COLORS['bg_card'], highlightthickness=0)
        canvas.pack(fill='both', expand=True)
        if self.slot is not None and self.slot[0] not in days:
            self.slot = None
        self._repaint = lambda: self._paint_hours(canvas, days, timed, hours)
        canvas.bind('<Configure>', lambda e: self._repaint())
        canvas.bind('<Button-1>', lambda e: self._pick_slot(canvas, e, days, hours))
        canvas.bind('<Double-1>', lambda e: self._new_at(canvas, e, days, hours))
        canvas.bind('<Leave>', lambda e: self._hide_tip())
        ttk.Label(self.body, text='Щелчок по свободному времени — выделить его, двойной — задача '
                                  'или комментарий. Щелчок по записи — открыть, наведение — '
                                  'полный текст.',
                  font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w', pady=(4, 0))

    def _geometry(self, canvas, days, hours):
        """Ширина, высота, высота часа и края колонок дней (их на одну больше, чем дней)."""
        width, height = canvas.winfo_width(), canvas.winfo_height()
        step = (height - 4) / max(hours[1] - hours[0], 1)
        weights = self._weights(days)
        unit = (width - TIME_COLUMN) / sum(weights)
        edges = [TIME_COLUMN]
        for weight in weights:
            edges.append(edges[-1] + weight * unit)
        return width, height, step, edges

    def _paint_hours(self, canvas, days, timed, hours):
        canvas.delete('all')
        width, height, step, edges = self._geometry(canvas, days, hours)
        first = hours[0]
        today = self._today()
        if today in days:
            i = days.index(today)
            canvas.create_rectangle(edges[i] + 1, 0, edges[i + 1] - 1, height,
                                    fill='#f8fbff', outline='')
        for n in range(hours[1] - first + 1):
            y = 2 + n * step
            canvas.create_line(TIME_COLUMN, y, width, y, fill=styles.COLORS['border'])
            if n < hours[1] - first:
                canvas.create_text(TIME_COLUMN - 8, y + 2, text=f'{first + n}:00', anchor='ne',
                                   fill=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 9))
        for x in edges:
            canvas.create_line(x, 0, x, height, fill=styles.COLORS['border'])

        def y_of(minutes):
            return 2 + (minutes / 60 - first) * step

        self._grid_items = {}
        for i, day in enumerate(days):
            for task, lane, lanes in self._lanes(timed.get(day, [])):
                start = _minutes(task.due_time)
                end = _minutes(task.end_time) if task.end_time else start + DEFAULT_MINUTES
                top, bottom = y_of(start), max(y_of(end), y_of(start) + 18)
                lane_width = (edges[i + 1] - edges[i] - 6) / lanes
                x0 = edges[i] + 3 + lane * lane_width
                x1 = x0 + lane_width - 2
                fg, bg = self._colors(task)
                tag = f'task{task.id}'
                canvas.create_rectangle(x0, top + 1, x1, bottom - 1, fill=bg, outline='', tags=tag)
                canvas.create_rectangle(x0, top + 1, x0 + 3, bottom - 1, fill=fg, outline='', tags=tag)
                if is_note(task):
                    text = f'{time_text(task)}  ✎ {task.title}'
                    font = (styles.DEFAULT_FONT, 9, 'italic')
                else:
                    text = f'{time_text(task)}  {task.title}'
                    font = (styles.DEFAULT_FONT, 10 if self._weights(days)[i] > 1 else 9,
                            'overstrike' if task.done_at else 'normal')
                canvas.create_text(x0 + 8, top + 3, text=text, anchor='nw', fill=fg, font=font,
                                   width=max(x1 - x0 - 12, 20), tags=tag)
                if task.license_plate and bottom - top > 34:
                    canvas.create_text(x0 + 8, top + 20, text=task.license_plate, anchor='nw',
                                       fill=styles.COLORS['primary'],
                                       font=(styles.DEFAULT_FONT, 9, 'underline'), tags=tag)
                canvas.tag_bind(tag, '<Button-1>', lambda e, t=task: self.edit(t))
                canvas.tag_bind(tag, '<Enter>', lambda e, t=task: (
                    canvas.config(cursor='hand2'), self._show_tip(e, t)))
                canvas.tag_bind(tag, '<Leave>', lambda e: (canvas.config(cursor=''),
                                                           self._hide_tip()))
                self._grid_items[tag] = task

        # Выделенное время — рамкой, под записями
        if self.slot is not None and self.slot[0] in days:
            i = days.index(self.slot[0])
            start = _minutes(self.slot[1])
            end = _minutes(self.slot[2]) if self.slot[2] else 24 * 60
            canvas.create_rectangle(edges[i] + 2, y_of(start) + 1,
                                    edges[i + 1] - 2, y_of(end) - 1,
                                    fill=styles.COLORS['primary_soft'],
                                    outline=styles.COLORS['primary'], width=2, tags='slot')
            canvas.tag_lower('slot')
            canvas.tag_raise('slot', 'all')
            for tag in self._grid_items:
                canvas.tag_raise(tag)

        # Красная линия — сейчас
        if today in days:
            now = self._now()
            minutes = now.hour * 60 + now.minute
            if first * 60 <= minutes <= hours[1] * 60:
                i = days.index(today)
                y = y_of(minutes)
                x0, x1 = edges[i], edges[i + 1]
                canvas.create_line(x0, y, x1, y, fill='#dc2626', width=2)
                canvas.create_oval(x0 - 4, y - 4, x0 + 4, y + 4, fill='#dc2626', outline='')

    @staticmethod
    def _lanes(tasks):
        """
        Записи, идущие одновременно, — рядом, а не друг на друге.
        Возвращает [(запись, дорожка, сколько дорожек в её группе)].
        """
        items = sorted(tasks, key=lambda t: _minutes(t.due_time))
        result, group, ends, group_end = [], [], [], -1

        def flush():
            lanes = max((lane for _t, lane in group), default=-1) + 1
            result.extend((task, lane, lanes) for task, lane in group)

        for task in items:
            start = _minutes(task.due_time)
            end = _minutes(task.end_time) if task.end_time else start + DEFAULT_MINUTES
            if group and start >= group_end:
                flush()
                group, ends = [], []
            lane = next((n for n, last in enumerate(ends) if last <= start), len(ends))
            if lane == len(ends):
                ends.append(end)
            else:
                ends[lane] = end
            group.append((task, lane))
            group_end = max(group_end, end) if group[:-1] else end
        if group:
            flush()
        return result

    def _slot_at(self, canvas, event, days, hours):
        """Какое время под мышью: (день, «с», «до») по получасам, на час. Запись — None."""
        if canvas.find_withtag('current') and any(
                tag.startswith('task') for tag in canvas.gettags('current')):
            return None
        width, height, step, edges = self._geometry(canvas, days, hours)
        if event.x < TIME_COLUMN:
            return None
        index = next((i for i in range(len(days)) if event.x < edges[i + 1]), len(days) - 1)
        minutes = int(((event.y - 2) / step + hours[0]) * 60)
        minutes = max(0, min(minutes - minutes % 30, 23 * 60 + 30))
        start = f'{minutes // 60:02d}:{minutes % 60:02d}'
        end_minutes = minutes + 60
        end = f'{end_minutes // 60:02d}:{end_minutes % 60:02d}' if end_minutes < 24 * 60 else None
        return days[index], start, end

    def _pick_slot(self, canvas, event, days, hours):
        """
        Щелчок по свободному времени — выделить его. «+ Задача» и
        «+ Комментарий» поставят запись на это время (решение владельца
        29.10.2026). Сетку не перестраиваем — только рамку, иначе двойной
        щелчок не дошёл бы до своего окна.
        """
        slot = self._slot_at(canvas, event, days, hours)
        if slot is None:
            return
        self.slot = slot
        self.selected = slot[0]
        self._repaint()

    def _new_at(self, canvas, event, days, hours):
        """Двойной щелчок по свободному времени — окошко: задача или комментарий."""
        slot = self._slot_at(canvas, event, days, hours)
        if slot is None:
            return
        self._choose(event, due_date=slot[0], due_time=slot[1], end_time=slot[2])

    def _choose(self, event, **when):
        """
        Окошко «что поставить»: задача (уйдёт в Telegram) или комментарий
        (просто запись). Открывается двойным щелчком по пустому месту.
        """
        title = day_title(when['due_date']) + (f' · {when["due_time"]}' if when.get('due_time') else '')
        menu = tk.Menu(self.frame, tearoff=0, font=(styles.DEFAULT_FONT, 11))
        menu.add_command(label=title, state='disabled')
        menu.add_separator()
        menu.add_command(label='Задача — уйдёт в Telegram',
                         command=lambda: self._open_new(KIND_TASK, **when))
        menu.add_command(label='Комментарий — просто запись',
                         command=lambda: self._open_new(KIND_NOTE, **when))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def set_view(self, view):
        self.view = view
        self.load()

    def select_day(self, day):
        """
        Выделить день. В месяце сетку не перестраиваем — только рамку и
        список справа: иначе двойной щелчок по дню не дошёл бы до окошка
        выбора (вторым щелчком жали бы уже по новой клетке).
        """
        previous, self.selected = self.selected, day
        if self.view != 'month' or day not in self._cells or previous not in self._cells:
            self.load()
            return
        for one, chosen in ((previous, False), (day, True)):
            box, labels = self._cells[one]
            bg = styles.COLORS['primary_soft'] if chosen else styles.COLORS['bg_card']
            box.config(bg=bg, highlightthickness=2 if chosen else 1,
                       highlightbackground=styles.COLORS['primary'] if chosen else styles.COLORS['border'])
            for label in labels:
                label.config(bg=bg)
        for child in self._side.winfo_children():
            child.destroy()
        self._draw_day_list(self._side, day)

    def open_day(self, day):
        self.selected = day
        self.view = 'day'
        self.load()

    def shift(self, step):
        """‹ › — на месяц, неделю или день, смотря что открыто."""
        if self.view == 'month':
            first = self.selected.replace(day=1)
            month = first.month - 1 + step
            target = date(first.year + month // 12, month % 12 + 1, 1)
            today = self._today()
            self.selected = today if (today.year, today.month) == (target.year, target.month) else target
        elif self.view == 'week':
            self.selected += timedelta(days=7 * step)
        else:
            self.selected += timedelta(days=step)
        self.load()

    def go_today(self):
        self.selected = self._today()
        self.load()

    def _changed(self):
        self.load()
        if self.on_changed:
            self.on_changed()

    def _open_new(self, kind, **defaults):
        # В неделе и дне выделили время — запись туда
        if not defaults and self.view != 'month' and self.slot is not None:
            defaults = dict(due_date=self.slot[0], due_time=self.slot[1], end_time=self.slot[2])
        sections = [c for c in self.filters if c != NOTE]
        open_task(self.frame, self.db, on_saved=self._changed, kind=kind,
                  category=sections[0] if len(sections) == 1 else 'work',
                  direction=self.query_direction() if self._wash() else 'tire',
                  **{'due_date': self.selected, **defaults})

    def new_task(self):
        self._open_new(KIND_TASK)

    def new_note(self):
        self._open_new(KIND_NOTE)

    def edit(self, task):
        self._hide_tip()
        open_task(self.frame, self.db, task, on_saved=self._changed)

    def toggle_done(self, task):
        try:
            self.service.set_done(task, not task.done_at, by=WHO)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Задача', f'Не удалось отметить: {e}')
            return
        self._changed()

    # ------------------------------------------------------------------
    # Подсказка при наведении: полный текст записи без открытия окна
    # ------------------------------------------------------------------

    def _hover(self, widget, task):
        widget.bind('<Enter>', lambda e, t=task: self._show_tip(e, t), add='+')
        widget.bind('<Leave>', lambda e: self._hide_tip(), add='+')
        widget.config(cursor='hand2')

    def _tip_text(self, task):
        lines = [task.note or task.title if is_note(task) else task.title]
        lines.append(time_text(task) or 'без времени')
        lines.append('комментарий' if is_note(task)
                     else CATEGORY_TITLES.get(task.category, task.category))
        if not is_note(task):
            if task.license_plate:
                lines.append(task.license_plate + (f' · {task.client_name}' if task.client_name else ''))
            party = self.service.counterparty(task.counterparty_uid)
            if party is not None:
                lines.append(party.name)
            if task.note:
                lines.append(task.note[:300])
            if task.amount:
                lines.append(f'{task.amount:,.0f} ₽'.replace(',', ' '))
            if task.done_at:
                lines.append(f'сделано · {task.done_by or ""}')
        return lines

    def _show_tip(self, event, task):
        self._hide_tip()
        try:
            lines = self._tip_text(task)
        except Exception:
            self.db.rollback()
            return
        tip = tk.Toplevel(self.frame)
        tip.overrideredirect(True)
        tip.attributes('-topmost', True)
        body = tk.Frame(tip, bg=styles.COLORS['text'], padx=10, pady=7)
        body.pack()
        tk.Label(body, text=lines[0], bg=styles.COLORS['text'], fg='white', justify='left',
                 wraplength=300, font=(styles.DEFAULT_FONT, 10, 'bold')).pack(anchor='w')
        tk.Label(body, text='\n'.join(lines[1:]), bg=styles.COLORS['text'], fg='#cbd5e1',
                 justify='left', wraplength=300, font=(styles.DEFAULT_FONT, 9)).pack(anchor='w')
        tip.update_idletasks()
        x = min(event.x_root + 14, tip.winfo_screenwidth() - tip.winfo_reqwidth() - 8)
        y = min(event.y_root + 16, tip.winfo_screenheight() - tip.winfo_reqheight() - 8)
        tip.geometry(f'+{max(x, 0)}+{max(y, 0)}')
        self._tip = tip

    def _hide_tip(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None

    def open_car(self, plate):
        from ui.car_info import open_car_info
        open_car_info(self.frame, self.db, plate)
