"""
Наряд блоками по направлениям: «Шиномонтаж» и «Мойка» (макеты от 26.10.2026).

Всё, что относится к направлению, — в его блоке: в шапке пост, мастера
или «Всё на: …», число услуг и сумма; под шапкой его услуги. Блок можно
свернуть до одной строки. Наряд с одним направлением — один блок.
Редкие действия (хранение, фото, «готово», удалить) — в меню «Ещё ▾».

Таблица услуг у каждого блока своя, но правка строк общая
(OrderItemsMixin): перед обработкой события текущей становится таблица,
в которой щёлкнули.
"""
import tkinter as tk
from tkinter import ttk

import styles
from services import directions

COLUMNS = ('Услуга', 'Кол-во', 'Цена', 'Скидка', 'Итого', 'Кто')
COLORS = {directions.TIRE: ('#1d4ed8', '#dbeafe'), directions.WASH: ('#0f766e', '#ccfbf1')}


def _plural(n):
    if n % 10 == 1 and n % 100 != 11:
        return 'услуга'
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 'услуги'
    return 'услуг'


class OrderBlocksMixin:
    """Блоки направлений в наряде и меню «Ещё»."""

    # ------------------------------------------------------------------
    # Шапка наряда: «Ещё ▾»
    # ------------------------------------------------------------------

    def build_more_menu(self, parent):
        self.more_button = styles.create_button(parent, "Ещё ▾", self.show_more_menu,
                                                'Compact.Secondary.TButton')
        self.more_button.pack(side='left', padx=(10, 0))
        # Кнопка «готово» живёт в меню, но её состояние (идёт отправка)
        # по-прежнему держим тут: tell_ready выключает её на время
        self.ready_button = ttk.Button(parent)

    def show_more_menu(self):
        menu = tk.Menu(self.frame, tearoff=0)
        if self.order.client:
            state = 'normal' if str(self.ready_button.cget('state')) != 'disabled' else 'disabled'
            menu.add_command(label="Сообщить, что готово", command=self.tell_ready, state=state)
            menu.add_command(label="Фото от мастеров", command=self.open_photos)
        menu.add_command(label="Всё по машине", command=self.open_car)
        if directions.TIRE in directions.parse(self.order.directions):
            menu.add_separator()
            menu.add_command(label="Принять на хранение", command=self.storage_accept)
            stored = self._stored_sets()
            menu.add_command(label="Выдать с хранения" + (
                f"  №{', №'.join(str(s.id) for s in stored)}" if stored else ""),
                command=self.storage_release)
        if self.order.status == 'draft':
            menu.add_separator()
            menu.add_command(label="Удалить наряд", command=self.delete_order)
        x = self.more_button.winfo_rootx()
        y = self.more_button.winfo_rooty() + self.more_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
        self._more_menu = menu

    # ------------------------------------------------------------------
    # Блоки
    # ------------------------------------------------------------------

    def build_blocks(self, parent):
        self.blocks_holder = ttk.Frame(parent, style='White.TFrame')
        self.blocks_holder.pack(fill='both', expand=True)
        self.trees = {}
        self.block_parts = {}
        # Свёрнутые блоки. Пока человек не нажимал, сворачиваем «чужое»
        # направление, если в наряде оба: мойщику шиномонтаж не нужен
        self.collapsed_by_hand = {}
        self.render_blocks()

    def _mode(self):
        tab = getattr(self, 'parent_orders_tab', None)
        return getattr(tab, 'mode', directions.TIRE) if tab is not None else directions.TIRE

    def _is_collapsed(self, direction, have):
        if direction in self.collapsed_by_hand:
            return self.collapsed_by_hand[direction]
        return len(have) > 1 and direction != self._mode()

    def render_blocks(self):
        for child in self.blocks_holder.winfo_children():
            child.destroy()
        self.trees, self.block_parts = {}, {}
        have = directions.parse(self.order.directions)
        self._rendered_directions = list(have)
        for direction in have:
            self._block(direction, have)
        # Подпись мастеров нужна всегда (её обновляет таймер), даже когда
        # блока шиномонтажа нет
        if not hasattr(self, 'employees_label') or not self.employees_label.winfo_exists():
            self.employees_label = ttk.Label(self.blocks_holder)
        missing = [d for d in directions.enabled(self.db) if d not in have]
        if missing and self.order.status != 'paid':
            row = ttk.Frame(self.blocks_holder, style='White.TFrame')
            row.pack(anchor='w', fill='x', pady=(6, 0))
            for direction in missing:
                styles.create_button(row, f'+ {directions.TITLES[direction]}',
                                     lambda d=direction: self.add_direction(d),
                                     'Compact.Secondary.TButton').pack(side='left', padx=(0, 6))
        # Совместимость: правка строк работает с «текущей» таблицей
        if self.trees:
            self.items_tree = next(iter(self.trees.values()))

    def _block(self, direction, have):
        fg, bg = COLORS[direction]
        collapsed = self._is_collapsed(direction, have)
        block = tk.Frame(self.blocks_holder, bg=styles.COLORS['bg_card'],
                         highlightthickness=1, highlightbackground=styles.COLORS['border_strong'])
        block.pack(fill='both' if not collapsed else 'x', expand=not collapsed, pady=(0, 6))
        head = tk.Frame(block, bg=bg)
        head.pack(fill='x')

        def pill(text, command):
            button = tk.Label(head, text=text, bg='#ffffff', fg=styles.COLORS['text'], cursor='hand2',
                              font=(styles.DEFAULT_FONT, 9), padx=8, pady=1,
                              highlightthickness=1, highlightbackground=styles.COLORS['border_strong'])
            button.pack(side='left', padx=(6, 0), pady=4)
            button.bind('<Button-1>', lambda e: command())
            return button

        def note(text):
            label = tk.Label(head, text=text, bg=bg, fg=styles.COLORS['text_secondary'],
                             font=(styles.DEFAULT_FONT, 9))
            label.pack(side='left', padx=(8, 0))
            return label

        tk.Label(head, text=directions.TITLES[direction].upper(), bg=bg, fg=fg,
                 font=(styles.DEFAULT_FONT, 10, 'bold')).pack(side='left', padx=(10, 2), pady=4)
        open_order = self.order.status != 'paid'

        if direction == directions.TIRE:
            vehicle = {'car': 'Легковой', 'suv': 'Джип/Кроссовер', 'truck': 'Категория С'}.get(
                self.order.vehicle_type, self.order.vehicle_type or '')
            note(' · '.join(x for x in (vehicle, self.order.wheel_diameter) if x))
            from services.live_queue_service import LiveQueueService
            if open_order and (self.order.post_number or LiveQueueService(self.db).enabled()):
                self.post_label = pill(self._post_text() + ' ▾', self.change_post)
            # Мастера: нажимаются, только когда их выбирают на наряд
            if directions.tire_assign(self.db) and open_order:
                self.employees_label = pill('Мастера ▾', self.choose_masters)
            else:
                self.employees_label = ttk.Label(head, text='', background=bg,
                                                 font=(styles.DEFAULT_FONT, 9))
                self.employees_label.pack(side='left', padx=(8, 0))
        else:
            note(directions.class_title(self.order.wash_class))
            if open_order:
                text = (f'Пост мойки {self.order.wash_post_number}' if self.order.wash_post_number
                        else 'Пост мойки не выбран')
                pill(text + ' ▾', self.change_wash_post)
                pill('Всё на: … ▾', self.assign_all_wash)

        toggle = tk.Label(head, text='развернуть ▾' if collapsed else 'свернуть ▴', bg='#ffffff',
                          fg=styles.COLORS['text_secondary'], cursor='hand2',
                          font=(styles.DEFAULT_FONT, 9), padx=8, pady=1,
                          highlightthickness=1, highlightbackground=styles.COLORS['border_strong'])
        toggle.pack(side='right', padx=(0, 8), pady=4)
        toggle.bind('<Button-1>', lambda e, d=direction: self.toggle_block(d))
        summary = tk.Label(head, text='', bg=bg, fg=styles.COLORS['text'],
                           font=(styles.DEFAULT_FONT, 10, 'bold'))
        summary.pack(side='right', padx=(0, 10))
        # Услуги «чужого» направления — списком: кнопки сверху показывают
        # только выбранное в переключателе
        if open_order and direction != self._mode():
            add = tk.Label(head, text=f'+ услуга {"мойки" if direction == directions.WASH else "шиномонтажа"}',
                           bg='#ffffff', fg=styles.COLORS['primary'], cursor='hand2',
                           font=(styles.DEFAULT_FONT, 9), padx=8, pady=1,
                           highlightthickness=1, highlightbackground=styles.COLORS['primary'])
            add.pack(side='right', padx=(0, 8), pady=4)
            add.bind('<Button-1>', lambda e, d=direction: self.pick_services(d))

        body = ttk.Frame(block, style='White.TFrame')
        if not collapsed:
            body.pack(fill='both', expand=True)
        tree = ttk.Treeview(body, columns=COLUMNS, show='headings', height=4)
        for column, title, width, anchor in (('Услуга', 'Услуга', 250, 'w'), ('Кол-во', 'Кол-во', 60, 'center'),
                                             ('Цена', 'Цена', 90, 'center'), ('Скидка', 'Скидка %', 90, 'center'),
                                             ('Итого', 'Итого', 90, 'center'), ('Кто', 'Кто делал', 120, 'center')):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor=anchor)
        # Кто делал — только у мойки: её начисляют тому, кто мыл
        if not directions.assigned(self.db, direction):
            tree.configure(displaycolumns=COLUMNS[:5])
        tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(body, orient='vertical', command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.config(yscrollcommand=scroll.set)
        tree.bind('<Double-1>', lambda e: self._on_tree(e, self.on_double_click))
        tree.bind('<Delete>', lambda e: self._on_tree(e, self.delete_item))
        tree.bind('<FocusIn>', lambda e: setattr(self, 'items_tree', e.widget))
        self.trees[direction] = tree
        self.block_parts[direction] = {'block': block, 'summary': summary, 'body': body}

    def _on_tree(self, event, handler):
        self.items_tree = event.widget
        return handler(event)

    def toggle_block(self, direction):
        have = directions.parse(self.order.directions)
        self.collapsed_by_hand[direction] = not self._is_collapsed(direction, have)
        self.render_blocks()
        self.refresh_items()

    def refresh_block_summaries(self, items):
        from services.order_service import OrderService
        for direction, parts in self.block_parts.items():
            mine = [i for i in items if (getattr(i, 'direction', None) or 'tire') == direction]
            total = sum(OrderService.item_total(i) for i in mine)
            n = len(mine)
            parts['summary'].config(text=f'{n} {_plural(n)} · {total:,.0f} ₽'.replace(',', ' '))

    def refresh_directions(self):
        """Направления наряда или режим сверху поменялись — перерисовать."""
        self.db.refresh(self.order)
        self.collapsed_by_hand = {}
        self.render_blocks()
        self.refresh_items()
        self.update_employees_display()
