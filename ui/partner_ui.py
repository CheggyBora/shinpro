"""
Работы у партнёров — окна программы (решения владельца 13.11.2026,
макет https://claude.ai/artifact/DsTP91HvMYxR3sEPYN62kA).

  JobDialog       «+ Работа у партнёра»: партнёр, услуга (его постоянная
                  или своя), цена клиенту, цена партнёра, зарплата
  JobCard         карточка работы: статус и что дальше
  PayDialog       «Оплатить партнёру»: наличные (РКО) / безнал / другое
  PartnersWindow  «Оплата партнёрам»: что ждёт оплаты, оплатить пачкой
  OfferingDialog  постоянная услуга в карточке контрагента
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from services import partner_service as ps
from services.partner_service import PartnerService, PartnerError


def money(value):
    if value is None:
        return '—'
    return f'{value:,.0f} ₽'.replace(',', ' ')


def _people(db):
    from ui.shop_tab import people_on_shift
    return people_on_shift(db)


def _dialog(parent, title):
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=styles.COLORS['bg_card'])
    dialog.transient(parent.winfo_toplevel())
    body = ttk.Frame(dialog, style='White.TFrame')
    body.pack(fill='both', expand=True, padx=18, pady=14)
    return dialog, body


def _row(body, title):
    row = ttk.Frame(body, style='White.TFrame')
    row.pack(fill='x', pady=3)
    styles.create_label(row, title, 'Card.TLabel').pack(side='left')
    return row


class SalaryBlock:
    """Кому и сколько начислять с работы."""

    def __init__(self, parent, db, rule=None):
        rule = rule or {}
        self.people = _people(db)
        box = ttk.LabelFrame(parent, text='Зарплата с этой работы')
        box.pack(fill='x', pady=(8, 4))
        line = ttk.Frame(box)
        line.pack(fill='x', padx=8, pady=4)
        ttk.Label(line, text='Кому:').pack(side='left')
        self.to = tk.StringVar(value=rule.get('salary_to') or ps.SAL_NONE)
        for key, title in ps.SALARY_TO_TITLES.items():
            ttk.Radiobutton(line, text=title, value=key, variable=self.to,
                            command=self._redraw).pack(side='left', padx=(8, 0))
        self.people_row = ttk.Frame(box)
        self.marks = {}
        chosen = set()
        if rule.get('salary_people'):
            from services.salary_service import ids_of
            chosen = set(ids_of(rule['salary_people']))
        for person in self.people:
            self.marks[person.id] = tk.BooleanVar(value=person.id in chosen)
            ttk.Checkbutton(self.people_row, text=person.name or f'№{person.id}',
                            variable=self.marks[person.id]).pack(side='left', padx=(8, 0))
        self.how_row = ttk.Frame(box)
        ttk.Label(self.how_row, text='Как:').pack(side='left')
        self.mode = ttk.Combobox(self.how_row, state='readonly', width=18,
                                 values=list(ps.MODE_TITLES.values()))
        self.mode.set(ps.MODE_TITLES.get(rule.get('salary_mode') or ps.MODE_MARGIN_PCT))
        self.mode.pack(side='left', padx=(8, 8))
        ttk.Label(self.how_row, text='Сколько:').pack(side='left')
        self.value = styles.create_entry(self.how_row, width=8)
        if rule.get('salary_value'):
            self.value.insert(0, f"{rule['salary_value']:g}")
        self.value.pack(side='left', padx=(8, 0))
        ttk.Label(self.how_row, text='(% или ₽; «вся маржа» — не нужно)').pack(side='left', padx=(6, 0))
        self._redraw()

    def _redraw(self):
        to = self.to.get()
        self.people_row.pack_forget()
        self.how_row.pack_forget()
        if to == ps.SAL_PEOPLE:
            self.people_row.pack(fill='x', padx=8, pady=(0, 4))
        if to != ps.SAL_NONE:
            self.how_row.pack(fill='x', padx=8, pady=(0, 6))

    def rule(self):
        mode = next((k for k, v in ps.MODE_TITLES.items() if v == self.mode.get()), None)
        return {'salary_to': self.to.get(), 'salary_mode': mode,
                'salary_value': self.value.get().strip() or None,
                'salary_people': [pid for pid, var in self.marks.items() if var.get()]}


class JobDialog:
    """«+ Работа у партнёра» — из наряда (order) или отдельно."""

    def __init__(self, parent, db, order=None, on_saved=None, kind=ps.KIND_WORK,
                 our_price=None, name=None, note=None, plate=None, client_name=None,
                 client_phone=None):
        from services.calendar_service import CalendarService
        self.db, self.order, self.on_saved, self.note = db, order, on_saved, note
        self.service = PartnerService(db)
        self.parties = CalendarService(db).counterparties()
        self.dialog, body = _dialog(parent, 'Работа у партнёра')
        if not self.parties:
            styles.create_label(body, 'Контрагентов нет — заведите партнёра в «Календаре» → '
                                      '«Контрагенты».', 'Card.TLabel').pack()
            styles.create_button(body, 'Закрыть', self.dialog.destroy,
                                 'Secondary.TButton').pack(pady=(10, 0))
            return

        row = _row(body, 'Вид:')
        self.kind = tk.StringVar(value=kind)
        for key, title in ps.KIND_TITLES.items():
            ttk.Radiobutton(row, text=title, value=key, variable=self.kind,
                            command=self._kind_changed).pack(side='left', padx=(8, 0))
        row = _row(body, 'Партнёр:')
        self.party = ttk.Combobox(row, state='readonly', width=40,
                                  values=[p.name + (f' — {p.kind}' if p.kind else '') for p in self.parties])
        self.party.pack(side='left', padx=(8, 0))
        self.party.bind('<<ComboboxSelected>>', lambda e: self._party_changed())
        row = _row(body, 'Услуга:')
        self.offer = ttk.Combobox(row, width=40)
        self.offer.pack(side='left', padx=(8, 0))
        self.offer.bind('<<ComboboxSelected>>', lambda e: self._offer_changed())
        styles.create_label(body, 'Из списка партнёра — цены и зарплата подставятся; или напишите свою. '
                                  'Название — как в наряде и чеке.', 'Muted.TLabel').pack(anchor='w')
        if order is None:
            row = _row(body, 'Номер машины:')
            self.plate = styles.create_entry(row, width=14)
            self.plate.pack(side='left', padx=(8, 12))
            if plate:
                self.plate.insert(0, plate)
            styles.create_label(row, 'Клиент:', 'Card.TLabel').pack(side='left')
            self.client = styles.create_entry(row, width=18)
            self.client.pack(side='left', padx=(8, 12))
            if client_name:
                self.client.insert(0, client_name)
            styles.create_label(row, 'Телефон:', 'Card.TLabel').pack(side='left')
            self.phone = styles.create_entry(row, width=16)
            self.phone.pack(side='left', padx=(8, 0))
            if client_phone:
                self.phone.insert(0, client_phone)
        row = _row(body, 'Цена клиенту:')
        self.our = styles.create_entry(row, width=10)
        self.our.pack(side='left', padx=(8, 16))
        if our_price:
            self.our.insert(0, f'{our_price:g}')
        styles.create_label(row, 'Цена партнёра:', 'Card.TLabel').pack(side='left')
        self.theirs = styles.create_entry(row, width=10)
        self.theirs.pack(side='left', padx=(8, 8))
        styles.create_label(row, 'пусто — согласуем с партнёром', 'Muted.TLabel').pack(side='left')
        self.client_ok = tk.BooleanVar(value=kind in (ps.KIND_PAINT, ps.KIND_TIRES))
        ttk.Checkbutton(body, text='Цену согласовать с клиентом, когда партнёр назовёт свою',
                        variable=self.client_ok).pack(anchor='w', pady=(4, 0))
        row = _row(body, 'Оформил:')
        self.people = _people(db)
        self.creator = ttk.Combobox(row, state='readonly', width=26,
                                    values=[p.title for p in self.people])
        self.creator.pack(side='left', padx=(8, 0))
        if len(self.people) == 1:
            self.creator.set(self.people[0].title)
        self.salary = SalaryBlock(body, db)
        if name:
            self.offer.set(name)
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Оформить', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def _kind_changed(self):
        self.client_ok.set(self.kind.get() in (ps.KIND_PAINT, ps.KIND_TIRES))

    def _party(self):
        index = self.party.current()
        return self.parties[index] if index >= 0 else None

    def _party_changed(self):
        party = self._party()
        self.offerings = self.service.offerings(party.uid) if party else []
        self.offer.config(values=[o.name for o in self.offerings])

    def _offer_changed(self):
        chosen = next((o for o in getattr(self, 'offerings', []) if o.name == self.offer.get()), None)
        if chosen is None:
            return
        self.kind.set(chosen.kind or ps.KIND_WORK)
        self._kind_changed()
        for entry, value in ((self.our, chosen.our_price), (self.theirs, chosen.partner_price)):
            entry.delete(0, tk.END)
            if value is not None:
                entry.insert(0, f'{value:g}')
        rule = {'salary_to': chosen.salary_to, 'salary_mode': chosen.salary_mode,
                'salary_value': chosen.salary_value, 'salary_people': chosen.salary_people}
        self.salary.to.set(rule['salary_to'] or ps.SAL_NONE)
        self.salary.mode.set(ps.MODE_TITLES.get(rule['salary_mode'] or ps.MODE_MARGIN_PCT))
        self.salary.value.delete(0, tk.END)
        if rule['salary_value']:
            self.salary.value.insert(0, f"{rule['salary_value']:g}")
        self.salary._redraw()

    def save(self):
        party = self._party()
        creator = next((p for p in self.people if p.title == self.creator.get()), None)
        try:
            if party is None:
                raise PartnerError('Выберите партнёра')
            rule = self.salary.rule()
            if rule['salary_to'] == ps.SAL_CREATOR and creator is None:
                raise PartnerError('Выберите, кто оформил: ему начисляется')
            extra = {}
            if self.order is None:
                extra = dict(plate=self.plate.get().strip() or None,
                             client_name=self.client.get().strip() or None,
                             client_phone=self.phone.get().strip() or None)
            task = self.service.create_job(
                party.uid, self.offer.get(), self.our.get(), self.theirs.get().strip() or None,
                kind=self.kind.get(), order_id=self.order.id if self.order else None,
                salary=rule, creator_id=creator.id if creator else None,
                needs_client=self.client_ok.get(), note=self.note,
                created_by=creator.title if creator else None, **extra)
        except (PartnerError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Работа у партнёра', str(e), parent=self.dialog)
            return
        self.task = task
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved(task)


class JobCard:
    """Карточка работы: статус, цены, что дальше."""

    def __init__(self, parent, db, task, on_change=None):
        self.db, self.task, self.on_change, self.parent = db, task, on_change, parent
        self.service = PartnerService(db)
        self.dialog, self.body = _dialog(parent, f'Работа {ps.number_of(task)}')
        self.draw()
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def draw(self):
        from services.calendar_service import CalendarService
        for child in self.body.winfo_children():
            child.destroy()
        task = self.task
        party = CalendarService(self.db).counterparty(task.counterparty_uid)
        fg, bg = ps.STATUS_COLORS.get(task.partner_status, ('#334155', '#e2e8f0'))
        head = ttk.Frame(self.body, style='White.TFrame')
        head.pack(fill='x')
        styles.create_label(head, f'{ps.number_of(task)} · {task.title}', 'CardHeading.TLabel').pack(side='left')
        tk.Label(head, text=ps.STATUS_TITLES.get(task.partner_status, ''), fg=fg, bg=bg,
                 padx=10, pady=2, font=(styles.DEFAULT_FONT, 9, 'bold')).pack(side='right')
        info = (f'{ps.KIND_TITLES.get(task.partner_kind, "")} · партнёр: {party.name if party else "—"}'
                f' · наряд №{task.order_id or "—"}')
        styles.create_label(self.body, info, 'Card.TLabel').pack(anchor='w', pady=(4, 8))
        row = _row(self.body, 'Цена клиенту:')
        self.our = styles.create_entry(row, width=10)
        self.our.insert(0, f'{task.our_price or 0:g}')
        self.our.pack(side='left', padx=(8, 16))
        styles.create_label(row, 'Цена партнёра:', 'Card.TLabel').pack(side='left')
        self.theirs = styles.create_entry(row, width=10)
        if task.partner_price is not None:
            self.theirs.insert(0, f'{task.partner_price:g}')
        self.theirs.pack(side='left', padx=(8, 8))
        margin = (task.our_price or 0) - task.partner_price if task.partner_price is not None else None
        styles.create_label(row, f'маржа {money(margin)}', 'Muted.TLabel').pack(side='left')
        if task.partner_status not in (ps.ST_PAID, ps.ST_REFUSED):
            styles.create_button(self.body, 'Сохранить цены', self.save_prices,
                                 'Secondary.TButton').pack(anchor='w', pady=(4, 8))
        if task.pay_method:
            styles.create_label(self.body, f'Оплачено: {ps.PAY_TITLES.get(task.pay_method, "")}'
                                + (f' · {task.pay_note}' if task.pay_note else ''),
                                'Card.TLabel').pack(anchor='w')
        actions = ttk.Frame(self.body, style='White.TFrame')
        actions.pack(fill='x', pady=(8, 0))
        status = task.partner_status

        def button(text, command, style='Secondary.TButton'):
            styles.create_button(actions, text, command, style).pack(side='left', padx=(0, 6))

        if status == ps.ST_CLIENT:
            button('Клиент согласен', lambda: self.act(lambda: self.service.client_answer(task, True)),
                   'Primary.TButton')
            button('Клиент отказался', lambda: self.act(lambda: self.service.client_answer(task, False)))
        if status == ps.ST_WORK:
            button('Партнёр сделал', lambda: self.act(lambda: self.service.finish(task)), 'Primary.TButton')
        if status == ps.ST_WAIT:
            button('Оплатить партнёру…', self.pay, 'Success.TButton')
        if status in (ps.ST_AGREE, ps.ST_CLIENT, ps.ST_WORK):
            button('Отказ партнёра', self.refuse)
        styles.create_button(actions, 'Закрыть', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right')

    def act(self, what):
        try:
            what()
        except (PartnerError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Работа у партнёра', str(e), parent=self.dialog)
            return
        self.changed()

    def changed(self):
        self.db.refresh(self.task)
        self.draw()
        if self.on_change:
            self.on_change()

    def save_prices(self):
        def both():
            if (self.our.get().strip() or '0') != f'{self.task.our_price or 0:g}':
                self.service.set_our_price(self.task, self.our.get())
            theirs = self.theirs.get().strip()
            current = '' if self.task.partner_price is None else f'{self.task.partner_price:g}'
            if theirs != current:
                self.service.set_partner_price(self.task, theirs or None)
        self.act(both)

    def refuse(self):
        if messagebox.askyesno('Отказ', 'Партнёр не возьмётся? Работа закроется, строка уйдёт из '
                                        'неоплаченного наряда.', parent=self.dialog):
            self.act(lambda: self.service.refuse(self.task, 'партнёр не взялся'))

    def pay(self):
        PayDialog(self.dialog, self.db, [self.task], on_paid=self.changed)


class PayDialog:
    """«Оплатить партнёру»: наличные из кассы — РКО, безнал, другое."""

    def __init__(self, parent, db, tasks, on_paid=None):
        self.db, self.tasks, self.on_paid = db, list(tasks), on_paid
        self.dialog, body = _dialog(parent, 'Оплатить партнёру')
        total = sum(t.partner_price or 0 for t in self.tasks)
        styles.create_label(body, ', '.join(f'{ps.number_of(t)} {t.title}' for t in self.tasks),
                            'Card.TLabel').pack(anchor='w')
        styles.create_label(body, f'Сумма: {money(total)}', 'CardHeading.TLabel').pack(anchor='w', pady=(6, 8))
        self.method = tk.StringVar(value=ps.PAY_CASH)
        hints = {ps.PAY_CASH: 'проводится РКО, остаток в кассе уменьшится',
                 ps.PAY_NONCASH: 'расход по безналу записывается, наличные не трогаем',
                 ps.PAY_OTHER: 'ни касса, ни безнал не меняются — например, взаимозачёт'}
        for key, title in ps.PAY_TITLES.items():
            ttk.Radiobutton(body, text=f'{title} — {hints[key]}', value=key,
                            variable=self.method).pack(anchor='w', pady=2)
        row = _row(body, 'Пометка:')
        self.note = styles.create_entry(row, width=40)
        self.note.pack(side='left', padx=(8, 0))
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Оплачено', self.save, 'Success.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def save(self):
        try:
            PartnerService(self.db).pay(self.tasks, self.method.get(), self.note.get().strip() or None)
        except (PartnerError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Оплата партнёру', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_paid:
            self.on_paid()


class PartnersWindow:
    """«Оплата партнёрам» и все работы у партнёров."""

    COLUMNS = (('num', 'Работа', 70), ('title', 'Что', 240), ('party', 'Партнёр', 140),
               ('our', 'С клиента', 90), ('theirs', 'Партнёру', 90), ('margin', 'Маржа', 80),
               ('status', 'Статус', 170))

    def __init__(self, parent, db):
        self.db, self.parent = db, parent
        self.service = PartnerService(db)
        self.dialog, body = _dialog(parent, 'Работы у партнёров')
        self.dialog.geometry('980x520')
        top = ttk.Frame(body, style='White.TFrame')
        top.pack(fill='x')
        self.total = styles.create_label(top, '', 'CardHeading.TLabel')
        self.total.pack(side='left')
        self.only_wait = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text='только «ждёт оплаты»', variable=self.only_wait,
                        command=self.fill).pack(side='right')
        # Кнопки — снизу и первыми: длинный список не выдавит их за край
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(side='bottom', fill='x')
        self.tree = ttk.Treeview(body, columns=[c[0] for c in self.COLUMNS], show='headings',
                                 selectmode='extended', height=12)
        for key, title, width in self.COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w' if key in ('title', 'party') else 'center')
        self.tree.pack(fill='both', expand=True, pady=8)
        self.tree.bind('<Double-1>', lambda e: self.open_card())
        styles.create_button(buttons, 'Оплатить отмеченные…', self.pay, 'Success.TButton').pack(side='left')
        styles.create_button(buttons, '+ Работа у партнёра', self.new_job,
                             'Secondary.TButton').pack(side='left', padx=(8, 0))
        styles.create_label(buttons, 'Отметить несколько — Ctrl или Shift', 'Muted.TLabel').pack(
            side='left', padx=(12, 0))
        styles.create_button(buttons, 'Закрыть', self.dialog.destroy, 'Secondary.TButton').pack(side='right')
        self.fill()
        styles.center_window(self.dialog, parent.winfo_toplevel())

    def fill(self):
        from services.calendar_service import CalendarService
        calendar = CalendarService(self.db)
        self.tree.delete(*self.tree.get_children())
        rows = self.service.to_pay() if self.only_wait.get() else self.service.jobs()
        owe = 0.0
        for task in rows:
            party = calendar.counterparty(task.counterparty_uid)
            margin = (task.our_price or 0) - task.partner_price if task.partner_price is not None else None
            if task.partner_status == ps.ST_WAIT:
                owe += task.partner_price or 0
            self.tree.insert('', 'end', iid=task.uid, values=(
                ps.number_of(task), task.title, party.name if party else '—', money(task.our_price),
                money(task.partner_price) if task.partner_price is not None else 'не указана',
                money(margin), ps.STATUS_TITLES.get(task.partner_status, '')))
        waiting = sum(t.partner_price or 0 for t in self.service.to_pay())
        self.total.config(text=f'Оплата партнёрам: {money(waiting)}')

    def chosen(self):
        return [self.service.job(uid) for uid in self.tree.selection()]

    def pay(self):
        tasks = [t for t in self.chosen() if t is not None]
        if not tasks:
            messagebox.showinfo('Оплата партнёрам', 'Отметьте работы в списке.', parent=self.dialog)
            return
        PayDialog(self.dialog, self.db, tasks, on_paid=self.fill)

    def open_card(self):
        tasks = self.chosen()
        if tasks and tasks[0] is not None:
            JobCard(self.dialog, self.db, tasks[0], on_change=self.fill)

    def new_job(self):
        JobDialog(self.dialog, self.db, on_saved=lambda task: self.fill())


class OfferingDialog:
    """Постоянная услуга контрагента: цены и начисление по умолчанию."""

    def __init__(self, parent, db, counterparty_uid, offering=None, on_saved=None):
        self.db, self.party, self.offering, self.on_saved = db, counterparty_uid, offering, on_saved
        self.dialog, body = _dialog(parent, 'Услуга партнёра')
        row = _row(body, 'Название:')
        self.name = styles.create_entry(row, width=36)
        self.name.pack(side='left', padx=(8, 0))
        row = _row(body, 'Вид:')
        self.kind = tk.StringVar(value=offering.kind if offering else ps.KIND_WORK)
        for key, title in ps.KIND_TITLES.items():
            ttk.Radiobutton(row, text=title, value=key, variable=self.kind).pack(side='left', padx=(8, 0))
        row = _row(body, 'Наша цена:')
        self.our = styles.create_entry(row, width=10)
        self.our.pack(side='left', padx=(8, 16))
        styles.create_label(row, 'Цена партнёра:', 'Card.TLabel').pack(side='left')
        self.theirs = styles.create_entry(row, width=10)
        self.theirs.pack(side='left', padx=(8, 0))
        rule = {}
        if offering is not None:
            self.name.insert(0, offering.name)
            for entry, value in ((self.our, offering.our_price), (self.theirs, offering.partner_price)):
                if value is not None:
                    entry.insert(0, f'{value:g}')
            rule = {'salary_to': offering.salary_to, 'salary_mode': offering.salary_mode,
                    'salary_value': offering.salary_value, 'salary_people': offering.salary_people}
        self.salary = SalaryBlock(body, db, rule)
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Сохранить', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def save(self):
        try:
            PartnerService(self.db).save_offering(
                self.offering, counterparty_uid=self.party, name=self.name.get(), kind=self.kind.get(),
                our_price=self.our.get(), partner_price=self.theirs.get(), **self.salary.rule())
        except (PartnerError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Услуга партнёра', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()
