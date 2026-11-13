"""
Магазин (решение владельца 08.11.2026): карточки товаров и продажа.

Слева — каталог карточками: фото (необязательно), название, категория,
цена и остаток. Щелчок по карточке — в продажу справа, «✎» — правка.
Продажу пробивают без машины или добавляют в открытый наряд.

Здесь же окно «Товар из магазина» для наряда (ShopPicker).
"""
import os
import platform
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import styles
from logger import log
from services import directions
from services.shop_service import ShopService
from services.stock_service import StockError

CARD_W, CARD_H, PHOTO_H = 200, 210, 90
COLUMNS = 4


def money(value):
    return f'{value:,.0f}'.replace(',', ' ') + ' ₽'


def people_on_shift(db):
    """Кто может продать: сначала на смене, администратор первым."""
    from models import Employee, WorkShift
    from services.employee_role_service import EmployeeRoleService
    roles = EmployeeRoleService(db)
    on_shift = {s.employee_id for s in db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()}
    people = db.query(Employee).filter(Employee.is_active.isnot(False)).order_by(Employee.id).all()
    return sorted(people, key=lambda e: (e.id not in on_shift, not roles.is_admin(e), e.id))


def _photo(path, width, height):
    """Миниатюра для карточки или None — нет фото или его не открыть."""
    if not path:
        return None
    try:
        from PIL import Image, ImageTk
        with Image.open(path) as image:
            image = image.convert('RGB')
            image.thumbnail((width, height))
            return ImageTk.PhotoImage(image)
    except Exception:
        return None


