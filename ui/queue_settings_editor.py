"""
Настройки живой очереди: запас на допы, сколько ждать позванного и
какие услуги сразу встают в наряд — «колёса в сборе» и «только шины».

Сохраняется сразу, как и другие списки в настройках.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from models import Service
from services.live_queue_service import (LiveQueueService, BUFFER_KEY, BUFFER_DEFAULT,
                                         CALL_WAIT_KEY, CALL_WAIT_DEFAULT, SEASON,
                                         AUTUMN_FROM_KEY, AUTUMN_FROM_DEFAULT,
                                         SPRING_FROM_KEY, SPRING_FROM_DEFAULT,
                                         SEASON_DAYS_KEY, SEASON_DAYS_DEFAULT)
from utils import as_naive, get_moscow_time
import styles


class QueueSettingsEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.service = LiveQueueService(db)

        # Посты и живая очередь нужны в ажиотаж. Вне его — наряды как
        # обычно. «По сезону» включает и выключает само по датам
        styles.create_label(parent, 'Посты и живая очередь:', 'Card.TLabel').pack(anchor='w')
        modes = ttk.Frame(parent, style='White.TFrame')
        modes.pack(anchor='w', pady=(4, 4))
        self.mode_var = tk.StringVar(value=self.service.mode())
        for value, title in (('on', 'Всегда'), (SEASON, 'По сезону'), ('off', 'Выключены')):
            ttk.Radiobutton(modes, text=title, value=value, variable=self.mode_var,
                            command=self.save_mode).pack(side='left', padx=(0, 14))

        season = ttk.Frame(parent, style='White.TFrame')
        season.pack(anchor='w', pady=(0, 4))
        self.season_fields = {}
        for column, (key, title, default) in enumerate((
                (AUTUMN_FROM_KEY, 'Осенью с', AUTUMN_FROM_DEFAULT),
                (SPRING_FROM_KEY, 'весной с', SPRING_FROM_DEFAULT))):
            styles.create_label(season, title, 'Card.TLabel').grid(
                row=0, column=column * 2, sticky='w', padx=(0 if column == 0 else 12, 4))
            var = tk.StringVar(value=self.service._settings().get(key, default) or default)
            entry = ttk.Entry(season, width=7, textvariable=var)
            entry.grid(row=0, column=column * 2 + 1, sticky='w')
            entry.bind('<FocusOut>', lambda e, k=key, v=var: self.save_day(k, v))
            entry.bind('<Return>', lambda e, k=key, v=var: self.save_day(k, v))
            self.season_fields[key] = var
        styles.create_label(season, 'длится', 'Card.TLabel').grid(row=0, column=4, padx=(12, 4))
        self.days_var = tk.StringVar(value=str(self.service._settings().get_int(
            SEASON_DAYS_KEY, SEASON_DAYS_DEFAULT)))
        days = ttk.Spinbox(season, from_=1, to=120, width=5, textvariable=self.days_var,
                           command=lambda: self.save_number(SEASON_DAYS_KEY, self.days_var))
        days.grid(row=0, column=5, sticky='w')
        days.bind('<FocusOut>', lambda e: self.save_number(SEASON_DAYS_KEY, self.days_var))
        styles.create_label(season, 'дней', 'Card.TLabel').grid(row=0, column=6, padx=(4, 0))

        self.mode_note = styles.create_label(parent, '', 'Card.TLabel')
        self.mode_note.pack(anchor='w', pady=(0, 12))
        self.show_mode()

        grid = ttk.Frame(parent, style='White.TFrame')
        grid.pack(fill='x', pady=(0, 12))
        self.numbers = {}
        for row, (key, title, default) in enumerate((
                (BUFFER_KEY, 'Запас на допы, мин', BUFFER_DEFAULT),
                (CALL_WAIT_KEY, 'Позвали — ждём машину, мин', CALL_WAIT_DEFAULT))):
            styles.create_label(grid, title, 'Card.TLabel').grid(row=row, column=0, sticky='w', pady=3)
            var = tk.StringVar(value=str(self.service._settings().get_int(key, default)))
            entry = ttk.Spinbox(grid, from_=0, to=120, width=6, textvariable=var,
                                command=lambda k=key, v=var: self.save_number(k, v))
            entry.grid(row=row, column=1, sticky='w', padx=(10, 0), pady=3)
            entry.bind('<FocusOut>', lambda e, k=key, v=var: self.save_number(k, v))
            entry.bind('<Return>', lambda e, k=key, v=var: self.save_number(k, v))
            self.numbers[key] = var

        self.auto_var = tk.BooleanVar(value=self.service.auto_call_enabled())
        ttk.Checkbutton(parent, text='Звать на освободившийся пост автоматически',
                        variable=self.auto_var,
                        command=lambda: self.service._settings().set(
                            'live_queue_auto_call', '1' if self.auto_var.get() else '0')
                        ).pack(anchor='w', pady=(0, 12))

        lists = ttk.Frame(parent, style='White.TFrame')
        lists.pack(fill='x', pady=(0, 10))
        self.boxes = {}
        for column, (assembled, title) in enumerate(((True, 'Колёса в сборе'),
                                                    (False, 'Только шины'))):
            col = ttk.Frame(lists, style='White.TFrame')
            col.pack(side='left', fill='y', padx=(0, 24))
            styles.create_label(col, f'{title} — услуги в наряд:', 'Card.TLabel').pack(anchor='w', pady=(0, 4))
            box = tk.Listbox(col, height=7, width=30, exportselection=False,
                             font=styles.FONTS['normal'], bg=styles.COLORS['bg_subtle'],
                             fg=styles.COLORS['text'],
                             selectbackground=styles.COLORS['primary'],
                             relief='flat', highlightthickness=1,
                             highlightbackground=styles.COLORS['border'])
            box.pack(anchor='w')
            row = ttk.Frame(col, style='White.TFrame')
            row.pack(anchor='w', pady=(4, 0))
            styles.create_button(row, 'Добавить из прайса', lambda a=assembled: self.add(a),
                                 'Compact.Secondary.TButton').pack(side='left')
            styles.create_button(row, 'Убрать', lambda a=assembled: self.remove(a),
                                 'Compact.Secondary.TButton').pack(side='left', padx=(4, 0))
            self.boxes[assembled] = box
        self.refresh()

    def refresh(self):
        for assembled, box in self.boxes.items():
            box.delete(0, tk.END)
            for name in self.service.kit(assembled):
                box.insert(tk.END, name)

    def save_number(self, key, var):
        try:
            value = max(0, int(var.get()))
        except ValueError:
            return
        self.service._settings().set(key, str(value))
        if key == SEASON_DAYS_KEY:
            self.show_mode()

    def save_mode(self):
        self.service.set_mode(self.mode_var.get())
        self.show_mode()

    def save_day(self, key, var):
        from services.live_queue_service import _day_month
        text = var.get().strip()
        if _day_month(text, 2024) is None:     # високосный: 29.02 тоже дата
            messagebox.showerror('Очередь', f'«{text}» — не дата. Нужно дд.мм, например 01.10',
                                 parent=self.window)
            return
        self.service._settings().set(key, text)
        self.show_mode()

    def show_mode(self):
        on = self.service.enabled()
        text = ('Сейчас включены: наряды встают на посты, программа зовёт сама.' if on else
                'Сейчас выключены: наряды как обычно, без постов; по QR встать нельзя, '
                '«Я на месте» в кабинете не показывается.')
        if self.service.mode() == SEASON:
            today = as_naive(get_moscow_time()).date()
            windows = [(s, e) for s, e in self.service.season_windows(today) if e >= today]
            if windows:
                start, end = windows[0]
                text += f'\nСезон: {start:%d.%m} — {end:%d.%m}.'
        self.mode_note.config(text=text)

    def remove(self, assembled):
        box = self.boxes[assembled]
        chosen = box.curselection()
        if not chosen:
            messagebox.showinfo('Очередь', 'Выберите услугу в списке', parent=self.window)
            return
        name = box.get(chosen[0])
        self.service.set_kit(assembled, [n for n in self.service.kit(assembled) if n != name])
        self.refresh()

    def price_names(self, assembled):
        rows = self.db.query(Service.name).filter(
            Service.is_active.isnot(False),
            Service.is_goods.isnot(True)).distinct().all()
        have = set(self.service.kit(assembled))
        return sorted({n for (n,) in rows if n and n not in have})

    def add(self, assembled):
        names = self.price_names(assembled)
        if not names:
            messagebox.showinfo('Очередь', 'Все услуги прайса уже в списке', parent=self.window)
            return None
        dialog = tk.Toplevel(self.window)
        dialog.title('Добавить из прайса')
        dialog.configure(bg=styles.COLORS['bg_card'])
        dialog.transient(self.window)
        body = ttk.Frame(dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=16, pady=14)
        listbox = tk.Listbox(body, height=14, width=42, selectmode='multiple',
                             exportselection=False, font=styles.FONTS['normal'])
        listbox.pack(fill='both', expand=True)
        for name in names:
            listbox.insert(tk.END, name)

        def save():
            picked = [listbox.get(i) for i in listbox.curselection()]
            if picked:
                self.service.set_kit(assembled, self.service.kit(assembled) + picked)
                self.refresh()
            dialog.destroy()

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        styles.create_button(buttons, 'Добавить', save, 'Primary.TButton').pack(side='left')
        styles.create_button(buttons, 'Отмена', dialog.destroy,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.center_window(dialog, self.window)
        dialog.grab_set()
        dialog.save = save
        dialog.listbox = listbox
        return dialog
