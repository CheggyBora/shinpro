"""
Раздел «Склад» (docs/stock.md): остатки, приход, позиции, расход по
услугам. В меню — только когда склад включён в настройках.

«Мало» (меньше минимума) — жёлтым, «в минусе» — красным. Минус не
останавливает продажи, а главному при уходе в минус пишет программа.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from models.stock import GOODS, MATERIAL, KIND_TITLES, UNITS
from services.stock_service import StockService, StockError, fmt_qty

DIRECTION_TITLES = {'tire': 'Шиномонтаж', 'wash': 'Мойка'}


class StockTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = StockService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.direction = None
        self.kind = None
        self.problems = False
        # Главное окно ставит сюда «поменялось» — обновить счётчик в меню
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
        styles.create_label(top, 'Склад', 'CardHeading.TLabel').pack(side='left')
        styles.create_button(top, 'Приход', self.receive, 'Primary.TButton').pack(side='right')
        styles.create_button(top, '+ Позиция', self.new_item,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.create_button(top, 'Расход по услугам', self.open_recipes,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))

        self.filters = tk.Frame(inner, bg=styles.COLORS['bg_card'])
        self.filters.pack(fill='x', pady=(12, 8))

        holder = ttk.Frame(inner, style='White.TFrame')
        holder.pack(fill='both', expand=True)
        columns = ('name', 'kind', 'where', 'qty', 'min', 'price', 'purchase')
        self.tree = ttk.Treeview(holder, columns=columns, show='headings', height=16)
        for column, title, width, anchor in (
                ('name', 'Позиция', 260, 'w'), ('kind', 'Вид', 90, 'center'),
                ('where', 'Где', 110, 'center'), ('qty', 'Остаток', 110, 'e'),
                ('min', 'Минимум', 90, 'e'), ('price', 'Цена', 110, 'e'),
                ('purchase', 'Закупка', 90, 'e')):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor)
        self.tree.tag_configure('low', background='#fef3c7')
        self.tree.tag_configure('neg', background='#fee2e2')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=scroll.set)
        self.tree.bind('<Double-1>', lambda e: self.edit_selected())
        ttk.Label(inner, text='Двойной щелчок — карточка позиции: правка, пересчёт, история.',
                  font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w', pady=(6, 0))

    def _chip(self, text, on, command):
        chip = tk.Label(self.filters, text=text, cursor='hand2', padx=10, pady=3,
                        relief='solid', borderwidth=1,
                        font=(styles.DEFAULT_FONT, 10, 'bold' if on else 'normal'),
                        bg=styles.COLORS['primary_soft'] if on else styles.COLORS['bg_card'],
                        fg=styles.COLORS['primary'] if on else styles.COLORS['text_secondary'])
        chip.pack(side='left', padx=(0, 5))
        chip.bind('<Button-1>', lambda e: command())

    def _draw_filters(self):
        for child in self.filters.winfo_children():
            child.destroy()
        from services import directions
        if directions.wash_on(self.db):
            tk.Label(self.filters, text='Направление:', bg=styles.COLORS['bg_card'],
                     fg=styles.COLORS['text_secondary']).pack(side='left', padx=(0, 6))
            for value, title in ((None, 'Все'), ('tire', 'Шиномонтаж'), ('wash', 'Мойка')):
                self._chip(title, self.direction == value, lambda v=value: self._set('direction', v))
        tk.Label(self.filters, text='Вид:', bg=styles.COLORS['bg_card'],
                 fg=styles.COLORS['text_secondary']).pack(side='left', padx=(12, 6))
        for value, title in ((None, 'Все'), (GOODS, 'Товары'), (MATERIAL, 'Материалы')):
            self._chip(title, self.kind == value, lambda v=value: self._set('kind', v))
        self._chip('Только мало и минус', self.problems,
                   lambda: self._set('problems', not self.problems))

    def _set(self, key, value):
        setattr(self, key, value)
        self.load()

    def load(self):
        self._draw_filters()
        for row in self.tree.get_children():
            self.tree.delete(row)
        try:
            items = self.service.items(self.direction, self.kind, self.problems)
        except Exception:
            self.db.rollback()
            return
        for item in items:
            price = f'{item.price:,.0f} ₽'.replace(',', ' ')
            if item.unit != 'шт':
                price += f'/{item.unit}'
            purchase = f'{item.purchase_price:,.0f} ₽'.replace(',', ' ') if item.purchase_price else '—'
            self.tree.insert('', 'end', iid=str(item.id), tags=(item.state,), values=(
                item.name, KIND_TITLES.get(item.kind, item.kind),
                DIRECTION_TITLES.get(item.direction, item.direction),
                fmt_qty(item.quantity, item.unit), fmt_qty(item.min_quantity), price, purchase))

    def _changed(self):
        self.load()
        if self.on_changed:
            self.on_changed()

    def selected(self):
        chosen = self.tree.selection()
        return self.service.get(int(chosen[0])) if chosen else None

    # ------------------------------------------------------------------

    def new_item(self):
        ItemDialog(self.frame, self.db, None, self._changed, direction=self.direction)

    def edit_selected(self):
        item = self.selected()
        if item is not None:
            ItemDialog(self.frame, self.db, item, self._changed)

    def receive(self):
        ReceiveDialog(self.frame, self.db, self.selected(), self._changed)

    def open_recipes(self):
        RecipesDialog(self.frame, self.db)


def _dialog(parent, title):
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=styles.COLORS['bg_card'])
    dialog.transient(parent.winfo_toplevel())
    body = ttk.Frame(dialog, style='White.TFrame')
    body.pack(fill='both', expand=True, padx=18, pady=14)
    return dialog, body


class ItemDialog:
    """Новая позиция или карточка существующей."""

    def __init__(self, parent, db, item, on_saved=None, direction=None):
        self.db = db
        self.service = StockService(db)
        self.item = item
        self.on_saved = on_saved
        self.dialog, body = _dialog(parent, 'Позиция склада' if item else 'Новая позиция')
        form = ttk.Frame(body, style='White.TFrame')
        form.pack(fill='x')

        def label(row, text):
            styles.create_label(form, text, 'Card.TLabel').grid(row=row, column=0, sticky='w', pady=3, padx=(0, 10))

        self.direction = tk.StringVar(value=item.direction if item else (direction or ''))
        self.kind = tk.StringVar(value=item.kind if item else '')
        label(0, 'Где*')
        where = ttk.Frame(form, style='White.TFrame')
        where.grid(row=0, column=1, sticky='w')
        label(1, 'Вид*')
        kinds = ttk.Frame(form, style='White.TFrame')
        kinds.grid(row=1, column=1, sticky='w')
        if item is None:
            for value, title in (('tire', 'Шиномонтаж'), ('wash', 'Мойка')):
                ttk.Radiobutton(where, text=title, value=value, variable=self.direction).pack(side='left', padx=(0, 12))
            for value, title in ((GOODS, 'Товар (продаётся)'), (MATERIAL, 'Материал (уходит на услуги)')):
                ttk.Radiobutton(kinds, text=title, value=value, variable=self.kind).pack(side='left', padx=(0, 12))
        else:
            styles.create_label(where, DIRECTION_TITLES.get(item.direction, ''), 'Card.TLabel').pack(side='left')
            styles.create_label(kinds, KIND_TITLES.get(item.kind, ''), 'Card.TLabel').pack(side='left')

        self.fields = {}
        rows = [('name', 'Название*', item.name if item else ''),
                ('price', 'Цена*, ₽', f'{item.price:g}' if item else ''),
                ('purchase_price', 'Закупка, ₽', f'{item.purchase_price:g}' if item and item.purchase_price else ''),
                ('min_quantity', 'Минимум', f'{item.min_quantity:g}' if item else '0')]
        if item is None:
            rows.append(('quantity', 'Остаток сейчас', '0'))
        for row, (key, title, value) in enumerate(rows, start=2):
            label(row, title)
            entry = styles.create_entry(form, width=30 if key == 'name' else 12)
            entry.insert(0, value)
            entry.grid(row=row, column=1, sticky='w', pady=3)
            self.fields[key] = entry
        label(len(rows) + 2, 'Единица')
        self.unit = tk.StringVar(value=item.unit if item else 'шт')
        ttk.Combobox(form, textvariable=self.unit, values=UNITS, state='readonly',
                     width=6).grid(row=len(rows) + 2, column=1, sticky='w', pady=3)

        if item is not None:
            styles.create_label(body, f'Остаток: {fmt_qty(item.quantity, item.unit)}',
                                'CardHeading.TLabel').pack(anchor='w', pady=(10, 2))
            moves = self.service.history(item, 12)
            names = {'receive': 'приход', 'order': 'наряд', 'refund': 'возврат', 'correct': 'пересчёт'}
            for move in moves:
                when = move.created_at.strftime('%d.%m %H:%M') if move.created_at else ''
                text = f'{when}  {names.get(move.reason, move.reason)}  {"+" if move.change > 0 else ""}{fmt_qty(move.change, item.unit)}'
                if move.order_id:
                    text += f'  · наряд №{move.order_id}'
                if move.note:
                    text += f'  · {move.note}'
                ttk.Label(body, text=text, font=styles.FONTS['small'],
                          background=styles.COLORS['bg_card']).pack(anchor='w')

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Сохранить', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        if item is not None:
            styles.create_button(buttons, 'Пересчитать', self.correct,
                                 'Secondary.TButton').pack(side='left')
            styles.create_button(buttons, 'Убрать', self.remove,
                                 'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def save(self):
        fields = {key: entry.get() for key, entry in self.fields.items()}
        fields.update(unit=self.unit.get(), direction=self.direction.get() or None,
                      kind=self.kind.get() or None)
        try:
            self.service.save_item(self.item, **fields)
        except StockError as e:
            self.db.rollback()
            messagebox.showerror('Склад', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()

    def correct(self):
        from tkinter import simpledialog
        value = simpledialog.askstring('Пересчёт', f'Сколько фактически ({self.item.unit}):',
                                       parent=self.dialog)
        if not value:
            return
        try:
            self.service.correct(self.item, value)
        except (StockError, ValueError):
            messagebox.showerror('Склад', 'Нужно число', parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()

    def remove(self):
        if not messagebox.askyesno('Склад', f'Убрать «{self.item.name}» со склада?', parent=self.dialog):
            return
        self.service.remove_item(self.item)
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()


class ReceiveDialog:
    """Приход: привезли — добавить к остатку."""

    def __init__(self, parent, db, item=None, on_saved=None):
        self.db = db
        self.service = StockService(db)
        self.on_saved = on_saved
        self.items = self.service.items()
        self.dialog, body = _dialog(parent, 'Приход на склад')
        if not self.items:
            styles.create_label(body, 'Сначала заведите позиции: «+ Позиция».', 'Card.TLabel').pack()
            styles.create_button(body, 'Закрыть', self.dialog.destroy, 'Secondary.TButton').pack(pady=(10, 0))
            return
        names = [f'{i.name} · сейчас {fmt_qty(i.quantity, i.unit)}' for i in self.items]
        self.choice = tk.StringVar(value=names[self.items.index(item)] if item in self.items else names[0])
        styles.create_label(body, 'Позиция', 'Card.TLabel').pack(anchor='w')
        ttk.Combobox(body, textvariable=self.choice, values=names, state='readonly',
                     width=44).pack(anchor='w', pady=(0, 8))
        self.names = names
        styles.create_label(body, 'Пришло', 'Card.TLabel').pack(anchor='w')
        self.amount = styles.create_entry(body, width=12)
        self.amount.pack(anchor='w', pady=(0, 8))
        styles.create_label(body, 'Закупка за единицу (если поменялась)', 'Card.TLabel').pack(anchor='w')
        self.purchase = styles.create_entry(body, width=12)
        self.purchase.pack(anchor='w', pady=(0, 8))
        styles.create_label(body, 'От кого / заметка', 'Card.TLabel').pack(anchor='w')
        self.note = styles.create_entry(body, width=40)
        self.note.pack(anchor='w', pady=(0, 8))
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(6, 0))
        styles.create_button(buttons, 'Оприходовать', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()
        self.amount.focus_set()

    def save(self):
        item = self.items[self.names.index(self.choice.get())]
        try:
            self.service.receive(item, self.amount.get(), self.purchase.get().strip() or None,
                                 note=self.note.get().strip() or None)
        except StockError as e:
            self.db.rollback()
            messagebox.showerror('Склад', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()


class RecipesDialog:
    """Расход по услугам: какие материалы и сколько на одно выполнение."""

    def __init__(self, parent, db):
        from models import Service
        self.db = db
        self.service = StockService(db)
        self.dialog, body = _dialog(parent, 'Расход по услугам')
        self.dialog.geometry('760x520')
        from services import directions
        self.direction = tk.StringVar(value='tire')
        if directions.wash_on(db):
            switch = ttk.Frame(body, style='White.TFrame')
            switch.pack(anchor='w', pady=(0, 8))
            for value, title in (('tire', 'Шиномонтаж'), ('wash', 'Мойка')):
                ttk.Radiobutton(switch, text=title, value=value, variable=self.direction,
                                command=self.load_services).pack(side='left', padx=(0, 12))
        split = ttk.Frame(body, style='White.TFrame')
        split.pack(fill='both', expand=True)
        self.services_box = tk.Listbox(split, width=34, exportselection=False, font=styles.FONTS['normal'])
        self.services_box.pack(side='left', fill='y')
        self.services_box.bind('<<ListboxSelect>>', lambda e: self.load_recipe())
        right = ttk.Frame(split, style='White.TFrame')
        right.pack(side='left', fill='both', expand=True, padx=(12, 0))
        self.recipe = ttk.Treeview(right, columns=('name', 'qty', 'cost'), show='headings', height=10)
        for column, title, width in (('name', 'Материал', 220), ('qty', 'На 1 раз', 90), ('cost', '₽', 70)):
            self.recipe.heading(column, text=title)
            self.recipe.column(column, width=width, anchor='w' if column == 'name' else 'e')
        self.recipe.pack(fill='both', expand=True)
        self.total = styles.create_label(right, '', 'CardHeading.TLabel')
        self.total.pack(anchor='w', pady=(6, 6))
        row = ttk.Frame(right, style='White.TFrame')
        row.pack(fill='x')
        styles.create_button(row, '+ материал', self.add_material, 'Secondary.TButton').pack(side='left')
        styles.create_button(row, 'Убрать', self.remove_material,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.create_button(body, 'Закрыть', self.dialog.destroy,
                             'Secondary.TButton').pack(anchor='e', pady=(10, 0))
        self.Service = Service
        self.load_services()
        styles.center_window(self.dialog, parent.winfo_toplevel())

    def load_services(self):
        rows = self.db.query(self.Service).filter(
            self.Service.is_active.isnot(False), self.Service.is_goods.isnot(True),
            self.Service.direction == self.direction.get()).order_by(self.Service.name).all()
        seen, self.services = set(), []
        for row in rows:
            if row.name not in seen:
                seen.add(row.name)
                self.services.append(row)
        self.services_box.delete(0, tk.END)
        for row in self.services:
            self.services_box.insert(tk.END, row.name)
        self.load_recipe()

    def current(self):
        chosen = self.services_box.curselection()
        return self.services[chosen[0]] if chosen else None

    def _same_name(self, service):
        # У шиномонтажа одна услуга заведена по типам машин — расход общий
        return self.db.query(self.Service).filter(self.Service.name == service.name,
                                                  self.Service.direction == service.direction).all()

    def load_recipe(self):
        for row in self.recipe.get_children():
            self.recipe.delete(row)
        service = self.current()
        if service is None:
            self.total.config(text='Выберите услугу слева')
            return
        for row, item in self.service.recipe(service.id):
            self.recipe.insert('', 'end', iid=str(item.id), values=(
                item.name, fmt_qty(row.quantity, item.unit), f'{row.quantity * (item.price or 0):.0f}'))
        self.total.config(text=f'Итого расходник: {self.service.recipe_cost(service.id):.0f} ₽')

    def add_material(self):
        from tkinter import simpledialog
        service = self.current()
        if service is None:
            return
        materials = self.service.items(self.direction.get(), MATERIAL)
        if not materials:
            messagebox.showinfo('Расход', 'Нет материалов этого направления — заведите на складе',
                                parent=self.dialog)
            return
        from ui.order_screen.directions import ask_choice
        item_id = ask_choice(self.dialog, 'Материал', 'Какой материал уходит на услугу:',
                             [(m.id, f'{m.name} ({m.unit})') for m in materials])
        if not item_id:
            return
        item = self.service.get(item_id)
        value = simpledialog.askstring('Расход', f'Сколько {item.unit} на одно выполнение:',
                                       parent=self.dialog)
        if not value:
            return
        try:
            for same in self._same_name(service):
                self.service.set_material(same.id, item_id, value)
        except (StockError, ValueError):
            self.db.rollback()
            messagebox.showerror('Расход', 'Нужно число больше нуля', parent=self.dialog)
            return
        self.load_recipe()

    def remove_material(self):
        service = self.current()
        chosen = self.recipe.selection()
        if service is None or not chosen:
            return
        for same in self._same_name(service):
            self.service.remove_material(same.id, int(chosen[0]))
        self.load_recipe()
