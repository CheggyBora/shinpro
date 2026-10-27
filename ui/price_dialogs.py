"""
Окна прайс-листа: новая услуга, новый товар, скрытые позиции и
«Свойства позиций» — одна строка на позицию для всех типов машин.

Макеты согласованы владельцем 28.10.2026.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import styles
from services import directions
from services.audit_service import AuditService
from services.price_list_service import (
    PriceListService, PriceError, TYPES, TYPE_TITLES, SHORT_TITLES, RADII, radii_of,
    FLAT, BY_RADIUS, EDITABLE)
from services.service_kind import looks_main

MUTED = '#64748b'


def _window(parent, title, size):
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.geometry(size)
    dialog.configure(bg=styles.COLORS['bg'])
    dialog.transient(parent.winfo_toplevel())
    styles.center_window(dialog, parent.winfo_toplevel())
    content = ttk.Frame(dialog, style='White.TFrame')
    content.pack(fill='both', expand=True, padx=20, pady=18)
    styles.create_label(content, title, 'CardHeading.TLabel').pack(anchor='w', pady=(0, 12))
    return dialog, content


def _note(parent, text, **pack):
    label = ttk.Label(parent, text=text, font=(styles.DEFAULT_FONT, 9), foreground=MUTED,
                      background=styles.COLORS['bg_card'],
                      wraplength=pack.pop('wrap', 820), justify='left')
    label.pack(anchor='w', **pack)
    return label


def _row(parent, title, width=14):
    row = ttk.Frame(parent, style='White.TFrame')
    row.pack(fill='x', pady=5)
    ttk.Label(row, text=title, style='Card.TLabel', width=width).pack(side='left')
    return row


def _number(text, what):
    text = (text or '').strip().replace(',', '.')
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise PriceError(f'{what} — числом')
    if value < 0:
        raise PriceError(f'{what} не может быть меньше нуля')
    return value


def _log(db, text):
    try:
        AuditService(db).log(AuditService.PRICE_CHANGE, text, entity_type='service')
    except Exception:
        db.rollback()


def _direction_choice(parent, db):
    """Шиномонтаж или мойка — только если мойка включена."""
    var = tk.StringVar(value=directions.TIRE)
    if directions.wash_on(db):
        row = _row(parent, 'Направление')
        for value, title in ((directions.TIRE, 'Шиномонтаж'), (directions.WASH, 'Мойка')):
            ttk.Radiobutton(row, text=title, value=value, variable=var).pack(
                side='left', padx=(0, 16))
    return var


# ----------------------------------------------------------------------
# + Услуга
# ----------------------------------------------------------------------

def new_service(parent, db, on_done=None):
    dialog, form = _window(parent, 'Новая услуга', '900x560')
    prices = PriceListService(db)

    name_row = _row(form, 'Название')
    name_var = tk.StringVar()
    name_entry = ttk.Entry(name_row, textvariable=name_var, width=36,
                           font=(styles.DEFAULT_FONT, 12))
    name_entry.pack(side='left')
    name_entry.focus_set()

    direction_var = _direction_choice(form, db)

    mode_row = _row(form, 'Цена')
    mode_var = tk.StringVar(value=BY_RADIUS)
    for value, title in ((BY_RADIUS, 'по радиусам'), (FLAT, 'одна на все размеры'),
                         (EDITABLE, 'вводят в наряде')):
        ttk.Radiobutton(mode_row, text=title, value=value, variable=mode_var,
                        command=lambda: show_mode()).pack(side='left', padx=(0, 16))

    price_box = ttk.Frame(form, style='White.TFrame')
    price_box.pack(fill='x', pady=(6, 0))

    # По радиусам: вкладка на тип машины
    radius_box = ttk.Frame(price_box, style='White.TFrame')
    tabs = ttk.Notebook(radius_box)
    tabs.pack(fill='x')
    entries = {}
    for kind, title in TYPES:
        page = ttk.Frame(tabs, style='White.TFrame')
        tabs.add(page, text=title)
        entries[kind] = {}
        for index, radius in enumerate(radii_of(kind)):
            cell = ttk.Frame(page, style='White.TFrame')
            cell.grid(row=index // 6, column=index % 6, padx=(10, 4), pady=(8, 4), sticky='w')
            ttk.Label(cell, text=f'R{radius}', font=(styles.DEFAULT_FONT, 9),
                      foreground=MUTED).pack(anchor='w')
            entry = ttk.Entry(cell, width=8, font=(styles.DEFAULT_FONT, 11))
            entry.pack()
            entries[kind][radius] = entry
    _note(radius_box, 'Цены для джипов и категории С можно не трогать — по умолчанию '
                      'как у легковых.', pady=(6, 0))

    flat_box = ttk.Frame(price_box, style='White.TFrame')
    flat_row = _row(flat_box, 'Цена, ₽')
    flat_entry = ttk.Entry(flat_row, width=10, font=(styles.DEFAULT_FONT, 12))
    flat_entry.pack(side='left')

    editable_box = ttk.Frame(price_box, style='White.TFrame')
    _note(editable_box, 'Цену мастер вписывает в наряде сам — для «Прочих услуг» '
                        'и слесарных работ.')

    wash_box = ttk.Frame(price_box, style='White.TFrame')
    _note(wash_box, 'У мойки цена по классу машины — поставьте её в прайсе мойки '
                    '(кнопка «Мойка»).')

    def show_mode():
        for box in (radius_box, flat_box, editable_box, wash_box):
            box.pack_forget()
        if direction_var.get() == directions.WASH:
            wash_box.pack(fill='x')
            mode_row.pack_forget()
            return
        if not mode_row.winfo_ismapped():
            mode_row.pack(fill='x', pady=5, before=price_box)
        {BY_RADIUS: radius_box, FLAT: flat_box, EDITABLE: editable_box}[mode_var.get()].pack(
            fill='x')

    direction_var.trace_add('write', lambda *_: show_mode())
    show_mode()

    props = _row(form, 'Свойства')
    extra_var = tk.BooleanVar(value=True)
    ttk.Checkbutton(props, text='допродажа', variable=extra_var).pack(side='left')
    ttk.Label(props, text='себестоимость, ₽', background=styles.COLORS['bg_card']).pack(
        side='left', padx=(18, 6))
    cost_entry = ttk.Entry(props, width=7, font=(styles.DEFAULT_FONT, 11))
    cost_entry.pack(side='left')
    ttk.Label(props, text='время, мин', background=styles.COLORS['bg_card']).pack(
        side='left', padx=(18, 6))
    minutes_entry = ttk.Entry(props, width=5, font=(styles.DEFAULT_FONT, 11))
    minutes_entry.pack(side='left')

    # Шиномонтаж, балансировка, съём — основные; остальное по умолчанию допродажа
    def guess_kind(*_):
        extra_var.set(not looks_main(name_var.get()))
    name_var.trace_add('write', guess_kind)

    _note(form, 'Свойства — общие для всех типов машин. Кнопка услуги сразу появится '
                'на экране нарядов (место — в «Раскладке кнопок»).', pady=(4, 10))

    def save():
        try:
            minutes = _number(minutes_entry.get(), 'Время')
            cost = _number(cost_entry.get(), 'Себестоимость')
            mode = mode_var.get()
            table = {kind: {radius: _number(entry.get(), f'Цена R{radius}')
                            for radius, entry in entries[kind].items()}
                     for kind in entries}
            rows = prices.add_service(
                name_var.get(), direction=direction_var.get(), mode=mode, prices=table,
                flat_price=_number(flat_entry.get(), 'Цена'), is_extra=extra_var.get(),
                consumable_cost=cost or 0, minutes=int(minutes or 0))
        except PriceError as error:
            messagebox.showerror('Новая услуга', str(error), parent=dialog)
            return
        except Exception as error:
            db.rollback()
            messagebox.showerror('Новая услуга', f'Не удалось добавить: {error}', parent=dialog)
            return
        _log(db, f'Добавлена услуга «{rows[0].name}»')
        dialog.destroy()
        if on_done:
            on_done(rows[0].name)

    buttons = ttk.Frame(form, style='White.TFrame')
    buttons.pack(fill='x', side='bottom')
    styles.create_button(buttons, 'Добавить услугу', save, 'Primary.TButton').pack(side='left')
    styles.create_button(buttons, 'Отмена', dialog.destroy, 'Secondary.TButton').pack(
        side='left', padx=(8, 0))
    return dialog


# ----------------------------------------------------------------------
# + Товар
# ----------------------------------------------------------------------

def new_goods(parent, db, on_done=None):
    dialog, form = _window(parent, 'Новый товар', '480x360')
    fields = {}
    for key, title in (('name', 'Название'), ('price', 'Цена продажи, ₽'),
                       ('purchase', 'Закупка, ₽')):
        row = _row(form, title, width=16)
        entry = ttk.Entry(row, width=24 if key == 'name' else 10, font=(styles.DEFAULT_FONT, 12))
        entry.pack(side='left')
        fields[key] = entry
    fields['name'].focus_set()
    direction_var = _direction_choice(form, db)

    from services.stock_service import StockService
    stock_on = StockService(db).enabled()
    _note(form, 'Цена одна на любую машину и размер. Мастерам с товара не начисляется — '
                'он продаётся, а не делается.' +
                (' Склад включён — товар появится и там, с нулевым остатком.' if stock_on else ''),
          wrap=420, pady=(8, 12))

    def save():
        try:
            row = PriceListService(db).add_goods(
                fields['name'].get(), fields['price'].get(), fields['purchase'].get(),
                direction=direction_var.get())
        except PriceError as error:
            messagebox.showerror('Новый товар', str(error), parent=dialog)
            return
        except Exception as error:
            db.rollback()
            messagebox.showerror('Новый товар', f'Не удалось добавить: {error}', parent=dialog)
            return
        _log(db, f'Добавлен товар «{row.name}», {row.flat_price:.0f} ₽')
        dialog.destroy()
        if on_done:
            on_done(row.name)

    buttons = ttk.Frame(form, style='White.TFrame')
    buttons.pack(fill='x')
    styles.create_button(buttons, 'Добавить товар', save, 'Primary.TButton').pack(side='left')
    styles.create_button(buttons, 'Отмена', dialog.destroy, 'Secondary.TButton').pack(
        side='left', padx=(8, 0))
    return dialog


# ----------------------------------------------------------------------
# Скрытые
# ----------------------------------------------------------------------

def hidden_list(parent, db, on_done=None):
    dialog, content = _window(parent, 'Скрытые позиции', '480x460')
    _note(content, 'Их нет в прайсе и на кнопках наряда, но в старых нарядах они остались. '
                   'Выберите позицию и нажмите «Вернуть».', wrap=430, pady=(0, 10))
    box = tk.Listbox(content, font=(styles.DEFAULT_FONT, 11), height=12,
                     relief='solid', borderwidth=1, activestyle='none')
    box.pack(fill='both', expand=True)
    service = PriceListService(db)

    def load():
        box.delete(0, 'end')
        for name in service.hidden():
            box.insert('end', name)

    def restore():
        picked = box.curselection()
        if not picked:
            return
        name = box.get(picked[0])
        service.restore(name)
        _log(db, f'«{name}» возвращена в прайс')
        load()
        if on_done:
            on_done(name)

    load()
    buttons = ttk.Frame(content, style='White.TFrame')
    buttons.pack(fill='x', pady=(10, 0))
    styles.create_button(buttons, 'Вернуть', restore, 'Primary.TButton').pack(side='left')
    styles.create_button(buttons, 'Закрыть', dialog.destroy, 'Secondary.TButton').pack(
        side='left', padx=(8, 0))
    return dialog


# ----------------------------------------------------------------------
# Свойства позиций
# ----------------------------------------------------------------------

COLUMNS = ('Позиция', 'Машины', 'Вид', 'Тип', 'Цена', 'Себест', 'Время', 'Скидка')
TITLES = {'Позиция': 'Позиция', 'Машины': 'Для каких машин', 'Вид': 'Вид', 'Тип': 'Тип',
          'Цена': 'Цена, руб.', 'Себест': 'Себестоимость', 'Время': 'Время, мин',
          'Скидка': 'Макс. скидка, %'}
WIDTHS = {'Позиция': 240, 'Машины': 150, 'Вид': 100, 'Тип': 80, 'Цена': 110,
          'Себест': 120, 'Время': 90, 'Скидка': 120}
DIFFERENT = 'разное'

# Колонка → (поле, заголовок окна, вопрос, целое ли, верхний предел)
NUMBERS = {
    'Цена': ('flat_price', 'Единая цена',
             'Цена при любом диаметре, руб.\n(0 — цена из таблицы по диаметрам):', False, None),
    'Себест': ('cost', 'Себестоимость',
               'Закупка товара или материалы внутри работы, руб.:', False, None),
    'Время': ('duration_minutes', 'Время выполнения', 'Сколько минут занимает услуга:',
              True, None),
    'Скидка': ('max_discount_percent', 'Максимальная скидка',
               'Наибольшая скидка, %\n(100 — без ограничений):', True, 100),
}


def _cost(row):
    return (row.purchase_price if row.is_goods else row.consumable_cost) or 0


def _show(field, value):
    if field == 'flat_price':
        return 'по диаметру' if value is None else f'{value:.0f}'
    if field == 'max_discount_percent':
        return 'без огр.' if value is None or value >= 100 else f'{value}'
    return f'{value or 0:.0f}'


def _value(row, field):
    if field == 'cost':
        return _cost(row)
    if field == 'max_discount_percent':
        return 100 if row.max_discount_percent is None else row.max_discount_percent
    if field == 'duration_minutes':
        return row.duration_minutes or 0
    return getattr(row, field)


def _same(rows, show):
    shown = {show(row) for row in rows}
    return shown.pop() if len(shown) == 1 else DIFFERENT


class PropertiesDialog:
    """Одна строка на позицию; меняем — меняется у всех типов машин сразу."""

    def __init__(self, parent, db, focus_name=None):
        self.db = db
        self.service = PriceListService(db)
        self.groups = {}
        self.dialog, content = _window(parent, 'Свойства позиций', '1080x640')
        _note(content,
              'Одна строка на позицию: меняете время или расходник — меняется сразу у '
              'легковых, джипов и категории С. «разное» — у типов машин значения не '
              'совпадают, двойной щелчок покажет их по отдельности.\n'
              'Товар — продаётся позицией, процент мастеру с него не идёт. Цена — единая, '
              'когда не зависит от диаметра. Себестоимость вычитается до расчёта зарплаты. '
              'Вид — основная или допродажа: по доле допов видно, предлагают ли мастера '
              'что-то сверх. Вид и тип переключаются двойным щелчком.',
              wrap=1020, pady=(0, 10))

        frame = ttk.Frame(content, style='White.TFrame')
        frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(frame, columns=COLUMNS, show='headings')
        for column in COLUMNS:
            self.tree.heading(column, text=TITLES[column])
            self.tree.column(column, width=WIDTHS[column],
                             anchor='w' if column == 'Позиция' else 'center')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=scroll.set)
        self.tree.bind('<Double-1>', self.on_double)

        bottom = ttk.Frame(content, style='White.TFrame')
        bottom.pack(fill='x', pady=(10, 0))
        self.count = ttk.Label(bottom, font=(styles.DEFAULT_FONT, 9), foreground=MUTED,
                               background=styles.COLORS['bg_card'])
        self.count.pack(side='left')
        styles.create_button(bottom, 'Закрыть', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right')
        self.load()
        if focus_name:
            self.focus(focus_name)

    def load(self):
        selected = self.tree.selection()
        keep = selected[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        self.groups = {}
        wash = directions.wash_on(self.db)
        groups = self.service.groups()
        for direction, name, rows in groups:
            if direction == directions.WASH and not wash:
                continue
            iid = f'{direction}:{name}'
            self.groups[iid] = (direction, name)
            title = f'{name} (мойка)' if direction == directions.WASH else name
            machines = ' · '.join(SHORT_TITLES.get(r.vehicle_type, r.vehicle_type) for r in rows)
            self.tree.insert('', 'end', iid=iid, values=(
                title, machines,
                _same(rows, lambda r: 'допродажа' if r.is_extra else 'основная'),
                _same(rows, lambda r: 'товар' if r.is_goods else 'работа'),
                *(_same(rows, lambda r, f=NUMBERS[c][0]: _show(f, _value(r, f)))
                  for c in ('Цена', 'Себест', 'Время', 'Скидка'))))
        self.count.config(text=f'Позиций: {len(self.groups)}')
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
            self.tree.see(keep)

    def focus(self, name):
        iid = f'{directions.TIRE}:{name}'
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def rows(self, iid):
        direction, name = self.groups[iid]
        return self.service.rows(name, direction)

    def on_double(self, event):
        if self.tree.identify_region(event.x, event.y) != 'cell':
            return
        iid = self.tree.identify_row(event.y)
        column = COLUMNS[int(self.tree.identify_column(event.x)[1:]) - 1]
        if not iid or iid not in self.groups or column in ('Позиция', 'Машины'):
            return
        rows = self.rows(iid)
        if not rows:
            return
        try:
            if column in ('Вид', 'Тип'):
                self.toggle(rows, column)
            elif len(rows) == 1 or self.tree.set(iid, column) != DIFFERENT:
                self.ask_one(rows, column)
            else:
                self.ask_each(rows, column)
        except Exception as error:
            self.db.rollback()
            messagebox.showerror('Свойства', f'Не удалось сохранить: {error}', parent=self.dialog)
        self.load()

    def toggle(self, rows, column):
        field = 'is_extra' if column == 'Вид' else 'is_goods'
        values = {bool(getattr(r, field)) for r in rows}
        if len(values) == 1:
            new = not values.pop()
        else:
            question = ('Сделать у всех типов машин «допродажа»?\n«Нет» — у всех «основная».'
                        if field == 'is_extra' else
                        'Сделать у всех типов машин «товар»?\n«Нет» — у всех «работа».')
            answer = messagebox.askyesnocancel('Свойства', question, parent=self.dialog)
            if answer is None:
                return
            new = answer
        changed = self.service.set_values(rows, field, new)
        # Переделали услугу в товар, а единой цены нет — берём наибольшую
        # из цен по диаметрам: молча ноль — однажды продать вентиль бесплатно
        if field == 'is_goods' and new:
            for row in rows:
                if row.flat_price is None:
                    prices = [getattr(row, f'price_r{n}') or 0 for n in RADII]
                    row.flat_price = max(prices) if prices else 0.0
            self.db.commit()
        if changed:
            word = (('допродажа' if new else 'основная') if field == 'is_extra'
                    else ('товар' if new else 'работа'))
            _log(self.db, f'«{rows[0].name}» — {word}')

    @staticmethod
    def _convert(column, value):
        field, _title, _prompt, whole, _maximum = NUMBERS[column]
        if field == 'flat_price':
            value = round(float(value), 2)
            # Ноль — «цены нет», а не «бесплатно»: иначе вернуться к ценам
            # по диаметрам было бы нечем
            return value if value > 0 else None
        return int(value) if whole else round(float(value), 2)

    def ask_one(self, rows, column):
        field, title, prompt, _whole, maximum = NUMBERS[column]
        current = _value(rows[0], field)
        who = '' if len(rows) == 1 else '\n(для всех типов машин)'
        value = simpledialog.askfloat(
            title, f'«{rows[0].name}»{who}\n\n{prompt}',
            initialvalue=current or 0, minvalue=0, maxvalue=maximum, parent=self.dialog)
        if value is None:
            return
        self._save(rows, column, self._convert(column, value))

    def _save(self, rows, column, values):
        field, title = NUMBERS[column][:2]
        changed = self.service.set_values(rows, field, values)
        for row, old, new in changed:
            who = '' if row.vehicle_type == 'all' else f' ({TYPE_TITLES.get(row.vehicle_type)})'
            _log(self.db, f'«{row.name}»{who} — {title.lower()}: '
                          f'{_show(field, old)} -> {_show(field, new)}')

    def ask_each(self, rows, column):
        """Окошко «разное»: значение у каждого типа машин и «всем одинаково»."""
        field, title, _prompt, _whole, maximum = NUMBERS[column]
        popup = tk.Toplevel(self.dialog)
        popup.title(title)
        popup.configure(bg=styles.COLORS['bg_card'])
        popup.transient(self.dialog)
        popup.resizable(False, False)
        inner = ttk.Frame(popup, style='White.TFrame')
        inner.pack(padx=20, pady=16)
        styles.create_label(inner, f'{rows[0].name} — {title.lower()}',
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))
        grid = ttk.Frame(inner, style='White.TFrame')
        grid.pack(anchor='w')
        entries = {}
        for index, row in enumerate(rows):
            styles.create_label(grid, TYPE_TITLES.get(row.vehicle_type, row.vehicle_type),
                                'Card.TLabel').grid(row=index, column=0, sticky='w', pady=3)
            entry = ttk.Entry(grid, width=9, font=(styles.DEFAULT_FONT, 11))
            value = _value(row, field)
            entry.insert(0, '' if value is None else f'{value:g}')
            entry.grid(row=index, column=1, padx=(14, 0), pady=3)
            entries[row.id] = entry

        def same_for_all():
            first = next(iter(entries.values())).get()
            for entry in entries.values():
                entry.delete(0, 'end')
                entry.insert(0, first)

        def save():
            values = {}
            try:
                for row_id, entry in entries.items():
                    number = _number(entry.get(), title) or 0
                    if maximum is not None and number > maximum:
                        raise PriceError(f'{title} — не больше {maximum}')
                    values[row_id] = self._convert(column, number)
            except PriceError as error:
                messagebox.showerror(title, str(error), parent=popup)
                return
            self._save(rows, column, values)
            popup.destroy()

        buttons = ttk.Frame(inner, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        first = _value(rows[0], field)
        styles.create_button(buttons, f'Всем одинаково: {_show(field, first)}', same_for_all,
                             'Secondary.TButton').pack(side='left')
        styles.create_button(buttons, 'Сохранить', save, 'Primary.TButton').pack(
            side='left', padx=(8, 0))
        # Посреди окна свойств: center_window берёт ширину ещё не
        # показанного окна, а она в этот момент — 1 пиксель
        popup.update_idletasks()
        x = self.dialog.winfo_rootx() + (self.dialog.winfo_width() - popup.winfo_reqwidth()) // 2
        y = self.dialog.winfo_rooty() + (self.dialog.winfo_height() - popup.winfo_reqheight()) // 3
        popup.geometry(f'+{max(x, 0)}+{max(y, 0)}')
        popup.grab_set()
        self.dialog.wait_window(popup)
