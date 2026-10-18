"""
Настройки живой очереди: запас на допы, сколько ждать позванного и
какие услуги сразу встают в наряд — «колёса в сборе» и «только шины».

Сохраняется сразу, как и другие списки в настройках.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from models import Service
from services.live_queue_service import (LiveQueueService, BUFFER_KEY, BUFFER_DEFAULT,
                                         CALL_WAIT_KEY, CALL_WAIT_DEFAULT)
import styles


class QueueSettingsEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.service = LiveQueueService(db)

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
