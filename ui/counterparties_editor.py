"""
Контрагенты — раздел настроек (docs/calendar.md).

Поставщики шин, расходников, правка дисков. Нужны, чтобы в задаче
календаря было видно, от кого приедет и кому звонить. Сохраняется сразу,
как и другие списки в настройках.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from services.calendar_service import CalendarService, TaskError

FIELDS = [('name', 'Название'), ('kind', 'Чем занимается'), ('contact', 'Контакт'),
          ('phone', 'Телефон'), ('email', 'Почта'), ('address', 'Адрес'),
          ('inn', 'ИНН'), ('note', 'Заметка')]


class CounterpartiesEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.service = CalendarService(db)
        self.current = None

        body = ttk.Frame(parent, style='White.TFrame')
        body.pack(fill='both', expand=True)

        left = ttk.Frame(body, style='White.TFrame')
        left.pack(side='left', fill='y', padx=(0, 16))
        self.listbox = tk.Listbox(left, height=14, width=28, exportselection=False,
                                  font=styles.FONTS['normal'], bg=styles.COLORS['bg_subtle'],
                                  relief='flat', highlightthickness=1,
                                  highlightbackground=styles.COLORS['border'])
        self.listbox.pack(fill='y', expand=True)
        self.listbox.bind('<<ListboxSelect>>', lambda e: self._chosen())
        styles.create_button(left, '+ Добавить', self.new,
                             'Secondary.TButton').pack(fill='x', pady=(6, 0))

        right = ttk.Frame(body, style='White.TFrame')
        right.pack(side='left', fill='both', expand=True)
        form = ttk.Frame(right, style='White.TFrame')
        form.pack(fill='x')
        self.entries = {}
        for row, (key, title) in enumerate(FIELDS):
            styles.create_label(form, title, 'Card.TLabel').grid(row=row, column=0, sticky='w', pady=3)
            entry = styles.create_entry(form, width=40)
            entry.grid(row=row, column=1, sticky='we', padx=(10, 0), pady=3)
            self.entries[key] = entry
        buttons = ttk.Frame(right, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        styles.create_button(buttons, 'Сохранить', self.save, 'Primary.TButton').pack(side='left')
        styles.create_button(buttons, '+ Задача с ним', self.add_task,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.create_button(buttons, 'Удалить', self.delete,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.create_label(right, 'Задачи и поставки', 'Card.TLabel').pack(anchor='w', pady=(14, 4))
        self.tasks = tk.Listbox(right, height=6, font=styles.FONTS['small'],
                                bg=styles.COLORS['bg_subtle'], relief='flat',
                                highlightthickness=1, highlightbackground=styles.COLORS['border'])
        self.tasks.pack(fill='x')
        self.refresh()

    def refresh(self, select_uid=None):
        self.rows = self.service.counterparties()
        self.listbox.delete(0, tk.END)
        for row in self.rows:
            self.listbox.insert(tk.END, row.name + (f'  ·  {row.kind}' if row.kind else ''))
        if select_uid:
            for index, row in enumerate(self.rows):
                if row.uid == select_uid:
                    self.listbox.selection_set(index)
                    self._chosen()
                    return
        self._fill(None)

    def _chosen(self):
        chosen = self.listbox.curselection()
        self._fill(self.rows[chosen[0]] if chosen else None)

    def _fill(self, row):
        self.current = row
        for key, entry in self.entries.items():
            entry.delete(0, tk.END)
            if row is not None and getattr(row, key):
                entry.insert(0, getattr(row, key))
        self.tasks.delete(0, tk.END)
        if row is not None:
            for task in self.service.tasks_of_counterparty(row.uid):
                mark = '✓ ' if task.done_at else ''
                self.tasks.insert(tk.END, f'{mark}{task.due_date:%d.%m.%y} · {task.title}')

    def new(self):
        self.listbox.selection_clear(0, tk.END)
        self._fill(None)
        self.entries['name'].focus_set()

    def save(self):
        fields = {key: entry.get() for key, entry in self.entries.items()}
        try:
            row = self.service.save_counterparty(self.current, **fields)
        except TaskError as e:
            messagebox.showerror('Контрагенты', str(e), parent=self.window)
            return
        self.refresh(select_uid=row.uid)

    def delete(self):
        if self.current is None:
            return
        if not messagebox.askyesno('Контрагенты', f'Удалить «{self.current.name}»?',
                                   parent=self.window):
            return
        self.service.delete_counterparty(self.current)
        self.refresh()

    def add_task(self):
        if self.current is None:
            messagebox.showinfo('Контрагенты', 'Сначала выберите или сохраните контрагента',
                                parent=self.window)
            return
        from ui.task_dialog import open_task
        uid = self.current.uid
        open_task(self.window, self.db, counterparty_uid=uid, category='tires',
                  on_saved=lambda: self.refresh(select_uid=uid))
