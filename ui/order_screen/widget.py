"""
Экран одного наряда.

Раньше весь наряд — состав, оплата, время, печать — жил в одном файле
на полторы тысячи строк, где правка в одном месте задевала соседнее.
Теперь класс собран из частей: позиции, оплата, учёт времени. Здесь
осталась только сборка экрана и то, что не относится ни к одной части.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from utils import format_phone
from logger import log
import styles

from .items import OrderItemsMixin
from .payment import OrderPaymentMixin
from .timing import OrderTimingMixin

class OrderWidget(OrderItemsMixin, OrderPaymentMixin, OrderTimingMixin):
    """Вкладка одного наряда: состав, оплата, время работы."""

    def __init__(self, frame, order, db, order_service, salary_service, print_service, close_callback, parent_orders_tab=None):
        self.frame = frame
        self.order = order
        self.db = db
        self.order_service = order_service
        self.salary_service = salary_service
        self.print_service = print_service
        self.close_callback = close_callback
        self.parent_orders_tab = parent_orders_tab
        
        # Содержимое наряда лежит на белой карточке: раньше оно висело
        # прямо на сером фоне и выглядело незаконченным
        card = styles.create_card_frame(frame)
        card.pack(fill='both', expand=True, padx=2, pady=(6, 2))

        main_container = ttk.Frame(card, style='White.TFrame')
        main_container.pack(fill='both', expand=True, padx=18, pady=(12, 10))

        # Верхняя строка: машина, скидки, цены
        top_frame = ttk.Frame(main_container, style='White.TFrame')
        top_frame.pack(fill='x', pady=(0, 8))

        # Машина и клиент (слева)
        info_frame = ttk.Frame(top_frame, style='White.TFrame')
        info_frame.pack(side='left')

        vehicle_type_map = {
            'car': 'Легковой',
            'suv': 'Джип/Кроссовер/Пикап',
            'truck': 'Категория С (коммерческий)'
        }
        vehicle_type_display = vehicle_type_map.get(order.vehicle_type, order.vehicle_type)
        
        # Заголовок наряда: номер крупно, характеристики машины —
        # отдельной приглушённой строкой, чтобы глаз не спотыкался
        # о частокол вертикальных чёрточек
        header_row = ttk.Frame(info_frame, style='White.TFrame')
        header_row.pack(anchor='w', fill='x')

        ttk.Label(header_row, text=f"Наряд №{order.id}",
                  font=(styles.DEFAULT_FONT, 15, 'bold'),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text']).pack(side='left')

        ttk.Label(header_row, text=order.car.license_plate,
                  font=(styles.DEFAULT_FONT, 13, 'bold'),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['primary']).pack(side='left', padx=(14, 0))

        # Удаление — действие редкое и опасное, поэтому не кричит цветом
        if order.status == 'draft':
            styles.create_button(header_row, "Удалить наряд", self.delete_order,
                                 'Secondary.TButton').pack(side='left', padx=(16, 0))

        ttk.Label(header_row,
                  text=f"{vehicle_type_display} · {order.wheel_diameter}",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary']).pack(side='left', padx=(14, 0))

        if order.client:
            client_row = ttk.Frame(info_frame, style='White.TFrame')
            client_row.pack(anchor='w', fill='x', pady=(6, 0))

            client_info = order.client.name or ""
            if order.client.phone:
                client_info += f" · {format_phone(order.client.phone)}"
            client_text = client_info
            if order.auto_discount:
                client_text += "  (автоскидка 5%)"
            ttk.Label(client_row, text=client_text, font=(styles.DEFAULT_FONT, 10),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['success'] if order.auto_discount
                      else styles.COLORS['text']).pack(side='left')

            # Из наряда сразу в карточку: поправить телефон или добавить
            # ещё одну машину, не выходя из работы
            styles.create_button(client_row, "Карточка клиента",
                                 self.open_client_card, 'Secondary.TButton').pack(
                                     side='left', padx=(10, 0))

        # Сотрудники (под машиной)
        self.employees_label = ttk.Label(info_frame, text="",
                                         background=styles.COLORS['bg_card'],
                                         font=(styles.DEFAULT_FONT, 9),
                                         foreground=styles.COLORS['text_secondary'])
        self.employees_label.pack(anchor='w', pady=(4, 0))
        
        # Рекомендации (под сотрудниками)
        recommendations_frame = ttk.Frame(main_container, style='White.TFrame')
        recommendations_frame.pack(fill='x', pady=(2, 0))
        
        ttk.Label(recommendations_frame, text="Рекомендации:", background=styles.COLORS['bg_card'], foreground=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 9, 'bold')).pack(anchor='w')
        
        self.recommendations_text = tk.Text(recommendations_frame, height=2, font=styles.FONTS['normal'], 
                                           bg=styles.COLORS['bg_card'], fg=styles.COLORS['text'],
                                           relief='solid', borderwidth=1, wrap='word')
        self.recommendations_text.pack(fill='x', pady=(2, 5))
        
        # Устанавливаем placeholder и загружаем существующие рекомендации
        if order.recommendations:
            self.recommendations_text.insert('1.0', order.recommendations)
            self.recommendations_text.tag_configure('placeholder', foreground='#94a3b8')
        else:
            self.recommendations_text.insert('1.0', 'Рекомендации для клиента...')
            self.recommendations_text.tag_add('placeholder', '1.0', 'end')
            self.recommendations_text.tag_configure('placeholder', foreground='#94a3b8')
        
        # Обработчики для placeholder и автосохранения
        self.recommendations_text.bind('<FocusIn>', self.on_recommendations_focus_in)
        self.recommendations_text.bind('<FocusOut>', self.on_recommendations_focus_out)
        
        # Скидки (левее)
        discount_frame = ttk.Frame(top_frame, style='White.TFrame')
        discount_frame.pack(side='left', padx=(15, 0))
        
        ttk.Label(discount_frame, text="Скидки:", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 11, 'bold')).pack(anchor='w')
        
        disc_row = ttk.Frame(discount_frame, style='White.TFrame')
        disc_row.pack()
        
        ttk.Label(disc_row, text="Диски:", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 10)).pack(side='left', padx=(0, 3))
        self.rim_discount_var = tk.StringVar(value='0')
        rim_combo = ttk.Combobox(disc_row, textvariable=self.rim_discount_var, values=['0', '10', '20'], 
                                 width=5, font=(styles.DEFAULT_FONT, 10), state='readonly')
        rim_combo.pack(side='left', padx=(0, 3))
        ttk.Button(disc_row, text="OK", command=self.apply_rim_discount, width=3).pack(side='left', padx=(0, 10))
        
        ttk.Label(disc_row, text="Общ:", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 10)).pack(side='left', padx=(0, 3))
        self.general_discount_var = tk.StringVar(value='0')
        general_combo = ttk.Combobox(disc_row, textvariable=self.general_discount_var, values=['0', '10', '15'], 
                                      width=5, font=(styles.DEFAULT_FONT, 10), state='readonly')
        general_combo.pack(side='left', padx=(0, 3))
        ttk.Button(disc_row, text="OK", command=self.apply_general_discount, width=3).pack(side='left')
        
        # Цены (справа)
        price_frame = ttk.Frame(top_frame, style='White.TFrame')
        price_frame.pack(side='right')
        
        self.price_label = ttk.Label(price_frame, text="0.00 руб.", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 14, 'bold'), foreground='#2563eb')
        self.price_label.pack(anchor='e')
        
        self.discount_price_label = ttk.Label(price_frame, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 12, 'bold'), foreground='#059669')
        self.discount_price_label.pack(anchor='e')

        # Расходники и база для зарплаты: механик и кассир видят цифру сразу,
        # а не узнают её в конце месяца
        self.salary_base_label = ttk.Label(price_frame, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 9),
                                           foreground='#64748b')
        self.salary_base_label.pack(anchor='e')

        # Плановое время и его сохранение.
        # Время меняется только по кнопке: пока мастер прикидывает стоимость,
        # прогноз для очереди не должен прыгать туда-сюда.
        time_row = ttk.Frame(price_frame, style='White.TFrame')
        time_row.pack(anchor='e', pady=(4, 0))

        self.time_label = ttk.Label(time_row, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 10, 'bold'),
                                    foreground='#2563eb')
        self.time_label.pack(side='left', padx=(0, 8))

        self.save_order_button = styles.create_button(
        time_row, "Сохранить наряд", self.save_composition, 'Primary.TButton')
        self.save_order_button.pack(side='left')

        self.unsaved_label = ttk.Label(price_frame, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 9),
                                       foreground='#d97706')
        self.unsaved_label.pack(anchor='e')

        # Идентификатор отложенного автосохранения, чтобы отменять предыдущее
        self._autosave_job = None

        # Список услуг
        ttk.Label(main_container, text="Услуги:", font=(styles.DEFAULT_FONT, 9, 'bold'), style='ServiceHeading.TLabel').pack(fill='x', pady=(2, 1))
        
        tree_frame = ttk.Frame(main_container, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        # Высоту просим небольшую: таблица растянется по месту, а высокий
        # запрос выдавливал её за нижний край окна
        self.items_tree = ttk.Treeview(tree_frame, columns=('Услуга', 'Кол-во', 'Цена', 'Скидка', 'Итого'),
                                       show='headings', height=6)
        self.items_tree.heading('Услуга', text='Услуга')
        self.items_tree.heading('Кол-во', text='Кол-во')
        self.items_tree.heading('Цена', text='Цена')
        self.items_tree.heading('Скидка', text='Скидка %')
        self.items_tree.heading('Итого', text='Итого')
        
        # Ширина колонок
        self.items_tree.column('Услуга', width=250, anchor='w')
        self.items_tree.column('Кол-во', width=60, anchor='center')
        self.items_tree.column('Цена', width=90, anchor='center')
        self.items_tree.column('Скидка', width=90, anchor='center')
        self.items_tree.column('Итого', width=90, anchor='center')
        
        self.items_tree.pack(side='left', fill='both', expand=True)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.items_tree.yview)
        tree_scroll.pack(side='right', fill='y')
        self.items_tree.config(yscrollcommand=tree_scroll.set)
        
        # Inline редактирование количества по двойному клику
        self.items_tree.bind('<Double-1>', self.on_double_click)
        self.items_tree.bind('<Delete>', self.delete_item)
        
        # Entry для inline редактирования
        self.edit_entry = None
        
        # Загрузка данных
        self.refresh_items()

    def open_client_card(self):
        """Открыть карточку клиента этого наряда."""
        from ui.client_card import open_client_card

        if not self.order.client_id:
            messagebox.showinfo("Клиент не указан",
                                "В этом наряде клиент не заполнен.")
            return

        try:
            card = open_client_card(self.frame, self.db, self.order.client_id)
            # После закрытия карточки перечитываем наряд: имя и телефон
            # могли поменять
            self.frame.wait_window(card)
            self.db.refresh(self.order)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось открыть карточку: {e}")

    def on_recommendations_focus_in(self, event):
        """Убираем placeholder при получении фокуса"""
        content = self.recommendations_text.get('1.0', 'end-1c')
        if content == 'Рекомендации для клиента...':
            self.recommendations_text.delete('1.0', 'end')
            self.recommendations_text.tag_remove('placeholder', '1.0', 'end')

    def on_recommendations_focus_out(self, event):
        """Сохраняем рекомендации при потере фокуса"""
        content = self.recommendations_text.get('1.0', 'end-1c').strip()
        
        if not content:
            # Если пусто, показываем placeholder
            self.recommendations_text.delete('1.0', 'end')
            self.recommendations_text.insert('1.0', 'Рекомендации для клиента...')
            self.recommendations_text.tag_add('placeholder', '1.0', 'end')
            # Сохраняем пустое значение
            self.order.recommendations = None
        else:
            # Сохраняем введённый текст
            self.order.recommendations = content
        
        # Сохраняем в базу данных
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            log.error(f"Ошибка сохранения рекомендаций: {e}")

    def delete_order(self):
        """Удаляет непробитый наряд с подтверждением"""
        # Проверяем, что наряд - черновик (только черновики можно удалять)
        if self.order.status != 'draft':
            messagebox.showerror("Ошибка", "Нельзя удалить наряд в работе или оплаченный.\nМожно удалять только черновики.")
            return
        
        # Диалог подтверждения
        confirm = messagebox.askyesno(
            "Подтверждение удаления", 
            f"Вы действительно хотите удалить наряд №{self.order.id}?\n\n"
            f"Машина: {self.order.car.license_plate}\n"
            f"Этот наряд будет полностью удалён из базы данных.\n\n"
            f"Продолжить?",
            icon='warning'
        )
        
        if not confirm:
            return
        
        try:
            # Вызываем метод полного удаления
            success, message = self.order_service.hard_delete_unpaid_order(self.order.id)
            
            if success:
                messagebox.showinfo("Успех", message)
                # Закрываем вкладку с нарядом
                self.close_callback(self.order.id)
            else:
                messagebox.showerror("Ошибка", message)
        
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить наряд:\n{str(e)}")
