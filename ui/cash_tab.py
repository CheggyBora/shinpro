"""
Раздел «Касса» (docs/cash.md): остаток наличных за смену, приходные и
расходные ордера, пересчёт при закрытии смены.

Серые строки — оплата картой и безнал: в списке видны, наличные не меняют.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from models.cash import KIND_IN, KIND_OUT, KIND_TITLES, METHOD_CASH, METHOD_NONCASH
from services.cash_service import CashService, CashError, money
from utils import as_naive


class CashTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = CashService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.shift = None
        self.on_changed = None
        self._build()
        self.load()

    def _build(self):
        card = styles.create_card_frame(self.frame)
        card.pack(fill='both', expand=True, padx=15, pady=15)
        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=16, pady=14)

        top = ttk.Frame(inner, style='White.TFrame')
        top.pack(fill='x')
        self.heading = styles.create_label(top, 'Касса', 'CardHeading.TLabel')
        self.heading.pack(side='left')
        styles.create_button(top, '− Расходный', lambda: self.new_order(KIND_OUT),
                             'Secondary.TButton').pack(side='right')
        styles.create_button(top, '+ Приходный', lambda: self.new_order(KIND_IN),
                             'Primary.TButton').pack(side='right', padx=(0, 6))
        self.shift_var = tk.StringVar()
        self.shift_box = ttk.Combobox(top, textvariable=self.shift_var, state='readonly', width=34)
        self.shift_box.pack(side='right', padx=(0, 12))
        self.shift_box.bind('<<ComboboxSelected>>', lambda e: self._pick_shift())

        self.tiles = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.tiles.pack(fill='x', pady=(12, 10))

        holder = ttk.Frame(inner, style='White.TFrame')
        holder.pack(fill='both', expand=True)
        columns = ('time', 'what', 'text', 'amount')
        self.tree = ttk.Treeview(holder, columns=columns, show='headings', height=15)
        for column, title, width, anchor in (('time', 'Время', 70, 'center'),
                                             ('what', 'Что', 150, 'w'),
                                             ('text', 'Статья / кто', 420, 'w'),
                                             ('amount', 'Сумма', 120, 'e')):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor)
        self.tree.tag_configure('grey', foreground='#94a3b8')
        self.tree.tag_configure('plus', foreground='#15803d')
        self.tree.tag_configure('minus', foreground='#b91c1c')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=scroll.set)
        self.tree.bind('<Double-1>', lambda e: self.open_selected())
        ttk.Label(inner, text='Двойной щелчок по ордеру — отменить ошибочный. '
                              'Серые строки — карта и безнал: наличные в кассе не меняют.',
                  font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w', pady=(6, 0))

    def _shifts(self):
        from models import Shift
        return self.db.query(Shift).order_by(Shift.id.desc()).limit(40).all()

    @staticmethod
    def _shift_title(shift):
        start = as_naive(shift.start_time)
        when = start.strftime('%d.%m.%Y %H:%M') if start else ''
        return f'Смена №{shift.id} · {when}' + (' · открыта' if shift.status == 'open' else '')

    def _pick_shift(self):
        titles = self.shift_box['values']
        chosen = self.shift_var.get()
        if chosen in titles:
            self.shift = self._shift_list[list(titles).index(chosen)]
            self.load(keep=True)

    def load(self, keep=False):
        try:
            self._shift_list = self._shifts()
        except Exception:
            self.db.rollback()
            return
        titles = [self._shift_title(s) for s in self._shift_list]
        self.shift_box['values'] = titles
        if not keep or self.shift not in self._shift_list:
            current = self.service.current_shift()
            self.shift = current or (self._shift_list[0] if self._shift_list else None)
        if self.shift is not None and self.shift in self._shift_list:
            self.shift_var.set(titles[self._shift_list.index(self.shift)])
        self._draw()

    def _tile(self, title, value, color=None, main=False):
        bg = styles.COLORS['primary_soft'] if main else '#f1f5f9'
        box = tk.Frame(self.tiles, bg=bg, padx=12, pady=8)
        box.pack(side='left', padx=(0, 8), fill='x', expand=True)
        tk.Label(box, text=title, bg=bg, fg=styles.COLORS['text_secondary'],
                 font=styles.FONTS['small']).pack(anchor='w')
        tk.Label(box, text=value, bg=bg, fg=color or styles.COLORS['text'],
                 font=(styles.DEFAULT_FONT, 15, 'bold')).pack(anchor='w')

    def _draw(self):
        for child in self.tiles.winfo_children():
            child.destroy()
        for row in self.tree.get_children():
            self.tree.delete(row)
        self._rows = {}
        if self.shift is None:
            tk.Label(self.tiles, text='Смен ещё не было — откройте смену в «Сотрудниках».',
                     bg=styles.COLORS['bg_card'], fg=styles.COLORS['text_secondary']).pack(anchor='w')
            return
        totals = self.service.totals(self.shift)
        self._tile('На начало смены', money(totals['start']) if self.shift.cash_start is not None else 'не вводили')
        self._tile('Пришло наличными', '+ ' + money(totals['came']), '#15803d')
        self._tile('Ушло', '− ' + money(totals['went']), '#b91c1c')
        if self.shift.status == 'open':
            self._tile('Должно быть в кассе', money(totals['expected']), styles.COLORS['primary'], main=True)
        elif self.shift.cash_counted is not None:
            diff = self.shift.cash_diff or 0
            text = money(self.shift.cash_counted) + (
                f'  ({"+" if diff > 0 else "−"} {money(abs(diff))})' if diff else '  · сошлось')
            self._tile('Пересчитали при закрытии', text, '#b91c1c' if diff < 0 else
                       ('#a16207' if diff > 0 else '#15803d'), main=True)
        else:
            self._tile('Должно было быть', money(totals['expected']), main=True)

        for n, line in enumerate(self.service.lines(self.shift)):
            when = line['time'].strftime('%H:%M') if line['time'] else ''
            effect = line['effect']
            if line['tag'] == 'start':
                amount, tag = money(line['amount']), ''
            elif effect > 0:
                amount, tag = '+ ' + money(effect), 'plus'
            elif effect < 0:
                amount, tag = '− ' + money(-effect), 'minus'
            else:
                amount, tag = money(line['amount']), 'grey'
            iid = f'l{n}'
            self.tree.insert('', 'end', iid=iid, values=(when, line['what'], line['text'], amount),
                             tags=(tag,) if tag else ())
            self._rows[iid] = line['order']

    def _changed(self):
        self.load(keep=True)
        if self.on_changed:
            self.on_changed()

    def new_order(self, kind):
        if self.service.current_shift() is None:
            messagebox.showinfo('Касса', 'Сначала откройте смену', parent=self.frame)
            return
        CashOrderDialog(self.frame, self.db, kind, self._changed)

    def open_selected(self):
        chosen = self.tree.selection()
        row = self._rows.get(chosen[0]) if chosen else None
        if row is None:
            return
        if row.reverses_id:
            messagebox.showinfo('Касса', 'Это отмена ордера — её не отменяют.', parent=self.frame)
            return
        if self.service.is_reversed(row):
            messagebox.showinfo('Касса', f'Ордер №{row.number} уже отменён.', parent=self.frame)
            return
        if row.payout_id:
            messagebox.showinfo('Касса', 'Это выдача зарплаты. Отменить её можно в «Сотрудниках» — '
                                         'ордер отменится сам.', parent=self.frame)
            return
        title = f'{KIND_TITLES[row.kind]} ордер №{row.number}'
        if not messagebox.askyesno('Касса', f'{title}\n{row.category}, {money(row.amount)}'
                                            f'{" · " + row.note if row.note else ""}\n\n'
                                            'Отменить? Будет проведён обратный ордер, '
                                            'в списке останутся оба.', parent=self.frame):
            return
        try:
            self.service.reverse(row, employee_id=_on_shift_default(self.db))
        except CashError as e:
            self.db.rollback()
            messagebox.showerror('Касса', str(e), parent=self.frame)
            return
        self._changed()


def _on_shift(db):
    """[(id, имя)] — кто сейчас на смене: выдаёт и вносит один из них."""
    try:
        from services.employee_service import EmployeeService
        people = EmployeeService(db)._on_shift()
        return [(e.id, e.title) for e in people]
    except Exception:
        db.rollback()
        return []


def _on_shift_default(db):
    people = _on_shift(db)
    return people[0][0] if len(people) == 1 else None


class CashOrderDialog:
    """Приходный или расходный ордер — одно окно, отличается заголовком."""

    def __init__(self, parent, db, kind, on_saved=None):
        self.db = db
        self.service = CashService(db)
        self.kind = kind
        self.on_saved = on_saved
        number = self.service._next_number(kind)
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f'{KIND_TITLES[kind]} ордер')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=14)
        styles.create_label(body, f'{KIND_TITLES[kind]} ордер №{number}',
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 8))
        form = ttk.Frame(body, style='White.TFrame')
        form.pack(fill='x')

        def label(row, text):
            styles.create_label(form, text, 'Card.TLabel').grid(row=row, column=0, sticky='nw',
                                                                pady=4, padx=(0, 12))

        label(0, 'Статья')
        self.category = tk.StringVar()
        cats = ttk.Frame(form, style='White.TFrame')
        cats.grid(row=0, column=1, sticky='w')
        for n, name in enumerate(self.service.categories(kind)):
            ttk.Radiobutton(cats, text=name, value=name, variable=self.category).grid(
                row=n // 3, column=n % 3, sticky='w', padx=(0, 12))

        label(1, 'Сумма, ₽')
        self.amount = styles.create_entry(form, width=14)
        self.amount.grid(row=1, column=1, sticky='w', pady=4)

        label(2, 'Чем')
        self.method = tk.StringVar(value=METHOD_CASH)
        ways = ttk.Frame(form, style='White.TFrame')
        ways.grid(row=2, column=1, sticky='w')
        cash_text = 'Наличные из кассы' if kind == KIND_OUT else 'Наличные в кассу'
        ttk.Radiobutton(ways, text=cash_text, value=METHOD_CASH, variable=self.method).pack(side='left', padx=(0, 12))
        ttk.Radiobutton(ways, text='Безнал — касса не меняется', value=METHOD_NONCASH,
                        variable=self.method).pack(side='left')

        label(3, 'Кому / за что' if kind == KIND_OUT else 'От кого / за что')
        self.note = styles.create_entry(form, width=40)
        self.note.grid(row=3, column=1, sticky='w', pady=4)

        label(4, 'Кто выдал' if kind == KIND_OUT else 'Кто принял')
        self.people = _on_shift(db)
        self.who = tk.StringVar(value=self.people[0][1] if len(self.people) == 1 else '')
        ttk.Combobox(form, textvariable=self.who, values=[p[1] for p in self.people],
                     state='readonly', width=24).grid(row=4, column=1, sticky='w', pady=4)

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Провести', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()
        self.amount.focus_set()

    def save(self):
        who = next((pid for pid, name in self.people if name == self.who.get()), None)
        try:
            self.service.create(self.kind, self.category.get(), self.amount.get(),
                                self.method.get(), note=self.note.get(), employee_id=who)
        except CashError as e:
            self.db.rollback()
            messagebox.showerror('Касса', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()


def ask_start(parent, db):
    """
    Открытие смены: сколько наличных фактически в кассе. Возвращает
    сумму или None — передумали.
    """
    from tkinter import simpledialog
    suggested = CashService(db).suggested_start()
    while True:
        value = simpledialog.askstring(
            'Касса', 'Сколько наличных сейчас в кассе? Пересчитайте.'
            + (f'\nПри закрытии прошлой смены было {money(suggested)}.' if suggested is not None else ''),
            initialvalue=f'{suggested:.0f}' if suggested is not None else '', parent=parent)
        if value is None:
            return None
        try:
            from services.cash_service import parse_amount
            return parse_amount(value)
        except CashError as e:
            messagebox.showerror('Касса', str(e), parent=parent)


class CountDialog:
    """
    Закрытие смены: пересчёт кассы обязателен. ok — сумму ввели и
    сохранили, можно закрывать смену.
    """

    def __init__(self, parent, db, shift):
        self.db = db
        self.service = CashService(db)
        self.shift = shift
        self.ok = False
        self.expected = self.service.expected(shift)
        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Закрытие смены · касса')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=14)
        styles.create_label(body, 'Пересчитайте наличные в кассе', 'CardHeading.TLabel').pack(anchor='w')
        styles.create_label(body, f'Должно быть: {money(self.expected)}', 'Card.TLabel').pack(anchor='w', pady=(8, 8))
        styles.create_label(body, 'Пересчитали, ₽', 'Card.TLabel').pack(anchor='w')
        self.counted = styles.create_entry(body, width=14)
        self.counted.pack(anchor='w', pady=(0, 8))
        self.counted.bind('<KeyRelease>', lambda e: self._diff())
        self.diff = tk.Label(body, text='', bg=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 11, 'bold'))
        self.diff.pack(anchor='w')
        self.reason_label = styles.create_label(body, 'Причина расхождения', 'Card.TLabel')
        self.reason = styles.create_entry(body, width=40)
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(side='bottom', fill='x', pady=(12, 0))
        self.buttons = buttons
        styles.create_button(buttons, 'Закрыть смену', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()
        self.counted.focus_set()

    def _value(self):
        from services.cash_service import parse_amount
        try:
            return parse_amount(self.counted.get()) if self.counted.get().strip() else None
        except CashError:
            return None

    def _diff(self):
        value = self._value()
        if value is None:
            self.diff.config(text='')
            self.reason_label.pack_forget()
            self.reason.pack_forget()
            return
        diff = round(value - self.expected, 2)
        if not diff:
            self.diff.config(text='Сошлось', fg='#15803d')
            self.reason_label.pack_forget()
            self.reason.pack_forget()
            return
        word = 'Недостача' if diff < 0 else 'Излишек'
        self.diff.config(text=f'{word}: {money(abs(diff))}', fg='#b91c1c' if diff < 0 else '#a16207')
        self.reason_label.pack(anchor='w', pady=(8, 0))
        self.reason.pack(anchor='w')

    def save(self):
        if self._value() is None:
            messagebox.showerror('Касса', 'Введите, сколько наличных пересчитали', parent=self.dialog)
            return
        try:
            self.service.count(self.shift, self.counted.get(), self.reason.get())
        except CashError as e:
            self.db.rollback()
            messagebox.showerror('Касса', str(e), parent=self.dialog)
            return
        self.ok = True
        self.dialog.destroy()


class CategoriesEditor:
    """Статьи прихода и расхода: добавить, убрать, переставить."""

    def __init__(self, parent, db):
        self.db = db
        self.service = CashService(db)
        self.frame = ttk.Frame(parent, style='White.TFrame')
        for kind, title in ((KIND_OUT, 'Статьи расхода'), (KIND_IN, 'Статьи прихода')):
            box = ttk.Frame(self.frame, style='White.TFrame')
            box.pack(side='left', fill='y', padx=(0, 24), anchor='n')
            styles.create_label(box, title, 'Card.TLabel').pack(anchor='w')
            listbox = tk.Listbox(box, height=7, width=24, exportselection=False,
                                 font=styles.FONTS['normal'])
            listbox.pack(anchor='w', pady=(4, 4))
            for name in self.service.categories(kind):
                listbox.insert(tk.END, name)
            row = ttk.Frame(box, style='White.TFrame')
            row.pack(anchor='w')
            styles.create_button(row, '+ Статья', lambda k=kind, l=listbox: self.add(k, l),
                                 'Secondary.TButton').pack(side='left')
            styles.create_button(row, 'Убрать', lambda k=kind, l=listbox: self.remove(k, l),
                                 'Secondary.TButton').pack(side='left', padx=(6, 0))

    def _save(self, kind, listbox):
        try:
            self.service.set_categories(kind, listbox.get(0, tk.END))
            return True
        except CashError as e:
            messagebox.showerror('Касса', str(e), parent=self.frame)
            return False

    def add(self, kind, listbox):
        from tkinter import simpledialog
        name = simpledialog.askstring('Касса', 'Название статьи:', parent=self.frame)
        name = (name or '').strip()
        if not name or name in listbox.get(0, tk.END):
            return
        listbox.insert(tk.END, name)
        self._save(kind, listbox)

    def remove(self, kind, listbox):
        chosen = listbox.curselection()
        if not chosen:
            return
        if listbox.size() == 1:
            messagebox.showerror('Касса', 'Нужна хотя бы одна статья', parent=self.frame)
            return
        listbox.delete(chosen[0])
        self._save(kind, listbox)
