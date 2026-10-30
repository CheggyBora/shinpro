"""
Окно записи календаря: задача или комментарий.

Задача — с галочкой «сделано»: висит в ленте над нарядами, краснеет,
если просрочена, и переходит на завтра. Комментарий — просто запись на
день: без галочки, не напоминает (решение владельца 29.10.2026).

Открывается из ленты над нарядами, из календаря, из наряда машины и
из карточки контрагента. Менять можно всё — задачу ставили второпях, а
поставка сдвинулась (docs/calendar.md).
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from models.calendar import (CATEGORIES, CATEGORY_TITLES, CATEGORY_COLORS, WORK, categories_of,
                             KIND_TASK, KIND_NOTE)
from services.calendar_service import CalendarService, TaskError
from ui.plate_picker import PlatePicker, owner_of, owner_text
from utils import get_moscow_time, as_naive

SOURCE_TITLES = {'shop': 'цех', 'dashboard': 'дашборд', 'auto': 'программа',
                 'cabinet': 'кабинет клиента'}

# Комментарий — серым: это не дело, а запись на день
NOTE_COLORS = ('#475569', '#f1f5f9')

WHO = 'Цех'
KIND_TITLES = {KIND_TASK: 'Задача', KIND_NOTE: 'Комментарий'}


def open_task(parent, db, task=None, on_saved=None, **defaults):
    return TaskDialog(parent, db, task, on_saved, defaults)


def time_text(task):
    """«11:00–12:30», «14:00» или пусто."""
    if not task.due_time:
        return ''
    return task.due_time + (f'–{task.end_time}' if task.end_time else '')


class TaskDialog:
    def __init__(self, parent, db, task=None, on_saved=None, defaults=None):
        self.db = db
        self.service = CalendarService(db)
        self.task = task
        self.on_saved = on_saved
        defaults = defaults or {}
        self.kind = (task.kind if task is not None else defaults.pop('kind', None)) or KIND_TASK

        self.dialog = tk.Toplevel(parent)
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=16)
        self.body = body

        # Задача или комментарий — переключатель сверху, как в макете
        self.kind_row = tk.Frame(body, bg=styles.COLORS['border'], padx=1, pady=1)
        self.kind_row.pack(anchor='w', pady=(0, 12))
        self.kind_buttons = {}
        for key in (KIND_TASK, KIND_NOTE):
            button = tk.Label(self.kind_row, text=KIND_TITLES[key], padx=20, pady=5, cursor='hand2',
                              font=(styles.DEFAULT_FONT, 11))
            button.pack(side='left', padx=(0 if key == KIND_TASK else 1, 0))
            button.bind('<Button-1>', lambda e, k=key: self.set_kind(k))
            self.kind_buttons[key] = button

        form = ttk.Frame(body, style='White.TFrame')
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.form = form
        self.rows = {}

        def label(row, text):
            widget = styles.create_label(form, text, 'Card.TLabel')
            widget.grid(row=row, column=0, sticky='nw', pady=4, padx=(0, 12))
            self.rows[row] = [widget]
            return widget

        def place(row, widget, **grid):
            widget.grid(row=row, column=1, pady=4, **grid)
            self.rows[row].append(widget)
            return widget

        today = as_naive(get_moscow_time()).date()

        # Шиномонтаж или мойка. Календарь один на оба направления, и чтобы
        # задача случайно не попала не туда, у новой задачи направление
        # выбирают сами — заранее ничего не отмечено (кроме случаев, когда
        # оно понятно: фильтр «Мойка», карточка контрагента мойки)
        from services import directions as _directions
        self.wash = _directions.wash_on(db) or (task is not None and task.direction == 'wash')
        if task is not None:
            self.direction = task.direction or 'tire'
        elif self.wash:
            self.direction = defaults.get('direction')
        else:
            self.direction = 'tire'
        if self.wash:
            where = ttk.Frame(body, style='White.TFrame')
            where.pack(fill='x', before=form, pady=(0, 8))
            styles.create_label(where, 'Где*', 'Card.TLabel').pack(side='left', padx=(0, 12))
            if task is not None:
                styles.create_label(where, _directions.TITLES[self.direction],
                                    'CardHeading.TLabel').pack(side='left')
            else:
                self.direction_var = tk.StringVar(value=self.direction or '')
                for value in (_directions.TIRE, _directions.WASH):
                    ttk.Radiobutton(where, text=_directions.TITLES[value], value=value,
                                    variable=self.direction_var,
                                    command=self._direction_chosen).pack(side='left', padx=(0, 14))

        label(0, 'Дата')
        self.day = place(0, styles.create_entry(form, width=12), sticky='w')
        day = task.due_date if task else defaults.get('due_date', today)
        self.day.insert(0, day.strftime('%d.%m.%Y'))

        label(1, 'Время')
        when = place(1, ttk.Frame(form, style='White.TFrame'), sticky='w')
        styles.create_label(when, 'с', 'Card.TLabel').pack(side='left', padx=(0, 6))
        self.time = styles.create_entry(when, width=7)
        self.time.pack(side='left')
        self.time.insert(0, (task.due_time if task else defaults.get('due_time')) or '')
        styles.create_label(when, 'до', 'Card.TLabel').pack(side='left', padx=(10, 6))
        self.end_time = styles.create_entry(when, width=7)
        self.end_time.pack(side='left')
        self.end_time.insert(0, (task.end_time if task else defaults.get('end_time')) or '')
        ttk.Label(when, text='можно не ставить — будет «без времени»', font=styles.FONTS['small'],
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(side='left', padx=(10, 0))

        label(2, 'Раздел')
        self.category = tk.StringVar(value=task.category if task else defaults.get('category', WORK))
        self.cats = place(2, ttk.Frame(form, style='White.TFrame'), sticky='w')
        self._draw_categories()

        label(3, 'Машина')
        car_row = place(3, ttk.Frame(form, style='White.TFrame'), sticky='w')
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

        label(4, 'Контрагент')
        self.parties = self.service.counterparties(self.direction) if self.direction else []
        names = ['—'] + [c.name for c in self.parties]
        self.party = tk.StringVar(value='—')
        uid = task.counterparty_uid if task else defaults.get('counterparty_uid')
        chosen = next((c for c in self.parties if c.uid == uid), None)
        if chosen is not None:
            self.party.set(chosen.name)
        self.party_box = place(4, ttk.Combobox(form, textvariable=self.party, values=names,
                                               state='readonly', width=30,
                                               font=styles.FONTS['normal']), sticky='w')
        self.party_box.bind('<<ComboboxSelected>>', lambda e: self._party_chosen())

        label(5, 'Что сделать')
        self.title = place(5, styles.create_entry(form, width=48), sticky='we')
        self.title.insert(0, (task.title if task else defaults.get('title')) or '')

        label(6, 'Подробно')
        self.note = place(6, tk.Text(form, height=4, width=48, wrap='word',
                                     font=styles.FONTS['normal'], relief='solid', borderwidth=1),
                          sticky='we')
        self.note.insert('1.0', (task.note if task else defaults.get('note')) or '')

        label(7, 'Сумма, ₽')
        self.amount = place(7, styles.create_entry(form, width=12), sticky='w')
        amount = task.amount if task else defaults.get('amount')
        if amount:
            self.amount.insert(0, f'{amount:g}')

        # Комментарий — одно поле текста. Длинный целиком лежит в «note»,
        # в заголовке — его начало: его и видно в календаре
        label(8, 'Комментарий')
        self.comment = place(8, tk.Text(form, height=5, width=48, wrap='word',
                                        font=styles.FONTS['normal'], relief='solid', borderwidth=1),
                             sticky='we')
        if task is not None and task.kind == KIND_NOTE:
            self.comment.insert('1.0', task.note or task.title or '')

        # Кому сообщить в Telegram — только у новой задачи: она уходит
        # один раз, при сохранении (решение владельца 30.10.2026)
        self.notify_vars = {}
        self.notify_touched = False
        self.personal_var = None
        if task is None:
            label(9, 'Уведомить')
            self.notify_box = place(9, tk.Frame(form, bg='#f8fafc', highlightthickness=1,
                                                highlightbackground=styles.COLORS['border']),
                                    sticky='w')
            self._draw_notify()

        self.hint = ttk.Label(body, font=styles.FONTS['small'], wraplength=560, justify='left',
                              foreground=styles.COLORS['text_secondary'],
                              background=styles.COLORS['bg_card'])
        self.hint.pack(anchor='w', pady=(10, 0))

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
        self.done_button = None
        if task is not None:
            self.done_button = styles.create_button(
                buttons, 'Вернуть в работу' if task.done_at else '✓ Сделано',
                self.toggle_done, 'Success.TButton')
            self.done_button.pack(side='left')
            self.delete_button = styles.create_button(buttons, 'Удалить', self.delete,
                                                      'Secondary.TButton')
            self.delete_button.pack(side='left', padx=(6, 0))
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

        self.set_kind(self.kind)
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    # ------------------------------------------------------------------

    def set_kind(self, kind):
        """Переключить вид: у комментария — только дата, время и текст."""
        # Текст переносим из одного вида в другой: передумали — не набирать заново
        if kind != self.kind:
            if kind == KIND_NOTE:
                text = self.title.get().strip()
                more = self.note.get('1.0', 'end').strip()
                self.comment.delete('1.0', 'end')
                self.comment.insert('1.0', '\n'.join(t for t in (text, more) if t))
            else:
                text = self.comment.get('1.0', 'end').strip()
                first, _, rest = text.partition('\n')
                self.title.delete(0, 'end')
                self.title.insert(0, first[:200])
                self.note.delete('1.0', 'end')
                self.note.insert('1.0', rest.strip())
        self.kind = kind
        note = kind == KIND_NOTE
        for key, button in self.kind_buttons.items():
            on = key == kind
            button.config(bg=styles.COLORS['primary'] if on else styles.COLORS['bg_card'],
                          fg='white' if on else styles.COLORS['text_secondary'],
                          font=(styles.DEFAULT_FONT, 11, 'bold' if on else 'normal'))
        for row, widgets in self.rows.items():
            shown = row in (0, 1, 8) if note else row != 8
            for widget in widgets:
                if shown:
                    widget.grid()
                else:
                    widget.grid_remove()
        if self.done_button is not None:
            if note:
                self.done_button.pack_forget()
            elif not self.done_button.winfo_manager():
                self.done_button.pack(side='left', before=self.delete_button)
        self.hint.config(text=(
            'Комментарий — просто запись на день: без галочки, не напоминает, не краснеет '
            'и никуда не переходит. Видят все — в цеху и в дашборде.' if note else
            'Задача — с галочкой «сделано». Сразу уходит в Telegram, висит в ленте над '
            'нарядами, краснеет, если просрочена, и переходит на завтра, пока её не отметят.'))
        if self.task is None:
            self.dialog.title('Новый комментарий' if note else 'Новая задача')
        else:
            self.dialog.title('Комментарий' if note else 'Задача')
        (self.comment if note else self.title).focus_set()

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

    def _draw_categories(self):
        for child in self.cats.winfo_children():
            child.destroy()
        if not self.direction:
            ttk.Label(self.cats, text='— появится после выбора направления —',
                      font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                      background=styles.COLORS['bg_card']).pack(side='left')
            return
        if self.category.get() not in categories_of(self.direction):
            self.category.set(WORK)
        for key in categories_of(self.direction):
            ttk.Radiobutton(self.cats, text=CATEGORY_TITLES[key], value=key,
                            variable=self.category,
                            command=self._category_chosen).pack(side='left', padx=(0, 10))

    def _category_chosen(self):
        # Раздел поменяли, а людей руками не трогали — отмечаем по разделу
        if getattr(self, 'notify_box', None) is not None and not self.notify_touched:
            self._draw_notify()

    def _people(self):
        """Все, кому бот может написать: нажавшие «Старт» и люди из «Доступа»."""
        from services.telegram_service import TelegramService
        telegram = TelegramService(self.db)
        people = [r for r in telegram.get_recipients() if r.chat_id]
        known = {r.chat_id for r in people}
        for kind in ('task',):
            people += [r for r in telegram.staff_recipients(kind) if r.chat_id not in known]
        return people

    def _draw_notify(self):
        """
        Люди с галочками: отмечены те, кому идёт раздел задачи (Настройки →
        Telegram). Можно снять и добавить — только для этой задачи.
        """
        box = self.notify_box
        for child in box.winfo_children():
            child.destroy()
        people = self._people()
        if not people:
            tk.Label(box, text='Telegram не настроен — Настройки → Telegram', bg='#f8fafc',
                     fg=styles.COLORS['text_secondary'], font=styles.FONTS['small']).pack(
                anchor='w', padx=8, pady=4)
            self.notify_vars = {}
            self._draw_personal()
            return
        chosen = set(self.service.notify_defaults(self.category.get() or WORK))
        if self.notify_touched:
            # Отмечали руками — отметки не сбиваем
            chosen = {chat for chat, var in self.notify_vars.items() if var.get()}
        # Выбранный контрагент — строкой «лично» ниже, не дважды
        party = next((c for c in self.parties if c.name == self.party.get()), None)
        nick = (party.telegram or '').lower() if party is not None else ''
        people = [p for p in people if not nick or p.username != nick]
        self.notify_vars = {}
        for person in people:
            var = tk.BooleanVar(value=person.chat_id in chosen)
            self.notify_vars[person.chat_id] = var
            text = person.title + (f'  @{person.username}' if person.username else '')
            tk.Checkbutton(box, text=text, variable=var, bg='#f8fafc', anchor='w',
                           activebackground='#f8fafc', font=styles.FONTS['normal'],
                           command=self._touched).pack(fill='x', padx=6)
        self._draw_personal()

    def _party_chosen(self):
        if getattr(self, 'notify_box', None) is not None:
            self._draw_notify()

    def _touched(self):
        self.notify_touched = True

    def _draw_personal(self):
        """Контрагент с ником — ему лично, отдельной строкой."""
        box = getattr(self, 'notify_box', None)
        if box is None:
            return
        for child in box.winfo_children():
            if getattr(child, 'personal', False):
                child.destroy()
        party = next((c for c in self.parties if c.name == self.party.get()), None)
        self.personal_var = None
        if party is None or not party.telegram or party.deleted:
            return
        self.personal_var = tk.BooleanVar(value=True)
        line = tk.Checkbutton(box, text=f'Контрагенту лично: {party.name}  @{party.telegram}',
                              variable=self.personal_var, bg='#f8fafc', anchor='w',
                              activebackground='#f8fafc', font=styles.FONTS['normal'])
        line.personal = True
        line.pack(fill='x', padx=6)

    def _direction_chosen(self):
        self.direction = self.direction_var.get() or None
        self._draw_categories()
        self.parties = self.service.counterparties(self.direction) if self.direction else []
        self.party.set('—')
        self.party_box.config(values=['—'] + [c.name for c in self.parties])
        self._category_chosen()
        self._draw_personal()

    def fields(self):
        times = dict(due_date=self.day.get(), due_time=self.time.get(),
                     end_time=self.end_time.get(), kind=self.kind)
        if self.kind == KIND_NOTE:
            text = self.comment.get('1.0', 'end').strip()
            first = text.split('\n', 1)[0][:200]
            # Короткий однострочный — только заголовок; длинный — целиком в note
            return dict(times, title=first, note=text if text != first else None,
                        category=self.category.get() if self.direction else WORK)
        amount = self.amount.get().strip().replace(' ', '').replace(',', '.')
        try:
            amount = float(amount) if amount else None
        except ValueError:
            raise TaskError('Сумма — числом, например 18700')
        party = next((c for c in self.parties if c.name == self.party.get()), None)
        return dict(
            times, category=self.category.get(), title=self.title.get(),
            note=self.note.get('1.0', 'end').strip() or None,
            license_plate=self.plate.get() or None,
            client_name=self.client_name if self.plate.get() else None,
            client_phone=self.client_phone if self.plate.get() else None,
            counterparty_uid=party.uid if party else None, amount=amount)

    def _done(self):
        if self.on_saved:
            self.on_saved()
        self.dialog.destroy()

    def _title(self):
        return KIND_TITLES[self.kind]

    def save(self):
        if not self.direction:
            messagebox.showerror(self._title(), 'Выберите, шиномонтаж это или мойка',
                                 parent=self.dialog)
            return
        try:
            fields = self.fields()
            # Новая задача (или комментарий, который сделали задачей) —
            # сразу в Telegram; комментарий просто записывается
            announce = self.kind == KIND_TASK and (self.task is None or self.task.kind == KIND_NOTE)
            if self.task is None:
                self.task = self.service.create(created_by=WHO, direction=self.direction, **fields)
            else:
                self.service.update(self.task, **fields)
            if announce:
                # Отмеченные в «Уведомить»; окна не было (задачу сделали
                # из комментария) — по разделу, как настроено
                chats = ([chat for chat, var in self.notify_vars.items() if var.get()]
                         if self.notify_vars else None)
                personal = self.personal_var.get() if self.personal_var is not None else True
                try:
                    self.service.announce(self.task, chats=chats, personal=personal)
                except Exception as e:
                    self.db.rollback()
                    from logger import log
                    log.error(f'Задача не встала в очередь Telegram: {e}')
        except TaskError as e:
            messagebox.showerror(self._title(), str(e), parent=self.dialog)
            return
        except Exception as e:
            self.db.rollback()
            messagebox.showerror(self._title(), f'Не удалось сохранить: {e}', parent=self.dialog)
            return
        self._done()

    def move(self, **kwargs):
        try:
            self.service.move(self.task, **kwargs)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror(self._title(), f'Не удалось перенести: {e}', parent=self.dialog)
            return
        self._done()

    def toggle_done(self):
        self.service.set_done(self.task, not self.task.done_at, by=WHO)
        self._done()

    def delete(self):
        what = 'комментарий' if self.kind == KIND_NOTE else 'задачу'
        if not messagebox.askyesno(f'Удалить {what}', f'Удалить «{self.task.title}»?',
                                   parent=self.dialog):
            return
        self.service.delete(self.task)
        self._done()
