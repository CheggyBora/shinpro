"""
Раздел «Запись»: предварительная запись клиентов на обслуживание.

День показан лентой времени сверху вниз — от 00:00 до 24:00, колонка
на каждый открытый пост. Запись висит карточкой на своём месте, и на
ней только номер машины: приёмщику при взгляде на экран нужен именно
он. Подробности открываются щелчком.

Сколько постов открыто под запись, решает приёмщик — здесь же, на
экране: от одного до трёх, на день, на неделю или на две недели вперёд.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date, timedelta

from tkcalendar import DateEntry

from models import Appointment
from services.booking_gateway import get_booking, MIN_POSTS, MAX_POSTS
from utils import get_moscow_time
from logger import log
import styles
from ui.appointment_dialogs import AppointmentDialog, AppointmentDetailsDialog

# Высота часа в ленте. 52 пикселя — получасовая запись остаётся
# читаемой, а рабочий день целиком помещается на экран без прокрутки
HOUR_HEIGHT = 52

# Ширина полосы со временем слева
GUTTER = 62

# Карточка не может быть тоньше этого, даже если запись на 15 минут:
# иначе номер машины на ней не прочитать
MIN_CARD_HEIGHT = 26

# С какого часа показываем ленту при открытии дня. Ночью записей
# не бывает, но время до 24:00 всё равно доступно прокруткой
DEFAULT_SCROLL_HOUR = 8

# Цвета карточек по состоянию записи
CARD_COLORS = {
    Appointment.STATUS_SCHEDULED: ('#dbeafe', '#2563eb', '#1e3a8a'),
    Appointment.STATUS_ARRIVED: ('#dcfce7', '#16a34a', '#14532d'),
    Appointment.STATUS_CANCELLED: ('#f1f5f9', '#cbd5e1', '#94a3b8'),
    Appointment.STATUS_NO_SHOW: ('#fee2e2', '#dc2626', '#7f1d1d'),
}

# Насколько дней вперёд раздаём посты одним нажатием
APPLY_SCOPES = [
    ('этот день', 1),
    ('неделю', 7),
    ('2 недели', 14),
]

# Отдельное значение переключателя: срок задаётся числом рядом
CUSTOM_SCOPE = 0
MAX_SCOPE_DAYS = 90


def plural_posts(count):
    """«1 пост», «2 поста», «5 постов» — иначе надпись читается как заглушка."""
    if 11 <= count % 100 <= 14:
        return 'постов'
    last = count % 10
    if last == 1:
        return 'пост'
    if last in (2, 3, 4):
        return 'поста'
    return 'постов'


class AppointmentsTab:
    def __init__(self, parent, db, orders_tab=None):
        self.db = db
        self.booking = get_booking(db)
        self.orders_tab = orders_tab
        self.frame = ttk.Frame(parent, style='BG.TFrame')

        self.current_day = get_moscow_time().date()
        self.scope_days = tk.IntVar(value=1)
        self.selected_posts = None
        self._applied_message = None
        self._cards = {}
        self.day_state = {'placed': [], 'posts': 1, 'online': True,
                          'fetched_at': None, 'reason': None}
        self._scrolled_once = False

        self._build_toolbar()
        self._build_timeline()

        self.load_day()

    # ------------------------------------------------------------------
    # Каркас
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        card = styles.create_card_frame(self.frame)
        card.pack(fill='x', padx=15, pady=(15, 8))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='x', padx=16, pady=12)

        # --- Первая строка: день и кнопка записи ------------------------
        top = ttk.Frame(inner, style='White.TFrame')
        top.pack(fill='x')

        styles.create_button(top, "◀", lambda: self.shift_day(-1),
                             'Secondary.TButton').pack(side='left')

        self.day_label = ttk.Label(top, text="", font=(styles.DEFAULT_FONT, 13, 'bold'),
                                   background=styles.COLORS['bg_card'],
                                   foreground=styles.COLORS['text'], width=26,
                                   anchor='center')
        self.day_label.pack(side='left', padx=6)

        styles.create_button(top, "▶", lambda: self.shift_day(1),
                             'Secondary.TButton').pack(side='left')

        styles.create_button(top, "Сегодня", self.go_today,
                             'Secondary.TButton').pack(side='left', padx=(14, 6))

        self.date_picker = DateEntry(top, width=12, locale='ru_RU',
                                     date_pattern='dd.mm.yyyy',
                                     font=styles.FONTS['normal'])
        self.date_picker.pack(side='left')
        self.date_picker.bind('<<DateEntrySelected>>', self.on_date_picked)

        self.book_button = styles.create_button(
            top, "Записать клиента", self.create_appointment, 'Primary.TButton')
        self.book_button.pack(side='right')

        # --- Посты -------------------------------------------------------
        # Выбор и применение — разные действия. Пока не нажали
        # «Применить», в базе ничего не меняется, и это видно на экране:
        # иначе непонятно, случилось уже что-то или ещё нет.
        ttk.Separator(inner, orient='horizontal').pack(fill='x', pady=(12, 10))

        # Строка состояния: что стоит на показанном дне сейчас
        self.posts_state = ttk.Label(
            inner, text="", font=(styles.DEFAULT_FONT, 10),
            background=styles.COLORS['bg_card'],
            foreground=styles.COLORS['text'])
        self.posts_state.pack(anchor='w', pady=(0, 8))

        posts_row = ttk.Frame(inner, style='White.TFrame')
        posts_row.pack(fill='x')

        styles.create_label(posts_row, "Сделать постов:",
                            'Card.TLabel').pack(side='left', padx=(0, 8))

        self.post_buttons = {}
        for count in range(MIN_POSTS, MAX_POSTS + 1):
            button = tk.Button(
                posts_row, text=str(count), width=3,
                font=(styles.DEFAULT_FONT, 11, 'bold'),
                relief='flat', bd=0, cursor='hand2',
                command=lambda c=count: self.choose_posts(c))
            button.pack(side='left', padx=(0, 4))
            self.post_buttons[count] = button

        styles.create_label(posts_row, "на:", 'Card.TLabel').pack(
            side='left', padx=(16, 8))

        for title, days in APPLY_SCOPES:
            ttk.Radiobutton(posts_row, text=title, value=days,
                            variable=self.scope_days,
                            command=self.refresh_posts_panel).pack(
                side='left', padx=(0, 10))

        # Свой срок: «на 10 дней вперёд» без перебора дней по одному
        ttk.Radiobutton(posts_row, text="свой срок:", value=CUSTOM_SCOPE,
                        variable=self.scope_days,
                        command=self.refresh_posts_panel).pack(side='left')

        self.custom_days = tk.StringVar(value='10')
        spin = ttk.Spinbox(posts_row, from_=1, to=MAX_SCOPE_DAYS, width=4,
                           textvariable=self.custom_days,
                           font=styles.FONTS['normal'],
                           command=self.refresh_posts_panel)
        spin.pack(side='left', padx=(6, 2))
        spin.bind('<KeyRelease>', lambda e: self.refresh_posts_panel())
        styles.create_label(posts_row, "дн.", 'Card.TLabel').pack(side='left')

        self.apply_button = styles.create_button(
            posts_row, "Применить", self.apply_posts, 'Primary.TButton')
        self.apply_button.pack(side='left', padx=(18, 0))

        self.posts_hint = ttk.Label(
            inner, text="", font=(styles.DEFAULT_FONT, 9),
            background=styles.COLORS['bg_card'],
            foreground=styles.COLORS['text_secondary'],
            wraplength=900, justify='left')
        self.posts_hint.pack(anchor='w', pady=(8, 0))

        # Полоса состояния связи. Видна только когда работаем через
        # сервер и связи нет: в обычной работе она была бы шумом
        self.connection_bar = tk.Label(
            self.frame, text="", anchor='w', padx=16, pady=7,
            font=(styles.DEFAULT_FONT, 10, 'bold'),
            bg=styles.COLORS['danger'], fg='white')

    def _build_timeline(self):
        card = styles.create_card_frame(self.frame)
        card.pack(fill='both', expand=True, padx=15, pady=(0, 15))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=14, pady=(10, 12))

        # Шапка с постами не прокручивается: иначе, уехав к вечеру,
        # перестаёшь понимать, какая колонка какой пост
        self.header = tk.Canvas(inner, height=26, highlightthickness=0,
                                bg=styles.COLORS['bg_card'])
        self.header.pack(fill='x')

        body = ttk.Frame(inner, style='White.TFrame')
        body.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(body, highlightthickness=0,
                                bg=styles.COLORS['bg_card'])
        scrollbar = ttk.Scrollbar(body, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set,
                              scrollregion=(0, 0, 0, 24 * HOUR_HEIGHT))

        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)

        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.canvas.bind('<MouseWheel>',
                         lambda e: self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units'))
        # Двойной щелчок по пустому месту — запись на это время:
        # быстрее, чем открывать окно и выставлять время руками
        self.canvas.bind('<Double-Button-1>', self.on_empty_double_click)

    # ------------------------------------------------------------------
    # Навигация по дням
    # ------------------------------------------------------------------

    def shift_day(self, delta):
        self.current_day += timedelta(days=delta)
        self.load_day()

    def go_today(self):
        self.current_day = get_moscow_time().date()
        self._scrolled_once = False
        self.load_day()

    def on_date_picked(self, event=None):
        chosen = self.date_picker.get_date()
        if chosen != self.current_day:
            self.current_day = chosen
            self.load_day()

    def load_day(self):
        self.date_picker.set_date(self.current_day)

        # Один поход за данными на перерисовку: при работе через сервер
        # это запрос по сети, и дёргать его из каждого метода нельзя
        try:
            self.day_state = self.booking.load_day(self.current_day)
        except Exception as e:
            log.error(f"Не удалось получить записи на день: {e}")
            self.day_state = {'placed': [], 'posts': 1, 'online': False,
                              'fetched_at': None, 'reason': str(e)}

        # Перешли на другой день — выбор подтягивается к тому, что там
        # стоит. Иначе выбранное на вчера выглядело бы как незакреплённая
        # правка сегодняшнего дня
        self.selected_posts = self.day_state.get('posts', 1)

        weekdays = ['понедельник', 'вторник', 'среда', 'четверг',
                    'пятница', 'суббота', 'воскресенье']
        months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
        title = (f"{weekdays[self.current_day.weekday()]}, "
                 f"{self.current_day.day} {months[self.current_day.month - 1]}")
        if self.current_day == get_moscow_time().date():
            title += "  ·  сегодня"
        self.day_label.config(text=title)

        self.redraw()

    # ------------------------------------------------------------------
    # Посты
    # ------------------------------------------------------------------

    def scope_length(self):
        """На сколько дней распространится настройка."""
        if self.scope_days.get() != CUSTOM_SCOPE:
            return self.scope_days.get()
        try:
            return max(1, min(MAX_SCOPE_DAYS, int(self.custom_days.get())))
        except (TypeError, ValueError):
            return 1

    def choose_posts(self, count):
        """
        Выбрать число постов. В базу пока ничего не пишем.

        Раньше нажатие сразу меняло настройку, и было непонятно,
        произошло уже что-то или нет. Теперь выбор виден на экране,
        а закрепляет его «Применить».
        """
        self.selected_posts = count
        self.refresh_posts_panel()

    def apply_posts(self):
        """Закрепить выбранное число постов за выбранным отрезком дней."""
        if not self.require_online():
            return

        days = self.scope_length()
        count = self.selected_posts
        last_day = self.current_day + timedelta(days=days - 1)

        try:
            self.booking.set_posts_for_days(self.current_day, days, count)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Посты", f"Не удалось сохранить: {e}")
            return

        if days == 1:
            where = f"на {self.current_day.strftime('%d.%m')}"
        else:
            where = (f"на {days} дн.: с {self.current_day.strftime('%d.%m')} "
                     f"по {last_day.strftime('%d.%m')}")
        self._applied_message = f"Готово: {count} {plural_posts(count)} {where}"

        # Перечитываем день: постов стало больше — карточки могли
        # перестать быть «сверх постов» и переехать в сетку
        chosen = count
        self.load_day()
        self.selected_posts = chosen

    def refresh_posts_panel(self, saved=None):
        """Показать, что стоит сейчас и что произойдёт при нажатии."""
        if saved is None:
            saved = self.day_state.get('posts', 1)

        if not hasattr(self, 'selected_posts') or self.selected_posts is None:
            self.selected_posts = saved

        for count, button in self.post_buttons.items():
            chosen = count == self.selected_posts
            button.config(
                bg=styles.COLORS['primary'] if chosen else styles.COLORS['bg_subtle'],
                fg='white' if chosen else styles.COLORS['text'],
                activebackground=styles.COLORS['primary_hover'] if chosen
                else styles.COLORS['border'],
                activeforeground='white' if chosen else styles.COLORS['text'])

        day_title = self.current_day.strftime('%d.%m.%Y')
        self.posts_state.config(
            text=f"Сейчас на {day_title} открыто "
                 f"{saved} {plural_posts(saved)} для записи")

        days = self.scope_length()
        last_day = self.current_day + timedelta(days=days - 1)

        if self._applied_message:
            # Подтверждение держим до следующего изменения выбора
            self.posts_hint.config(text=self._applied_message,
                                   foreground=styles.COLORS['success'])
            self._applied_message = None
            return

        if days == 1:
            target = f"день {day_title}"
        else:
            target = (f"{days} дн. — с {day_title} по "
                      f"{last_day.strftime('%d.%m.%Y')}")

        self.posts_hint.config(
            text=f"Нажмите «Применить» — и на {target} будет "
                 f"{self.selected_posts} {plural_posts(self.selected_posts)}. "
                 f"Пока не нажали, ничего не изменилось.",
            foreground=styles.COLORS['warning'] if self.selected_posts != saved
            else styles.COLORS['text_secondary'])

    # ------------------------------------------------------------------
    # Связь
    # ------------------------------------------------------------------

    def _refresh_connection(self):
        """
        Показать, что связи нет, и запретить то, что без неё нельзя.

        Когда записи живут на сервере, без интернета их нельзя ни
        создать, ни отменить. Молчать об этом нельзя: приёмщик нажмёт
        и решит, что записал.
        """
        online = self.day_state.get('online', True)

        if online or not self.booking.is_remote:
            self.connection_bar.pack_forget()
        else:
            fetched = self.day_state.get('fetched_at')
            when = (f"Показано на {fetched:%H:%M}" if fetched
                    else "Данных за этот день ещё не получали")
            self.connection_bar.config(
                text=f"Нет связи с сервером. {when}. "
                     f"Записать и отменить сейчас нельзя")
            self.connection_bar.pack(fill='x', before=self.frame.winfo_children()[0])

        # Кнопки, которым нужна связь
        state = 'normal' if (online or not self.booking.is_remote) else 'disabled'
        for widget in (self.book_button, self.apply_button):
            try:
                widget.config(state=state)
            except Exception:
                pass

    def require_online(self):
        """Проверить связь перед действием. Возвращает True, если можно."""
        if not self.booking.is_remote or self.day_state.get('online', True):
            return True

        messagebox.showwarning(
            "Нет связи",
            "Записи хранятся на сервере, а связи сейчас нет.\n\n"
            "Записать, отменить или отметить приезд можно будет, когда "
            "интернет вернётся. Приём машин, оплата и печать чеков "
            "работают как обычно.")
        return False

    # ------------------------------------------------------------------
    # Отрисовка ленты
    # ------------------------------------------------------------------

    def redraw(self):
        placed = self.day_state.get('placed', [])
        posts = self.day_state.get('posts', 1)

        self.refresh_posts_panel(saved=posts)
        self._refresh_connection()

        # Записей может оказаться больше, чем постов: посты уменьшили
        # задним числом. Такие показываем отдельной колонкой, а не прячем
        overflow = any(column >= posts for _, column in placed)
        columns = posts + (1 if overflow else 0)

        width = max(self.canvas.winfo_width(), 200)
        column_width = max(90, (width - GUTTER - 6) / columns)

        self._draw_header(columns, posts, column_width)
        self._draw_grid(columns, column_width, width)
        self._draw_cards(placed, column_width)

        self.canvas.configure(scrollregion=(0, 0, width, 24 * HOUR_HEIGHT))

        if not self._scrolled_once:
            self.canvas.yview_moveto(DEFAULT_SCROLL_HOUR / 24)
            self._scrolled_once = True

    def _draw_header(self, columns, posts, column_width):
        self.header.delete('all')
        for index in range(columns):
            x = GUTTER + index * column_width
            title = f"Пост {index + 1}" if index < posts else "Сверх постов"
            colour = (styles.COLORS['text_secondary'] if index < posts
                      else styles.COLORS['danger'])
            self.header.create_text(x + column_width / 2, 14, text=title,
                                    font=(styles.DEFAULT_FONT, 10, 'bold'),
                                    fill=colour)

    def _draw_grid(self, columns, column_width, width):
        self.canvas.delete('grid')

        for hour in range(25):
            y = hour * HOUR_HEIGHT
            self.canvas.create_line(GUTTER - 6, y, width, y,
                                    fill=styles.COLORS['border'], tags='grid')
            if hour < 24:
                self.canvas.create_text(
                    GUTTER - 12, y + 2, text=f"{hour:02d}:00", anchor='ne',
                    font=(styles.DEFAULT_FONT, 9),
                    fill=styles.COLORS['text_secondary'], tags='grid')
                # Получасовая отметка — светлее, чтобы не рябило
                self.canvas.create_line(
                    GUTTER - 6, y + HOUR_HEIGHT / 2, width, y + HOUR_HEIGHT / 2,
                    fill=styles.COLORS['bg_subtle'], tags='grid')

        for index in range(columns + 1):
            x = GUTTER + index * column_width
            self.canvas.create_line(x, 0, x, 24 * HOUR_HEIGHT,
                                    fill=styles.COLORS['border'], tags='grid')

        # Красная черта «сейчас» — только на сегодняшнем дне
        if self.current_day == get_moscow_time().date():
            now = get_moscow_time()
            y = (now.hour + now.minute / 60) * HOUR_HEIGHT
            self.canvas.create_line(GUTTER - 6, y, width, y,
                                    fill=styles.COLORS['danger'], width=2,
                                    tags='grid')

    def _draw_cards(self, placed, column_width):
        self.canvas.delete('card')
        self._cards = {}

        for appointment, column in placed:
            moment = appointment.scheduled_at
            top = (moment.hour + moment.minute / 60) * HOUR_HEIGHT
            height = max(MIN_CARD_HEIGHT,
                         (appointment.duration_minutes or 30) / 60 * HOUR_HEIGHT)

            x0 = GUTTER + column * column_width + 3
            x1 = x0 + column_width - 8
            y0, y1 = top + 2, top + height - 2

            fill, outline, text_colour = CARD_COLORS.get(
                appointment.status, CARD_COLORS[Appointment.STATUS_SCHEDULED])

            key = self.booking.key_of(appointment)
            tag = f'appt_{key}'
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill,
                                         outline=outline, width=1,
                                         tags=('card', tag))
            # На карточке только номер: это то, чем машина отличается
            # от других на экране
            self.canvas.create_text(
                (x0 + x1) / 2, (y0 + y1) / 2,
                text=appointment.license_plate or 'без номера',
                font=(styles.DEFAULT_FONT, 10, 'bold'),
                fill=text_colour, tags=('card', tag))

            self.canvas.tag_bind(tag, '<Button-1>',
                                 lambda e, i=key: self.open_details(i))
            self._cards[key] = tag

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def on_empty_double_click(self, event):
        """Двойной щелчок по свободному месту — запись на это время."""
        if self.canvas.find_withtag('current') and \
                'card' in self.canvas.gettags('current'):
            return

        y = self.canvas.canvasy(event.y)
        minutes = int(y / HOUR_HEIGHT * 60)
        minutes = max(0, min(24 * 60 - 15, minutes))

        when = datetime(self.current_day.year, self.current_day.month,
                        self.current_day.day) + timedelta(minutes=minutes)
        self.create_appointment(when=when)

    def create_appointment(self, when=None):
        if not self.require_online():
            return

        if when is None:
            base = get_moscow_time()
            if self.current_day != base.date():
                base = datetime(self.current_day.year, self.current_day.month,
                                self.current_day.day, 9, 0)
            when = base
        AppointmentDialog(self.frame, self.db, when=when, on_saved=self.load_day)

    def open_details(self, key):
        AppointmentDetailsDialog(self.frame, self.db, key,
                                 on_changed=self.load_day,
                                 orders_tab=self.orders_tab)
