"""
Настройка «Выбор колеса»: включена ли и у каких услуг открывается
схема машины.

Услуги добавляются из прайса списком — набирать название руками
значит ошибиться буквой, и схема молча не откроется. Сохраняется
сразу, как и другие списки в настройках.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from models import Service
from services.wheel_service import WheelSettings
import styles


class WheelServicesEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.wheels = WheelSettings(db)

        self.enabled_var = tk.BooleanVar(value=self.wheels.enabled())
        ttk.Checkbutton(parent, text='Спрашивать колесо при ремонте и правке',
                        variable=self.enabled_var,
                        command=self.save_enabled).pack(anchor='w', pady=(0, 10))

        styles.create_label(parent, 'Услуги, у которых открывается схема:',
                            'Card.TLabel').pack(anchor='w', pady=(0, 4))

        row = ttk.Frame(parent, style='White.TFrame')
        row.pack(fill='x', pady=(0, 10))

        self.listbox = tk.Listbox(
            row, height=8, width=40, exportselection=False,
            font=styles.FONTS['normal'], bg=styles.COLORS['bg_subtle'],
            fg=styles.COLORS['text'],
            selectbackground=styles.COLORS['primary'],
            relief='flat', highlightthickness=1,
            highlightbackground=styles.COLORS['border'])
        self.listbox.pack(side='left')

        buttons = ttk.Frame(row, style='White.TFrame')
        buttons.pack(side='left', fill='y', padx=(10, 0))
        styles.create_button(buttons, 'Добавить из прайса', self.add,
                             'Compact.Secondary.TButton').pack(fill='x')
        styles.create_button(buttons, 'Убрать', self.remove,
                             'Compact.Secondary.TButton').pack(fill='x', pady=(4, 0))
        styles.create_button(buttons, 'Посмотреть схему', self.preview,
                             'Compact.Secondary.TButton').pack(fill='x', pady=(4, 0))

        self.refresh()

    def refresh(self):
        self.listbox.delete(0, tk.END)
        for name in self.wheels.names():
            self.listbox.insert(tk.END, name)

    def save_enabled(self):
        try:
            self.wheels.set_enabled(self.enabled_var.get())
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                 parent=self.window)

    def remove(self):
        chosen = self.listbox.curselection()
        if not chosen:
            messagebox.showinfo('Выбор колеса', 'Выберите услугу в списке',
                                parent=self.window)
            return
        try:
            self.wheels.remove(self.listbox.get(chosen[0]))
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                 parent=self.window)
        self.refresh()

    def price_names(self):
        """Работы из прайса, которых ещё нет в списке."""
        rows = self.db.query(Service.name).filter(
            Service.is_active.isnot(False),
            Service.is_goods.isnot(True)).distinct().all()
        have = set(self.wheels.names())
        return sorted({name for (name,) in rows if name and name not in have})

    def add(self):
        names = self.price_names()
        if not names:
            messagebox.showinfo('Выбор колеса', 'Все услуги прайса уже в списке',
                                parent=self.window)
            return None

        dialog = tk.Toplevel(self.window)
        dialog.title('Добавить из прайса')
        dialog.configure(bg=styles.COLORS['bg_card'])
        dialog.transient(self.window)

        body = ttk.Frame(dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=16, pady=14)
        styles.create_label(body, 'Отметьте услуги (можно несколько):',
                            'Card.TLabel').pack(anchor='w', pady=(0, 6))

        listbox = tk.Listbox(body, height=14, width=42, selectmode='multiple',
                             exportselection=False,
                             font=styles.FONTS['normal'],
                             bg=styles.COLORS['bg_subtle'],
                             fg=styles.COLORS['text'],
                             selectbackground=styles.COLORS['primary'],
                             relief='flat', highlightthickness=1,
                             highlightbackground=styles.COLORS['border'])
        listbox.pack(fill='both', expand=True)
        for name in names:
            listbox.insert(tk.END, name)

        def save():
            picked = [listbox.get(i) for i in listbox.curselection()]
            if not picked:
                dialog.destroy()
                return
            try:
                self.wheels.set_names(self.wheels.names() + picked)
            except Exception as e:
                self.db.rollback()
                messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                     parent=dialog)
                return
            dialog.destroy()
            self.refresh()

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        styles.create_button(buttons, 'Добавить', save,
                             'Primary.TButton').pack(side='left')
        styles.create_button(buttons, 'Отмена', dialog.destroy,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        dialog.bind('<Escape>', lambda e: dialog.destroy())

        styles.center_window(dialog, self.window)
        dialog.grab_set()
        dialog.save = save
        dialog.listbox = listbox
        return dialog

    def preview(self):
        """
        Показать схему, как её увидит приёмщик, — легковую и грузовую.
        Ничего не сохраняет.
        """
        from ui import wheel_picker

        chosen = self.listbox.curselection()
        name = self.listbox.get(chosen[0]) if chosen else 'Ремонт жгутом'
        for vehicle_type in ('car', 'truck'):
            result = wheel_picker.pick_wheels(self.window, vehicle_type,
                                              f'{name} — пример')
            if result is None:
                break
