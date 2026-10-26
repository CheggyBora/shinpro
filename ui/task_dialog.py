"""
Окно задачи календаря: завести, поправить, перенести, отметить.

Открывается из ленты над нарядами, из календаря, из наряда машины и
из карточки контрагента. Менять можно всё — задачу ставили второпях, а
поставка сдвинулась (docs/calendar.md).
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from models.calendar import CATEGORIES, CATEGORY_TITLES, WORK, categories_of
from services.calendar_service import CalendarService, TaskError
from ui.plate_picker import PlatePicker, owner_of, owner_text
from utils import get_moscow_time, as_naive

SOURCE_TITLES = {'shop': 'цех', 'dashboard': 'дашборд', 'auto': 'программа',
                 'cabinet': 'кабинет клиента'}

# Цвета разделов — те же, что в дашборде
CATEGORY_COLORS = {
    'work': ('#1d4ed8', '#dbeafe'),
    'storage': ('#0f766e', '#ccfbf1'),
    'tires': ('#c2410c', '#ffedd5'),
    'paint': ('#6d28d9', '#ede9fe'),
    'supply': ('#b45309', '#fef3c7'),
}

WHO = 'Цех'


def open_task(parent, db, task=None, on_saved=None, **defaults):
    return TaskDialog(parent, db, task, on_saved, defaults)


class TaskDialog:
    def __init__(self, parent, db, task=None, on_saved=None, defaults=None):
        self.db = db
        self.service = CalendarService(db)
        self.task = task
        self.on_saved = on_saved
        defaults = defaults or {}

        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Задача' if task else 'Новая задача')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=16)
        form = ttk.Frame(body, style='White.TFrame')
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)

        def label(row, text):
            styles.create_label(form, text, 'Card.TLabel').grid(
                row=row, column=0, sticky='nw', pady=4, padx=(0, 12))

        today = as_naive(get_moscow_time()).date()

        # Слой календаря: у мойки свои разделы и контрагенты
        self.direction = (task.direction if task else defaults.get('direction')) or 'tire'
        label(0, 'Раздел')
        self.category = tk.StringVar(value=task.category if task else defaults.get('category', WORK))
        if self.category.get() not in categories_of(self.direction):
            self.category.set(WORK)
        cats = ttk.Frame(form, style='White.TFrame')
        cats.grid(row=0, column=1, sticky='w', pady=4)
        for key in categories_of(self.direction):
            ttk.Radiobutton(cats, text=CATEGORY_TITLES[key], value=key,
                            variable=self.category).pack(side='left', padx=(0, 10))

        label(1, 'Дата и время')
        when = ttk.Frame(form, style='White.TFrame')
        when.grid(row=1, column=1, sticky='w', pady=4)
        self.day = styles.create_entry(when, width=12)
        self.day.pack(side='left')
        day = task.due_date if task else defaults.get('due_date', today)
        self.day.insert(0, day.strftime('%d.%m.%Y'))
        self.time = styles.create_entry(when, width=7)
        self.time.pack(side='left', padx=(8, 8))
        self.time.insert(0, (task.due_time if task else defaults.get('due_time')) or '')
        ttk.Label(when, text='время можно не ставить', font=styles.FONTS['small'],
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(side='left')

        label(2, 'Машина')
        car_row = ttk.Frame(form, style='White.TFrame')
        car_row.grid(row=2, column=1, sticky='w', pady=4)
        self.plate = PlatePicker(car_row, db, on_pick=self._show_owner)
        self.plate.frame.pack(side='left', anchor='n')
        self.owner_label = ttk.Label(car_row, text='', font=styles.FONTS['small'],
                                     foreground=styles.COLORS['text_secondary'],
                                     background=styles.COLORS['bg_card'])
        self.owner_label.pack(side='left', anchor='n', padx=(8, 8), pady=(4, 0))
        styles.create_button(car_row, 'Открыть машину', self.open_car,
                             'Compact.Secondary.TButton').pack(side='left', anchor='n')
        plate = task.license_plate if task else defaults.get('license_plate')
        if plate:
            self.plate.set(plate)
            self._show_owner(plate)
        self.client_name = task.client_name if task else defaults.get('client_name')
        self.client_phone = task.client_phone if task else defaults.get('client_phone')

        label(3, 'Контрагент')
        self.parties = self.service.counterparties(self.direction)
        names = ['—'] + [c.name for c in self.parties]
        self.party = tk.StringVar(value='—')
        uid = task.counterparty_uid if task else defaults.get('counterparty_uid')
        chosen = next((c for c in self.parties if c.uid == uid), None)
        if chosen is not None:
            self.party.set(chosen.name)
        ttk.Combobox(form, textvariable=self.party, values=names, state='readonly',
                     width=30, font=styles.FONTS['normal']).grid(row=3, column=1, sticky='w', pady=4)

        label(4, 'Что за задача')
        self.title = styles.create_entry(form, width=48)
        self.title.grid(row=4, column=1, sticky='we', pady=4)
        self.title.insert(0, (task.title if task else defaults.get('title')) or '')

        label(5, 'Что сделать')
        self.note = tk.Text(form, height=4, width=48, wrap='word', font=styles.FONTS['normal'],
                            relief='solid', borderwidth=1)
        self.note.grid(row=5, column=1, sticky='we', pady=4)
        self.note.insert('1.0', (task.note if task else defaults.get('note')) or '')

        label(6, 'Сумма, ₽')
        self.amount = styles.create_entry(form, width=12)
        self.amount.grid(row=6, column=1, sticky='w', pady=4)
        amount = task.amount if task else defaults.get('amount')
        if amount:
            self.amount.insert(0, f'{amount:g}')

        if task is not None:
            styles.create_label(body, 'Перенести', 'Card.TLabel').pack(anchor='w', pady=(10, 4))
            moves = ttk.Frame(body, style='White.TFrame')
            moves.pack(fill='x')
            for text, kwargs in (('+1 час', {'hours': 1}), ('Завтра', {'days': 1}),
                                 ('Через неделю', {'days': 7})):
                styles.create_button(moves, text, lambda k=kwargs: self.move(**k),
                                     'Secondary.TButton').pack(side='left', padx=(0, 6))
            ttk.Label(moves, text='или поменяйте дату выше и «Сохранить»',
                      font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card']).pack(side='left', padx=(6, 0))

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(14, 0))
        if task is not None:
            styles.create_button(buttons, 'Вернуть в работу' if task.done_at else '✓ Сделано',
                                 self.toggle_done, 'Success.TButton').pack(side='left')
            styles.create_button(buttons, 'Удалить', self.delete,
                                 'Secondary.TButton').pack(side='left', padx=(6, 0))
            who = SOURCE_TITLES.get(task.source, task.source or '')
            info = f'создал: {task.created_by or who}' + (f' · {who}' if task.created_by and who else '')
            if task.done_at:
                info += f'\nсделано: {task.done_by or ""} {as_naive(task.done_at):%d.%m %H:%M}'
            ttk.Label(buttons, text=info, font=styles.FONTS['small'], justify='right',
                      foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card']).pack(side='left', padx=(12, 0))
        styles.create_button(buttons, 'Сохранить', self.save,
                             'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))

        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()
        self.title.focus_set()

    # ------------------------------------------------------------------

    def _show_owner(self, plate):
        car, owner = owner_of(self.db, plate)
        self.owner_label.config(text=owner_text(owner))
        if owner is not None:
            self.client_name, self.client_phone = owner.name, owner.phone

    def open_car(self):
        plate = self.plate.get()
        if not plate:
            messagebox.showinfo('Машина', 'Впишите номер машины', parent=self.dialog)
            return
        from ui.car_info import open_car_info
        open_car_info(self.dialog, self.db, plate)

    def fields(self):
        amount = self.amount.get().strip().replace(' ', '').replace(',', '.')
        try:
            amount = float(amount) if amount else None
        except ValueError:
            raise TaskError('Сумма — числом, например 18700')
        party = next((c for c in self.parties if c.name == self.party.get()), None)
        return dict(
            category=self.category.get(), due_date=self.day.get(),
            due_time=self.time.get(), title=self.title.get(),
            note=self.note.get('1.0', 'end').strip() or None,
            license_plate=self.plate.get() or None,
            client_name=self.client_name if self.plate.get() else None,
            client_phone=self.client_phone if self.plate.get() else None,
            counterparty_uid=party.uid if party else None, amount=amount)

    def _done(self):
        if self.on_saved:
            self.on_saved()
        self.dialog.destroy()

    def save(self):
        try:
            fields = self.fields()
            if self.task is None:
                self.task = self.service.create(created_by=WHO, direction=self.direction, **fields)
            else:
                self.service.update(self.task, **fields)
        except TaskError as e:
            messagebox.showerror('Задача', str(e), parent=self.dialog)
            return
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Задача', f'Не удалось сохранить: {e}', parent=self.dialog)
            return
        self._done()

    def move(self, **kwargs):
        try:
            self.service.move(self.task, **kwargs)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Задача', f'Не удалось перенести: {e}', parent=self.dialog)
            return
        self._done()

    def toggle_done(self):
        self.service.set_done(self.task, not self.task.done_at, by=WHO)
        self._done()

    def delete(self):
        if not messagebox.askyesno('Удалить задачу', f'Удалить «{self.task.title}»?',
                                   parent=self.dialog):
            return
        self.service.delete(self.task)
        self._done()
