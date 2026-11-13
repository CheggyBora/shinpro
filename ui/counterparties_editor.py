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
          ('inn', 'ИНН'), ('telegram', 'Telegram'), ('note', 'Заметка')]


class CounterpartiesEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.service = CalendarService(db)
        self.current = None
        # У мойки свои контрагенты (химия, расходники) — отдельный слой
        self.direction = 'tire'
        from services import directions
        if directions.wash_on(db):
            switch = ttk.Frame(parent, style='White.TFrame')
            switch.pack(anchor='w', pady=(0, 8))
            self.direction_var = tk.StringVar(value='tire')
            for value, title in (('tire', 'Шиномонтаж'), ('wash', 'Мойка')):
                ttk.Radiobutton(switch, text=title, value=value, variable=self.direction_var,
                                command=self._switch).pack(side='left', padx=(0, 14))

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
        # Пишет ли контрагент боту — без этого личное сообщение не дойдёт
        self.telegram_hint = ttk.Label(form, text='', font=styles.FONTS['small'], wraplength=420,
                                       justify='left', background=styles.COLORS['bg_card'],
                                       foreground=styles.COLORS['text_secondary'])
        self.telegram_hint.grid(row=len(FIELDS), column=1, sticky='w', padx=(10, 0))
        buttons = ttk.Frame(right, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        styles.create_button(buttons, 'Сохранить', self.save, 'Primary.TButton').pack(side='left')
        styles.create_button(buttons, '+ Задача с ним', self.add_task,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.create_button(buttons, 'Удалить', self.delete,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        # Постоянные услуги партнёра (решение владельца 13.11.2026): цены и
        # начисление по умолчанию — в наряде подставятся сами
        styles.create_label(right, 'Его услуги (работы у партнёра)', 'Card.TLabel').pack(
            anchor='w', pady=(14, 4))
        self.offerings = ttk.Treeview(right, columns=('name', 'our', 'theirs', 'salary'),
                                      show='headings', height=4)
        for key, title, width in (('name', 'Услуга', 180), ('our', 'Наша', 70),
                                  ('theirs', 'Его', 70), ('salary', 'Зарплата', 200)):
            self.offerings.heading(key, text=title)
            self.offerings.column(key, width=width)
        self.offerings.pack(fill='x')
        self.offerings.bind('<Double-1>', lambda e: self.edit_offering())
        offer_buttons = ttk.Frame(right, style='White.TFrame')
        offer_buttons.pack(fill='x', pady=(4, 0))
        for title, command in (('+ Услуга', self.add_offering), ('Изменить', self.edit_offering),
                               ('Убрать', self.remove_offering), ('+ Работа у партнёра', self.new_job)):
            styles.create_button(offer_buttons, title, command,
                                 'Compact.Secondary.TButton').pack(side='left', padx=(0, 6))
        styles.create_label(right, 'Задачи и поставки', 'Card.TLabel').pack(anchor='w', pady=(14, 4))
        self.tasks = tk.Listbox(right, height=6, font=styles.FONTS['small'],
                                bg=styles.COLORS['bg_subtle'], relief='flat',
                                highlightthickness=1, highlightbackground=styles.COLORS['border'])
        self.tasks.pack(fill='x')
        self.refresh()

    def _switch(self):
        self.direction = self.direction_var.get()
        self.refresh()

    def refresh(self, select_uid=None):
        self.rows = self.service.counterparties(self.direction)
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
                value = getattr(row, key)
                entry.insert(0, '@' + value if key == 'telegram' else value)
        self._telegram_hint(row)
        self._fill_offerings()
        self.tasks.delete(0, tk.END)
        if row is not None:
            for task in self.service.tasks_of_counterparty(row.uid):
                mark = '✓ ' if task.done_at else ''
                self.tasks.insert(tk.END, f'{mark}{task.due_date:%d.%m.%y} · {task.title}')

    def _fill_offerings(self):
        from services import partner_service as ps
        from ui.partner_ui import money
        if not hasattr(self, 'offerings'):
            return
        self.offerings.delete(*self.offerings.get_children())
        if self.current is None:
            return
        for offer in ps.PartnerService(self.db).offerings(self.current.uid):
            if (offer.salary_to or ps.SAL_NONE) == ps.SAL_NONE:
                salary = 'никому'
            else:
                how = ps.MODE_TITLES.get(offer.salary_mode, '')
                value = '' if offer.salary_mode == ps.MODE_MARGIN_ALL else f' {offer.salary_value or 0:g}'
                salary = f'{ps.SALARY_TO_TITLES.get(offer.salary_to, "")}: {how}{value}'
            self.offerings.insert('', 'end', iid=offer.uid, values=(
                offer.name, money(offer.our_price), money(offer.partner_price), salary))

    def _need_party(self):
        if self.current is None:
            messagebox.showinfo('Контрагенты', 'Сначала выберите или сохраните контрагента',
                                parent=self.window)
            return False
        return True

    def add_offering(self):
        if not self._need_party():
            return
        from ui.partner_ui import OfferingDialog
        OfferingDialog(self.window, self.db, self.current.uid, on_saved=self._fill_offerings)

    def edit_offering(self):
        chosen = self.offerings.selection()
        if not chosen or not self._need_party():
            return
        from services.partner_service import PartnerService
        from ui.partner_ui import OfferingDialog
        OfferingDialog(self.window, self.db, self.current.uid,
                       PartnerService(self.db).offering(chosen[0]), on_saved=self._fill_offerings)

    def remove_offering(self):
        chosen = self.offerings.selection()
        if not chosen:
            return
        from services.partner_service import PartnerService
        service = PartnerService(self.db)
        offer = service.offering(chosen[0])
        if offer and messagebox.askyesno('Услуги партнёра', f'Убрать «{offer.name}»?', parent=self.window):
            service.delete_offering(offer)
            self._fill_offerings()

    def new_job(self):
        if not self._need_party():
            return
        from ui.partner_ui import JobDialog
        uid = self.current.uid
        dialog = JobDialog(self.window, self.db, on_saved=lambda task: self.refresh(select_uid=uid))
        if getattr(dialog, 'parties', None):
            index = next((i for i, p in enumerate(dialog.parties) if p.uid == uid), -1)
            if index >= 0:
                dialog.party.current(index)
                dialog._party_changed()

    def _telegram_hint(self, row):
        from services.telegram_service import TelegramService
        nick = row.telegram if row is not None else None
        if not nick:
            text = ('Ник в Telegram, например @ivan_shiny. Задача с этим контрагентом '
                    'придёт ему лично — если он нажал «Старт» у бота.')
        elif TelegramService(self.db).chat_of(nick):
            text = f'✓ @{nick} пишет боту — задачи с ним уходят ему в Telegram.'
        else:
            text = (f'@{nick} ещё не писал боту. Попросите открыть бота и нажать «Старт» — '
                    'задачи начнут приходить ему сами.')
        self.telegram_hint.config(text=text)

    def new(self):
        self.listbox.selection_clear(0, tk.END)
        self._fill(None)
        self.entries['name'].focus_set()

    def save(self):
        fields = {key: entry.get() for key, entry in self.entries.items()}
        fields['direction'] = self.direction
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
        open_task(self.window, self.db, counterparty_uid=uid,
                  category='tires' if self.direction == 'tire' else 'supply',
                  direction=self.direction, on_saved=lambda: self.refresh(select_uid=uid))