class ShopTab:
    def __init__(self, parent, db, app=None):
        self.db = db
        self.app = app
        self.shop = ShopService(db)
        self.category = None
        self.basket = {}          # id карточки → количество
        self._images = []
        self.frame = ttk.Frame(parent, style='TFrame')

        left = tk.Frame(self.frame, bg=styles.COLORS['bg_card'], highlightthickness=1,
                        highlightbackground=styles.COLORS['border'])
        left.pack(side='left', fill='both', expand=True, padx=(15, 8), pady=15)
        head = tk.Frame(left, bg=styles.COLORS['bg_card'])
        head.pack(fill='x', padx=16, pady=(12, 4))
        tk.Label(head, text='Магазин', bg=styles.COLORS['bg_card'], fg=styles.COLORS['text'],
                 font=(styles.DEFAULT_FONT, 15, 'bold')).pack(side='left')
        styles.create_button(head, '+ Товар', lambda: CardDialog(self.frame, self.db, None, self.load),
                             'Primary.TButton').pack(side='right')
        search = tk.Frame(left, bg=styles.COLORS['bg_card'])
        search.pack(fill='x', padx=16, pady=(0, 4))
        self.search = styles.create_entry(search, width=28)
        self.search.pack(side='left')
        self.search.bind('<KeyRelease>', lambda e: self.draw_cards())
        tk.Label(search, text='название, артикул', bg=styles.COLORS['bg_card'],
                 fg=styles.COLORS['text_secondary'], font=styles.FONTS['small']).pack(side='left', padx=6)
        self.chips = tk.Frame(left, bg=styles.COLORS['bg_card'])
        self.chips.pack(fill='x', padx=16, pady=(2, 6))

        holder = tk.Frame(left, bg=styles.COLORS['bg_card'])
        holder.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(holder, bg=styles.COLORS['bg_card'], highlightthickness=0)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.grid = tk.Frame(self.canvas, bg=styles.COLORS['bg_card'])
        self.canvas.create_window((0, 0), window=self.grid, anchor='nw')
        self.grid.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Enter>', lambda e: self.canvas.bind_all(
            '<MouseWheel>', lambda ev: self.canvas.yview_scroll(-1 if ev.delta > 0 else 1, 'units')))
        self.canvas.bind('<Leave>', lambda e: self.canvas.unbind_all('<MouseWheel>'))

        right = tk.Frame(self.frame, bg=styles.COLORS['bg_card'], highlightthickness=1,
                         highlightbackground=styles.COLORS['border'], width=480)
        right.pack(side='right', fill='y', padx=(0, 15), pady=15)
        right.pack_propagate(False)
        body = tk.Frame(right, bg=styles.COLORS['bg_card'])
        body.pack(fill='both', expand=True, padx=16, pady=12)
        tk.Label(body, text='Продажа', bg=styles.COLORS['bg_card'], fg=styles.COLORS['text'],
                 font=(styles.DEFAULT_FONT, 13, 'bold')).pack(anchor='w')
        tk.Label(body, text='Щелчок по карточке — сюда. Можно без машины\nили в открытый наряд.',
                 bg=styles.COLORS['bg_card'], fg=styles.COLORS['text_secondary'], justify='left',
                 font=styles.FONTS['small']).pack(anchor='w', pady=(2, 6))
        self.lines = ttk.Treeview(body, columns=('name', 'qty', 'sum'), show='headings', height=8)
        for column, title, width, anchor in (('name', 'Товар', 220, 'w'), ('qty', 'Кол-во', 60, 'center'),
                                             ('sum', 'Сумма', 90, 'e')):
            self.lines.heading(column, text=title)
            self.lines.column(column, width=width, anchor=anchor)
        self.lines.pack(fill='x')
        row = tk.Frame(body, bg=styles.COLORS['bg_card'])
        row.pack(fill='x', pady=(4, 6))
        for text, change in (('+1', 1), ('−1', -1), ('Убрать', 0)):
            styles.create_button(row, text, lambda c=change: self.change_line(c),
                                 'Compact.Secondary.TButton').pack(side='left', padx=(0, 4))
        styles.create_button(row, 'Очистить', self.clear, 'Compact.Secondary.TButton').pack(side='right')
        # «Продал» — только когда процент с продаж включён (решение
        # владельца 09.11.2026): выключен — продажа просто пробивается
        self.seller_row = seller_row = tk.Frame(body, bg=styles.COLORS['bg_card'])
        styles.create_label(seller_row, 'Продал:', 'Card.TLabel').pack(side='left')
        self.seller = tk.StringVar()
        self.seller_box = ttk.Combobox(seller_row, textvariable=self.seller, state='readonly', width=28)
        self.seller_box.pack(side='left', padx=(8, 0))
        # Администратор продажи — когда ему идёт процент с магазина, а на
        # смене их несколько (решение владельца 13.11.2026)
        self.admin_row = admin_row = tk.Frame(body, bg=styles.COLORS['bg_card'])
        styles.create_label(admin_row, 'Администратор:', 'Card.TLabel').pack(side='left')
        self.sale_admin = tk.StringVar()
        self.admin_box = ttk.Combobox(admin_row, textvariable=self.sale_admin, state='readonly', width=24)
        self.admin_box.pack(side='left', padx=(8, 0))
        self.total = tk.Label(body, text='Итого: 0 ₽', bg=styles.COLORS['bg_card'], fg=styles.COLORS['primary'],
                              font=(styles.DEFAULT_FONT, 15, 'bold'))
        self.total.pack(anchor='e', pady=(8, 6))
        styles.create_button(body, 'Пробить продажу', self.sell, 'Success.TButton').pack(fill='x')
        styles.create_button(body, 'Добавить в открытый наряд ▾', self.to_order,
                             'Secondary.TButton').pack(fill='x', pady=(6, 0))

    # ------------------------------------------------------------------

    def load(self):
        self._draw_chips()
        self.draw_cards()
        self._fill_sellers()
        self.draw_basket()

    def _draw_chips(self):
        for child in self.chips.winfo_children():
            child.destroy()
        categories = self.shop.categories()
        if self.category not in categories:
            self.category = None
        for value in [None] + categories:
            on = value == self.category
            chip = tk.Label(self.chips, text=value or 'Все', padx=10, pady=3, cursor='hand2',
                            bg=styles.COLORS['primary'] if on else '#eef2f7',
                            fg='white' if on else styles.COLORS['text'], font=styles.FONTS['small'])
            chip.pack(side='left', padx=(0, 4))
            chip.bind('<Button-1>', lambda e, v=value: self._pick_category(v))

    def _pick_category(self, value):
        self.category = value
        self._draw_chips()
        self.draw_cards()

    def draw_cards(self):
        for child in self.grid.winfo_children():
            child.destroy()
        self._images = []
        cards = self.shop.cards(self.search.get(), self.category)
        if not cards:
            tk.Label(self.grid, text='Товаров нет. «+ Товар» — завести карточку.',
                     bg=styles.COLORS['bg_card'], fg=styles.COLORS['text_secondary']).grid(padx=8, pady=20)
            return
        block = directions.stock_negative(self.db) == 'block'
        for index, card in enumerate(cards):
            self._card(card, index, block and (card.quantity or 0) <= 0)

    def _card(self, card, index, disabled):
        bg = '#f1f5f9' if disabled else '#f8fafc'
        box = tk.Frame(self.grid, bg=bg, width=CARD_W, height=CARD_H, cursor='hand2',
                       highlightthickness=1, highlightbackground=styles.COLORS['border'])
        box.grid(row=index // COLUMNS, column=index % COLUMNS, padx=6, pady=6)
        box.pack_propagate(False)
        image = _photo(self.shop.photo_path(card), CARD_W - 2, PHOTO_H)
        if image is not None:
            self._images.append(image)
            picture = tk.Label(box, image=image, bg='#e2e8f0', height=PHOTO_H)
        else:
            picture = tk.Label(box, text='нет фото', bg='#e2e8f0', fg='#94a3b8', height=5,
                               font=styles.FONTS['small'])
        picture.pack(fill='x')
        name = tk.Label(box, text=card.name, bg=bg, fg=styles.COLORS['text'], wraplength=CARD_W - 16,
                        justify='left', anchor='w', font=(styles.DEFAULT_FONT, 10, 'bold'))
        name.pack(fill='x', padx=8, pady=(4, 0))
        meta = ' · '.join(x for x in (card.category, card.sku) if x)
        info = tk.Label(box, text=meta, bg=bg, fg=styles.COLORS['text_secondary'], anchor='w',
                        font=styles.FONTS['small'])
        info.pack(fill='x', padx=8)
        price = tk.Label(box, text=money(card.price or 0), bg=bg, fg=styles.COLORS['primary'], anchor='w',
                         font=(styles.DEFAULT_FONT, 12, 'bold'))
        price.pack(fill='x', padx=8)
        qty = card.quantity or 0
        low = qty <= (card.min_quantity or 0)
        stock = tk.Label(box, text=f'на складе: {qty:g} {card.unit}' + (' — закончился' if qty <= 0 else ''),
                         bg=bg, anchor='w', font=styles.FONTS['small'],
                         fg='#b91c1c' if qty <= 0 else ('#b45309' if low else styles.COLORS['text_secondary']))
        stock.pack(fill='x', padx=8)
        edit = tk.Label(box, text='✎', bg=bg, fg=styles.COLORS['text_secondary'], cursor='hand2',
                        font=(styles.DEFAULT_FONT, 11))
        edit.place(relx=1.0, y=PHOTO_H + 2, anchor='ne', x=-4)
        edit.bind('<Button-1>', lambda e: CardDialog(self.frame, self.db, card, self.load))
        for widget in (box, picture, name, info, price, stock):
            widget.bind('<Button-1>', lambda e, c=card, d=disabled: self.add(c, d))

    # --- продажа --------------------------------------------------------

    def _fill_sellers(self):
        from services.order_service import OrderService
        self._people = people_on_shift(self.db)
        if directions.shop_pay_on(self.db):
            self.seller_row.pack(fill='x', pady=(4, 2), before=self.total)
        else:
            self.seller_row.pack_forget()
        from services.salary_service import SalaryService
        self._admins = SalaryService(self.db).admins_on_shift()
        if directions.admin_shop_on(self.db) and len(self._admins) >= 2:
            self.admin_row.pack(fill='x', pady=(2, 2), before=self.total)
        else:
            self.admin_row.pack_forget()
        admin_titles = [a.title for a in self._admins]
        self.admin_box.config(values=admin_titles)
        if self.sale_admin.get() not in admin_titles:
            self.sale_admin.set('')
        titles = [p.title for p in self._people]
        self.seller_box.config(values=titles)
        default = OrderService(self.db)._default_seller()
        chosen = next((p for p in self._people if p.id == default), None)
        # Сам не подставляем никого, кроме единственного на смене: продавца
        # выбирают, иначе процент уйдёт не тому
        if self.seller.get() not in titles:
            self.seller.set(chosen.title if chosen else '')

    def _seller_id(self):
        if not directions.shop_pay_on(self.db):
            return None
        person = next((p for p in getattr(self, '_people', []) if p.title == self.seller.get()), None)
        return person.id if person else None

    def _admin_id(self):
        admin = next((a for a in getattr(self, '_admins', []) if a.title == self.sale_admin.get()), None)
        return admin.id if admin else None

    def _seller_ok(self):
        """Процент с продаж включён — без продавца не продаём."""
        if directions.shop_pay_on(self.db) and not self._seller_id():
            messagebox.showwarning('Магазин', 'Выберите, кто продал.', parent=self.frame)
            self.seller_box.focus_set()
            return False
        if self.admin_row.winfo_manager() and not self._admin_id():
            messagebox.showwarning('Магазин', 'Выберите администратора продажи.', parent=self.frame)
            self.admin_box.focus_set()
            return False
        return True

    def add(self, card, disabled=False):
        if disabled:
            messagebox.showwarning('Магазин', f'«{card.name}» нет на складе — продать нельзя '
                                              '(Настройки → Склад).', parent=self.frame)
            return
        self.basket[card.id] = self.basket.get(card.id, 0) + 1
        self.draw_basket()

    def _cards_in_basket(self):
        from models.stock import StockItem
        rows = []
        for card_id, qty in self.basket.items():
            card = self.db.query(StockItem).get(card_id)
            if card is not None and qty > 0:
                rows.append((card, qty))
        return rows

    def draw_basket(self):
        self.lines.delete(*self.lines.get_children())
        total = 0.0
        for card, qty in self._cards_in_basket():
            amount = (card.price or 0) * qty
            total += amount
            self.lines.insert('', 'end', iid=str(card.id), values=(card.name, qty, money(amount)))
        self.total.config(text=f'Итого: {money(total)}')

    def change_line(self, change):
        selection = self.lines.selection()
        if not selection:
            return
        card_id = int(selection[0])
        if change == 0:
            self.basket.pop(card_id, None)
        else:
            self.basket[card_id] = max(0, self.basket.get(card_id, 0) + change)
            if not self.basket[card_id]:
                self.basket.pop(card_id)
        self.draw_basket()
        if str(card_id) in self.lines.get_children():
            self.lines.selection_set(str(card_id))

    def clear(self):
        self.basket = {}
        self.draw_basket()

    def _shift_open(self):
        from services.shift_service import ShiftService
        if ShiftService(self.db).get_current_shift() is None:
            messagebox.showwarning('Смена закрыта', 'Откройте смену: продажа проводится в смене.',
                                   parent=self.frame)
            return False
        return True

    def sell(self):
        lines = self._cards_in_basket()
        if not lines or not self._shift_open():
            if not lines:
                messagebox.showinfo('Магазин', 'Щёлкните по карточкам — товары встанут в продажу.',
                                    parent=self.frame)
            return
        if not self._seller_ok():
            return
        total = sum((card.price or 0) * qty for card, qty in lines)
        payment = ask_payment(self.frame, total)
        if payment is None:
            return
        method, cash = payment
        from services import SalaryService, OrderService
        try:
            order = self.shop.create_sale(lines, seller_id=self._seller_id(), admin_id=self._admin_id())
            amount = OrderService(self.db).calculate_total(order.id)
            SalaryService(self.db).process_payment(order.id, method, amount, cash)
        except (StockError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Магазин', str(e), parent=self.frame)
            return
        self.clear()
        self.load()
        self._print(order, amount)

    def _print(self, order, total):
        """Чек — как у наряда: узкий, если включён термопринтер, иначе A4."""
        try:
            from services.order_service import OrderService
            from services.print_service import PrintService
            from services.settings_service import SettingsService
            items = OrderService(self.db).get_order_items(order.id)
            settings = SettingsService(self.db)
            printer = PrintService()
            if settings.get('thermal_receipt_enabled', '0') == '1':
                path = printer.generate_thermal_receipt(order, items, total,
                                                        width_mm=settings.get_int('thermal_receipt_width', 58))
            else:
                path = printer.generate_receipt(order, items, total)
            if platform.system() == 'Windows':
                os.startfile(path, 'print')
            messagebox.showinfo('Магазин', f'Продажа №{order.id} пробита: {money(total)}.',
                                parent=self.frame)
        except Exception as e:
            log.error(f'Чек продажи не напечатан: {e}')
            messagebox.showinfo('Магазин', f'Продажа №{order.id} пробита: {money(total)}.\n'
                                           f'Чек не напечатан: {e}', parent=self.frame)

    def to_order(self):
        """Товары продажи — в открытый наряд (по номеру и машине)."""
        lines = self._cards_in_basket()
        if not lines:
            messagebox.showinfo('Магазин', 'Сначала выберите товары.', parent=self.frame)
            return
        if not self._seller_ok():
            return
        orders_tab = getattr(self.app, 'orders_tab', None) if self.app else None
        opened = list(getattr(orders_tab, 'active_orders', {}).values()) if orders_tab else []
        if not opened:
            messagebox.showinfo('Магазин', 'Открытых нарядов нет.', parent=self.frame)
            return
        from ui.order_screen.directions import ask_choice
        chosen = ask_choice(self.frame, 'В наряд', 'В какой наряд добавить:',
                            [(w.order.id, f'№{w.order.id} · {w.order.car.license_plate}') for w in opened])
        if not chosen:
            return
        widget = next(w for w in opened if w.order.id == chosen)
        from services.order_service import OrderService
        try:
            for card, qty in lines:
                OrderService(self.db).add_service_to_order(chosen, card.service_id,
                                                           employee_id=self._seller_id(), quantity=qty)
        except (StockError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Магазин', str(e), parent=self.frame)
            return
        self.clear()
        widget.refresh_items()
        if self.app is not None:
            orders_tab.order_notebook.select(widget.frame)
            self.app.show_orders()


def ask_payment(parent, total):
    """Наличные, карта или раздельно. (способ, наличными) или None."""
    dialog = tk.Toplevel(parent)
    dialog.title('Оплата')
    dialog.configure(bg=styles.COLORS['bg_card'])
    dialog.transient(parent.winfo_toplevel())
    body = ttk.Frame(dialog, style='White.TFrame')
    body.pack(fill='both', expand=True, padx=20, pady=16)
    tk.Label(body, text=f'К оплате: {money(total)}', bg=styles.COLORS['bg_card'], fg=styles.COLORS['primary'],
             font=(styles.DEFAULT_FONT, 15, 'bold')).pack(anchor='w', pady=(0, 10))
    method = tk.StringVar(value='cash')
    cash = tk.StringVar()
    for text, value in (('Наличные', 'cash'), ('Карта', 'card'), ('Раздельно: часть наличными', 'mixed')):
        ttk.Radiobutton(body, text=text, value=value, variable=method).pack(anchor='w', pady=2)
    row = ttk.Frame(body, style='White.TFrame')
    row.pack(fill='x', pady=(6, 0))
    styles.create_label(row, 'Наличными (если раздельно):', 'Card.TLabel').pack(side='left')
    ttk.Entry(row, textvariable=cash, width=10).pack(side='left', padx=6)
    result = {}

    def done():
        if method.get() == 'mixed':
            try:
                value = round(float(cash.get().replace(',', '.').replace(' ', '')), 2)
            except ValueError:
                value = 0
            if not 0 < value < total:
                messagebox.showwarning('Оплата', f'Наличными — больше 0 и меньше {total:.0f} ₽.',
                                       parent=dialog)
                return
            result['value'] = ('mixed', value)
        else:
            result['value'] = (method.get(), None)
        dialog.destroy()

    buttons = ttk.Frame(body, style='White.TFrame')
    buttons.pack(fill='x', pady=(12, 0))
    styles.create_button(buttons, 'Оплатить', done, 'Success.TButton').pack(side='left', fill='x', expand=True)
    styles.create_button(buttons, 'Отмена', dialog.destroy, 'Secondary.TButton').pack(
        side='left', fill='x', expand=True, padx=(6, 0))
    styles.center_window(dialog, parent.winfo_toplevel())
    dialog.grab_set()
    parent.wait_window(dialog)
    return result.get('value')


class CardDialog:
    """Карточка товара: завести или поправить."""

    def __init__(self, parent, db, card, on_saved=None):
        self.db = db
        self.card = card
        self.on_saved = on_saved
        self.shop = ShopService(db)
        self.photo_from = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Товар' if card else 'Новый товар')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        form = ttk.Frame(self.dialog, style='White.TFrame')
        form.pack(fill='both', expand=True, padx=20, pady=16)
        self.fields = {}

        def row(r, title, key, value, width=32, values=None):
            styles.create_label(form, title, 'Card.TLabel').grid(row=r, column=0, sticky='w', pady=3, padx=(0, 12))
            if values is not None:
                widget = ttk.Combobox(form, values=values, width=width - 2)
                widget.set(value or '')
            else:
                widget = styles.create_entry(form, width=width)
                widget.insert(0, '' if value is None else value)
            widget.grid(row=r, column=1, sticky='w', pady=3)
            self.fields[key] = widget

        def number(value):
            return '' if value in (None, '') else f'{value:g}'

        row(0, 'Название*', 'name', card.name if card else '')
        row(1, 'Категория', 'category', card.category if card else '', values=self.shop.categories())
        row(2, 'Артикул', 'sku', card.sku if card else '')
        row(3, 'Цена продажи, ₽*', 'price', number(card.price) if card else '', width=12)
        row(4, 'Закупка, ₽', 'purchase_price', number(card.purchase_price) if card else '', width=12)
        row(5, 'Остаток' + ('' if card else ' сейчас'), 'quantity',
            number(card.quantity) if card else '0', width=12)
        row(6, 'Мало, если меньше', 'min_quantity', number(card.min_quantity) if card else '0', width=12)
        row(7, 'Бонус продавцу, ₽ за шт', 'bonus', number(card.bonus) if card else '', width=12)
        tk.Label(form, text='Пусто — по ставке магазина. Указан — бонус вместо процента.',
                 bg=styles.COLORS['bg_card'], fg=styles.COLORS['text_secondary'],
                 font=styles.FONTS['small']).grid(row=8, column=1, sticky='w')

        styles.create_label(form, 'Фото', 'Card.TLabel').grid(row=9, column=0, sticky='nw', pady=6)
        photo = ttk.Frame(form, style='White.TFrame')
        photo.grid(row=9, column=1, sticky='w', pady=6)
        self.photo_label = tk.Label(photo, text='нет фото — необязательно', bg='#e2e8f0', fg='#64748b',
                                    width=24, height=5)
        self.photo_label.pack(side='left')
        side = ttk.Frame(photo, style='White.TFrame')
        side.pack(side='left', padx=8)
        styles.create_button(side, 'Выбрать фото…', self.choose_photo, 'Compact.Secondary.TButton').pack(fill='x')
        styles.create_button(side, 'Убрать фото', self.drop_photo, 'Compact.Secondary.TButton').pack(
            fill='x', pady=(4, 0))
        self._show_photo(self.shop.photo_path(card) if card else None)

        buttons = ttk.Frame(form, style='White.TFrame')
        buttons.grid(row=10, column=0, columnspan=2, sticky='we', pady=(14, 0))
        if card is not None:
            styles.create_button(buttons, 'Убрать из магазина', self.remove, 'Secondary.TButton').pack(side='left')
        styles.create_button(buttons, 'Сохранить', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy, 'Secondary.TButton').pack(
            side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def _show_photo(self, path):
        image = _photo(path, 180, 100)
        self._image = image
        if image is not None:
            self.photo_label.config(image=image, text='', width=180, height=100)
        else:
            self.photo_label.config(image='', text='нет фото — необязательно', width=24, height=5)

    def choose_photo(self):
        path = filedialog.askopenfilename(
            parent=self.dialog, title='Фото товара',
            filetypes=[('Картинки', '*.jpg *.jpeg *.png *.webp *.bmp'), ('Все файлы', '*.*')])
        if path:
            self.photo_from = path
            self._show_photo(path)

    def drop_photo(self):
        self.photo_from = None
        if self.card is not None:
            self.shop.remove_photo(self.card)
        self._show_photo(None)

    def save(self):
        values = {key: widget.get().strip() for key, widget in self.fields.items()}
        quantity = values.pop('quantity')
        try:
            if self.card is None:
                card = self.shop.save_card(None, photo_from=self.photo_from, quantity=quantity, **values)
            else:
                card = self.shop.save_card(self.card, photo_from=self.photo_from, **values)
                # Остаток правим пересчётом — со следом в истории склада
                try:
                    wanted = float(quantity.replace(',', '.')) if quantity else card.quantity
                except ValueError:
                    raise StockError('Остаток — числом')
                if abs(wanted - (card.quantity or 0)) > 1e-9:
                    self.shop.stock.correct(card, wanted, note='Правка в карточке магазина')
        except StockError as e:
            self.db.rollback()
            messagebox.showerror('Товар', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()

    def remove(self):
        if not messagebox.askyesno('Товар', f'Убрать «{self.card.name}» из магазина? '
                                             'Проданное останется в истории.', parent=self.dialog):
            return
        self.shop.stock.remove_item(self.card)
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()


class ShopPicker:
    """«+ Товар из магазина» в наряде: найти, сколько, кто продал."""

    def __init__(self, parent, db, order, on_added=None):
        self.db = db
        self.order = order
        self.on_added = on_added
        self.shop = ShopService(db)
        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Товар из магазина')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=16, pady=12)
        self.search = styles.create_entry(body, width=40)
        self.search.pack(anchor='w')
        self.search.bind('<KeyRelease>', lambda e: self.fill())
        self.tree = ttk.Treeview(body, columns=('name', 'cat', 'price', 'qty'), show='headings', height=12)
        for column, title, width, anchor in (('name', 'Товар', 240, 'w'), ('cat', 'Категория', 130, 'w'),
                                             ('price', 'Цена', 80, 'e'), ('qty', 'На складе', 80, 'center')):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor=anchor)
        self.tree.pack(fill='both', expand=True, pady=6)
        self.tree.bind('<Double-1>', lambda e: self.add())
        row = ttk.Frame(body, style='White.TFrame')
        row.pack(fill='x')
        styles.create_label(row, 'Сколько:', 'Card.TLabel').pack(side='left')
        self.qty = ttk.Spinbox(row, from_=1, to=999, width=5)
        self.qty.set(1)
        self.qty.pack(side='left', padx=(6, 14))
        self.people = people_on_shift(db)
        from services.order_service import OrderService
        default = OrderService(db)._default_seller()
        self.seller = ttk.Combobox(row, values=[p.title for p in self.people], state='readonly', width=24)
        chosen = next((p for p in self.people if p.id == default), None)
        self.seller.set(chosen.title if chosen else '')
        # «Продал» — только когда процент с продаж включён
        self.pay_on = directions.shop_pay_on(db)
        if self.pay_on:
            styles.create_label(row, 'Продал:', 'Card.TLabel').pack(side='left')
            self.seller.pack(side='left', padx=6)
        styles.create_button(body, 'Добавить в наряд', self.add, 'Primary.TButton').pack(fill='x', pady=(10, 0))
        self.fill()
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()
        self.search.focus_set()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        for card in self.shop.cards(self.search.get()):
            self.tree.insert('', 'end', iid=str(card.id), values=(
                card.name, card.category or '', money(card.price or 0), f'{card.quantity or 0:g}'))

    def add(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo('Магазин', 'Выберите товар в списке.', parent=self.dialog)
            return
        from models.stock import StockItem
        from services.order_service import OrderService
        card = self.db.query(StockItem).get(int(selection[0]))
        seller = next((p for p in self.people if p.title == self.seller.get()), None)             if self.pay_on else None
        if self.pay_on and seller is None:
            messagebox.showwarning('Магазин', 'Выберите, кто продал.', parent=self.dialog)
            return
        try:
            qty = max(1, int(self.qty.get()))
            OrderService(self.db).add_service_to_order(self.order.id, card.service_id,
                                                       employee_id=seller.id if seller else None,
                                                       quantity=qty)
        except (StockError, ValueError) as e:
            self.db.rollback()
            messagebox.showerror('Магазин', str(e), parent=self.dialog)
            return
        self.dialog.destroy()
        if self.on_added:
            self.on_added()
