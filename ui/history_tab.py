import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from models import Car, WorkOrder, WorkOrderItem
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from services import ClientService
from utils import normalize_plate, format_phone
import styles
from logger import log

class HistoryTab:
    def __init__(self, parent, db):
        self.db = db
        self.client_service = ClientService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.current_page = 1
        self.items_per_page = 30
        self.total_orders = 0

        # Активный фильтр. None во всех полях = показываем все наряды.
        self.current_car_ids = None
        self.current_client_id = None
        self.current_filter_text = None

        search_card = styles.create_card_frame(self.frame)
        search_card.pack(fill='x', padx=15, pady=(15, 10))

        search_inner = ttk.Frame(search_card, style='White.TFrame')
        search_inner.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(search_inner, "Поиск по номеру автомобиля или телефону клиента",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))

        search_frame = ttk.Frame(search_inner, style='White.TFrame')
        search_frame.pack(fill='x')

        styles.create_label(search_frame, "Номер авто или телефон:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.license_entry = styles.create_entry(search_frame, width=24)
        self.license_entry.pack(side='left', padx=(0, 10))
        self.license_entry.bind('<Return>', lambda e: self.search_history())
        styles.create_button(search_frame, "Найти", self.search_history, 'Primary.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(search_frame, "Показать все", self.show_all_history, 'Secondary.TButton').pack(side='left')

        # Подсказка о том, что именно сейчас показано
        self.filter_label = ttk.Label(search_inner, text="", font=(styles.DEFAULT_FONT, 9),
                                      foreground='#059669')
        self.filter_label.pack(anchor='w', pady=(8, 0))
        
        history_card = styles.create_card_frame(self.frame)
        history_card.pack(fill='both', expand=True, padx=15, pady=(0, 15))
        
        history_inner = ttk.Frame(history_card, style='White.TFrame')
        history_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(history_inner, "История нарядов", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))
        
        tree_frame = ttk.Frame(history_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        self.history_tree = ttk.Treeview(tree_frame, columns=('Статус', 'Дата', 'Наряд №', 'Автомобиль', 'Услуг', 'Сумма', 'Оплата'), show='headings')
        self.history_tree.heading('Статус', text='')
        self.history_tree.heading('Дата', text='Дата')
        self.history_tree.heading('Наряд №', text='Наряд №')
        self.history_tree.heading('Автомобиль', text='Автомобиль')
        self.history_tree.heading('Услуг', text='Кол-во услуг')
        self.history_tree.heading('Сумма', text='Сумма')
        self.history_tree.heading('Оплата', text='Способ оплаты')
        self.history_tree.column('Статус', width=40, anchor='center')
        self.history_tree.column('Дата', width=130)
        self.history_tree.column('Наряд №', width=80)
        self.history_tree.column('Автомобиль', width=120)
        self.history_tree.column('Услуг', width=120)
        self.history_tree.column('Сумма', width=90)
        self.history_tree.column('Оплата', width=120)
        self.history_tree.pack(side='left', fill='both', expand=True)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.history_tree.yview)
        tree_scroll.pack(side='right', fill='y')
        self.history_tree.config(yscrollcommand=tree_scroll.set)
        
        self.history_tree.bind('<Double-1>', self.show_order_details)
        
        # Пагинация
        pagination_frame = ttk.Frame(history_inner, style='White.TFrame')
        pagination_frame.pack(fill='x', pady=(10, 0))
        
        self.info_label = styles.create_label(pagination_frame, "", 'Card.TLabel')
        self.info_label.pack(side='left', padx=(0, 20))
        
        self.prev_button = styles.create_button(pagination_frame, "◀ Предыдущая", self.prev_page, 'Secondary.TButton')
        self.prev_button.pack(side='left', padx=(0, 10))
        
        self.page_label = styles.create_label(pagination_frame, "Страница 1", 'Card.TLabel')
        self.page_label.pack(side='left', padx=(0, 10))
        
        self.next_button = styles.create_button(pagination_frame, "Следующая ▶", self.next_page, 'Secondary.TButton')
        self.next_button.pack(side='left')
        
        # Кнопка удаления наряда
        self.delete_button = styles.create_button(pagination_frame, "Удалить выбранный наряд",
                                                  self.delete_selected_order, 'Danger.TButton')
        self.delete_button.pack(side='right', padx=(10, 0))

        self.reprint_button = styles.create_button(pagination_frame, "Перепечатать чек",
                                                   self.reprint_receipt, 'Secondary.TButton')
        self.reprint_button.pack(side='right')

        self.warranty_button = styles.create_button(pagination_frame, "Гарантия",
                                                    self.toggle_warranty, 'Secondary.TButton')
        self.warranty_button.pack(side='right', padx=(0, 6))

        self.refund_button = styles.create_button(pagination_frame, "Возврат / сторно",
                                                  self.refund_order, 'Secondary.TButton')
        self.refund_button.pack(side='right', padx=(0, 6))
        
        # Загружаем все наряды при открытии вкладки
        self.load_page()
    
    def search_history(self):
        """
        Поиск нарядов по номеру автомобиля или по телефону клиента.

        Сначала пробуем номер машины — тогда показываем наряды по ней одной.
        Если не нашли, ищем клиента по телефону или имени и показываем
        наряды сразу по всем его машинам.
        """
        query_text = self.license_entry.get().strip()
        if not query_text:
            messagebox.showwarning("Предупреждение", "Введите номер автомобиля или телефон клиента")
            return

        try:
            # 1. Номер автомобиля (в любом написании)
            plate = normalize_plate(query_text)
            car = self.db.query(Car).filter(Car.license_plate == plate).first() if plate else None

            if car:
                self.current_car_ids = [car.id]
                self.current_client_id = None
                owner = car.client
                if owner:
                    self.current_filter_text = (
                        f"Автомобиль {car.license_plate} · владелец: "
                        f"{owner.name or 'без имени'} {format_phone(owner.phone) if owner.phone else ''}".strip()
                    )
                else:
                    self.current_filter_text = f"Автомобиль {car.license_plate}"
                self.current_page = 1
                self.load_page()
                return

            # 2. Клиент по телефону или имени — показываем все его машины
            clients = self.client_service.search(query_text, limit=1)
            if clients:
                client = clients[0]
                cars = self.client_service.get_client_cars(client.id)
                self.current_car_ids = [c.id for c in cars]
                self.current_client_id = client.id
                plates = ', '.join(c.license_plate for c in cars) or 'машин не закреплено'
                self.current_filter_text = (
                    f"Клиент {client.name or 'без имени'} "
                    f"{format_phone(client.phone) if client.phone else ''} · {plates}".strip()
                )
                self.current_page = 1
                self.load_page()
                return

            messagebox.showinfo(
                "Информация",
                f"По запросу «{query_text}» ничего не найдено.\n\n"
                f"Можно искать по номеру автомобиля, телефону клиента или его имени."
            )
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось выполнить поиск:\n{str(e)}")

    def show_all_history(self):
        self.current_car_ids = None
        self.current_client_id = None
        self.current_filter_text = None
        self.license_entry.delete(0, 'end')
        self.current_page = 1
        self.load_page()
    
    def load_page(self):
        try:
            # Импортируем TireStorage для фильтрации
            from models import TireStorage
            
            # Формируем запрос в зависимости от наличия фильтра
            query = self.db.query(WorkOrder).options(joinedload(WorkOrder.items))
            
            # Исключаем наряды хранения шин (которые имеют связь с tire_storage)
            query = query.outerjoin(TireStorage, WorkOrder.id == TireStorage.work_order_id)
            query = query.filter(TireStorage.id == None)
            
            # Фильтр: конкретная машина, либо все машины найденного клиента
            conditions = []
            if self.current_car_ids:
                conditions.append(WorkOrder.car_id.in_(self.current_car_ids))
            if self.current_client_id:
                conditions.append(WorkOrder.client_id == self.current_client_id)
            if conditions:
                query = query.filter(or_(*conditions))
            elif self.current_car_ids is not None or self.current_client_id is not None:
                # Клиент найден, но за ним не закреплено ни одной машины
                query = query.filter(False)
            
            # Получаем общее количество нарядов (исключая хранение и включая удалённые)
            self.total_orders = query.filter(WorkOrder.status == 'paid').count()
            
            # Вычисляем количество страниц
            total_pages = (self.total_orders + self.items_per_page - 1) // self.items_per_page
            
            # Получаем наряды для текущей страницы (исключая хранение и включая удалённые)
            offset = (self.current_page - 1) * self.items_per_page
            orders = query.filter(WorkOrder.status == 'paid').order_by(WorkOrder.paid_at.desc()).offset(offset).limit(self.items_per_page).all()
            
            # Очищаем таблицу
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            
            # Настраиваем тег для удалённых нарядов
            self.history_tree.tag_configure('deleted', foreground='#dc3545')
            self.history_tree.tag_configure('refunded', foreground=styles.COLORS['warning'])
            self.history_tree.tag_configure('warranty', foreground=styles.COLORS['secondary'])
            
            # Заполняем таблицу
            for order in orders:
                items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order.id).all()
                total_services = sum(item.quantity for item in items)
                services_text = f"{total_services} {'услуга' if total_services == 1 else 'услуг' if total_services > 4 or total_services == 0 else 'услуги'}"
                
                payment_method = 'Наличные' if order.payment_method == 'cash' else 'Безнал'
                
                # Пометка состояния: удалён, возвращён или гарантийный.
                # Строка дополнительно подкрашивается по тегу.
                refunded = float(order.refunded_amount or 0)
                paid_amount = float(order.total_amount or 0)

                if order.is_deleted:
                    status_icon, tag = '×', 'deleted'
                elif refunded >= paid_amount > 0:
                    status_icon, tag = '↩', 'refunded'
                elif refunded > 0:
                    status_icon, tag = '~', 'refunded'
                elif order.is_warranty:
                    status_icon, tag = 'Г', 'warranty'
                else:
                    status_icon, tag = '', None

                tags = (str(order.id), tag) if tag else (str(order.id),)

                # В сумме показываем остаток после возврата
                amount_text = f"{paid_amount:.2f} ₽"
                if refunded > 0:
                    amount_text = f"{paid_amount - refunded:.2f} ₽ (возврат {refunded:.0f})"

                self.history_tree.insert('', 'end', values=(
                    status_icon,
                    order.paid_at.strftime('%d.%m.%Y %H:%M'),
                    order.id,
                    order.car.license_plate,
                    services_text,
                    amount_text,
                    payment_method
                ), tags=tags)
            
            # Обновляем информацию о пагинации
            is_filtered = self.current_filter_text is not None
            info_text = (f"Найдено нарядов: {self.total_orders}" if is_filtered
                         else f"Всего нарядов: {self.total_orders}")
            self.info_label.config(text=info_text)
            self.filter_label.config(text=self.current_filter_text or "")
            self.page_label.config(text=f"Страница {self.current_page} из {total_pages if total_pages > 0 else 1}")
            
            # Управляем кнопками
            self.prev_button.config(state='normal' if self.current_page > 1 else 'disabled')
            self.next_button.config(state='normal' if self.current_page < total_pages else 'disabled')
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось загрузить историю нарядов:\n{str(e)}")
            # Очищаем таблицу при ошибке
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
    
    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_page()
    
    def next_page(self):
        total_pages = (self.total_orders + self.items_per_page - 1) // self.items_per_page
        if self.current_page < total_pages:
            self.current_page += 1
            self.load_page()
    
    def show_order_details(self, event):
        selected = self.history_tree.selection()
        if not selected:
            return
        
        try:
            order_id = int(self.history_tree.item(selected[0])['tags'][0])
            order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
            
            if not order:
                return
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            log.error(f"ERROR in show_order_details: {error_details}")
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось загрузить детали наряда:\n{str(e)}")
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title(f"Детали наряда #{order_id}")
        dialog.geometry("750x650")
        dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(dialog, self.frame.winfo_toplevel())
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(content, f"Наряд #{order.id}", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        info_frame = ttk.Frame(content, style='White.TFrame')
        info_frame.pack(fill='x', pady=(0, 15))
        
        styles.create_label(info_frame, f"Дата: {order.paid_at.strftime('%d.%m.%Y %H:%M')}", 'Card.TLabel').pack(anchor='w', pady=2)
        styles.create_label(info_frame, f"Автомобиль: {order.car.license_plate}", 'Card.TLabel').pack(anchor='w', pady=2)
        
        if order.client:
            client_info = f"{order.client.name or ''}"
            if order.client.client_number:
                client_info += f" (#{order.client.client_number})"
            styles.create_label(info_frame, f"Клиент: {client_info}", 'Card.TLabel').pack(anchor='w', pady=2)
        
        styles.create_label(info_frame, f"Диаметр: {order.wheel_diameter}", 'Card.TLabel').pack(anchor='w', pady=2)
        
        styles.create_label(content, "Список услуг:", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))
        
        tree_frame = ttk.Frame(content, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True, pady=(0, 15))
        
        items_tree = ttk.Treeview(tree_frame, columns=('Услуга', 'Количество', 'Скидка', 'Цена', 'Итого'), show='headings')
        items_tree.heading('Услуга', text='Услуга')
        items_tree.heading('Количество', text='Кол-во')
        items_tree.heading('Скидка', text='Скидка %')
        items_tree.heading('Цена', text='Цена')
        items_tree.heading('Итого', text='Итого')
        
        items_tree.column('Услуга', width=250)
        items_tree.column('Количество', width=80)
        items_tree.column('Скидка', width=80)
        items_tree.column('Цена', width=100)
        items_tree.column('Итого', width=100)
        
        items_tree.pack(side='left', fill='both', expand=True)
        
        items_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=items_tree.yview)
        items_scroll.pack(side='right', fill='y')
        items_tree.config(yscrollcommand=items_scroll.set)
        
        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        for item in items:
            item_total = item.price * item.quantity * (1 - item.discount_percent / 100)
            items_tree.insert('', 'end', values=(
                item.service.name,
                item.quantity,
                item.discount_percent,
                f"{item.price:.2f}",
                f"{item_total:.2f}"
            ))
        
        total_frame = ttk.Frame(content, style='White.TFrame')
        total_frame.pack(fill='x', pady=(0, 10))
        
        styles.create_label(total_frame, f"Общая скидка: {order.general_discount}%", 'Card.TLabel').pack(anchor='w', pady=2)
        
        auto_discount_text = f"Автоскидка 5%: {'Да' if order.auto_discount else 'Нет'}"
        styles.create_label(total_frame, auto_discount_text, 'Card.TLabel').pack(anchor='w', pady=2)
        
        payment_method = 'Наличные' if order.payment_method == 'cash' else 'Безналичный'
        styles.create_label(total_frame, f"Способ оплаты: {payment_method}", 'Card.TLabel').pack(anchor='w', pady=2)
        
        total_label = styles.create_label(total_frame, f"ИТОГО: {order.total_amount:.2f} руб.", 'CardHeading.TLabel')
        total_label.pack(anchor='w', pady=(10, 0))
        total_label.configure(font=(styles.DEFAULT_FONT, 16, 'bold'), foreground=styles.COLORS['primary'])
        
        # Кнопки действий
        buttons_frame = ttk.Frame(content, style='White.TFrame')
        buttons_frame.pack(fill='x', pady=(10, 0))
        
        styles.create_button(buttons_frame, "Удалить наряд",                            lambda: self.delete_order(order_id, dialog), 
                           'Danger.TButton').pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        styles.create_button(buttons_frame, "Закрыть", dialog.destroy, 'Secondary.TButton').pack(side='left', fill='x', expand=True)
    
    def selected_order_id(self):
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showinfo("Выбор", "Выберите наряд в списке")
            return None
        return int(self.history_tree.item(selection[0])['tags'][0])

    def refund_order(self):
        """
        Вернуть деньги по наряду или сторнировать ошибочную оплату.

        В отличие от удаления, наряд остаётся в истории: работа
        выполнялась, и это должно быть видно.
        """
        from services import OrderService

        order_id = self.selected_order_id()
        if not order_id:
            return

        order_service = OrderService(self.db)
        order = order_service.get_order_by_id(order_id, include_deleted=True)
        if not order:
            messagebox.showerror("Ошибка", f"Наряд №{order_id} не найден")
            return

        paid = float(order.total_amount or 0)
        already = float(order.refunded_amount or 0)
        available = round(paid - already, 2)

        if available <= 0:
            messagebox.showinfo("Возврат невозможен",
                                f"По наряду №{order_id} уже возвращена вся сумма")
            return

        dialog = tk.Toplevel(self.frame)
        dialog.title(f"Возврат по наряду №{order_id}")
        dialog.geometry("430x400")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, f"Наряд №{order_id}",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 4))
        ttk.Label(content,
                  text=f"{order.car.license_plate if order.car else '—'}  ·  "
                       f"оплачено {paid:.2f} руб."
                       + (f"  ·  уже возвращено {already:.2f} руб." if already else ''),
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary']).pack(anchor='w', pady=(0, 15))

        styles.create_label(content, "Что делаем:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        kind_var = tk.StringVar(value='Возврат денег клиенту')
        ttk.Combobox(content, textvariable=kind_var, state='readonly',
                     values=['Возврат денег клиенту', 'Сторно (пробили по ошибке)'],
                     font=styles.FONTS['normal']).pack(fill='x', pady=(0, 12))

        styles.create_label(content, "Сумма возврата, руб.:",
                            'Card.TLabel').pack(anchor='w', pady=(0, 5))
        amount_entry = styles.create_entry(content, width=20)
        amount_entry.insert(0, f"{available:.2f}")
        amount_entry.pack(fill='x', pady=(0, 4))
        ttk.Label(content, text=f"Доступно к возврату: {available:.2f} руб.",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary']).pack(anchor='w', pady=(0, 12))

        styles.create_label(content, "Причина:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        reason_entry = styles.create_entry(content, width=40)
        reason_entry.pack(fill='x', pady=(0, 8))

        ttk.Label(content,
                  text="Начисления зарплаты откатятся соразмерно возвращаемой сумме.",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary'],
                  wraplength=370, justify='left').pack(anchor='w', pady=(0, 15))

        def apply_refund():
            try:
                amount = float(amount_entry.get().replace(',', '.'))
            except ValueError:
                messagebox.showerror("Ошибка", "Сумма должна быть числом", parent=dialog)
                return

            reason = reason_entry.get().strip()
            if not reason:
                messagebox.showerror("Ошибка", "Укажите причину возврата", parent=dialog)
                return

            kind = (OrderService.REVERSAL if kind_var.get().startswith('Сторно')
                    else OrderService.REFUND)

            if not messagebox.askyesno(
                    "Подтверждение",
                    f"{kind_var.get()} на сумму {amount:.2f} руб. по наряду №{order_id}?\n\n"
                    f"Действие будет записано в журнал.", parent=dialog):
                return

            success, message = order_service.refund_order(
                order_id, amount=amount, reason=reason, refund_type=kind)

            if success:
                dialog.destroy()
                messagebox.showinfo("Готово", message)
                self.load_page()
            else:
                messagebox.showerror("Ошибка", message, parent=dialog)

        styles.create_button(content, "Провести", apply_refund,
                             'Danger.TButton').pack(fill='x')

    def toggle_warranty(self):
        """Отметить наряд гарантийной переделкой или снять отметку."""
        from services import OrderService

        order_id = self.selected_order_id()
        if not order_id:
            return

        order_service = OrderService(self.db)
        order = order_service.get_order_by_id(order_id, include_deleted=True)
        if not order:
            return

        if order.is_warranty:
            if messagebox.askyesno("Снять отметку",
                                   f"Наряд №{order_id} отмечен как гарантийная переделка.\n\n"
                                   f"Снять отметку?"):
                order_service.set_warranty(order_id, False)
                self.load_page()
            return

        reason = simpledialog.askstring(
            "Гарантийная переделка",
            f"Наряд №{order_id} — переделка по гарантии.\n\n"
            f"Такой наряд не попадёт в выручку и средний чек.\n\n"
            f"Причина:",
            parent=self.frame)
        if reason is None:
            return

        try:
            order_service.set_warranty(order_id, True, reason=reason)
            self.load_page()
            messagebox.showinfo("Готово",
                                f"Наряд №{order_id} отмечен как гарантийная переделка")
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", str(e))

    def reprint_receipt(self):
        """
        Собрать чек заново по данным наряда и открыть его.

        Нужно, когда клиент потерял чек, бухгалтерии нужен дубликат или
        печать сорвалась при оплате.
        """
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showinfo("Выбор", "Выберите наряд в списке")
            return

        order_id = int(self.history_tree.item(selection[0])['tags'][0])

        try:
            from services import OrderService, PrintService

            order_service = OrderService(self.db)
            order = order_service.get_order_by_id(order_id, include_deleted=True)
            if not order:
                messagebox.showerror("Ошибка", f"Наряд №{order_id} не найден")
                return

            items = order_service.get_order_items(order_id)
            total = float(order.total_amount or 0)
            path = PrintService().generate_receipt(order, items, total)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось собрать чек:\n{e}")
            return

        # Печатаем и заодно открываем: если принтер недоступен,
        # чек хотя бы будет на экране
        import os
        import platform

        printed = False
        if platform.system() == 'Windows':
            try:
                os.startfile(path, "print")
                printed = True
            except Exception as e:
                log.error(f"Не удалось отправить на печать: {e}")

        if not printed:
            try:
                if platform.system() == 'Windows':
                    os.startfile(path)
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', path])
            except Exception as e:
                log.error(f"Не удалось открыть чек: {e}")

        messagebox.showinfo(
            "Чек готов",
            f"Чек по наряду №{order_id} "
            + ("отправлен на печать." if printed else f"сохранён:\n{path}"))

    def delete_selected_order(self):
        """Удалить выбранный в таблице наряд"""
        selected = self.history_tree.selection()
        if not selected:
            messagebox.showwarning("Предупреждение", "Выберите наряд для удаления")
            return
        
        order_id = int(self.history_tree.item(selected[0])['tags'][0])
        
        # Вызываем диалог подтверждения удаления
        from services.order_service import OrderService
        
        # Диалог подтверждения
        confirm_dialog = tk.Toplevel(self.frame)
        confirm_dialog.title("Подтверждение удаления")
        confirm_dialog.geometry("450x250")
        confirm_dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(confirm_dialog, self.frame.winfo_toplevel())
        confirm_dialog.grab_set()
        
        content = ttk.Frame(confirm_dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        warning = styles.create_label(content, f"⚠ Удалить наряд №{order_id}?", 'CardHeading.TLabel')
        warning.pack(anchor='w', pady=(0, 10))
        warning.configure(foreground='#d32f2f')
        
        info = styles.create_label(content, 
                                   "Это действие:\n" +
                                   "• Пометит наряд как удалённый\n" +
                                   "• Отменит начисления ЗП\n" +
                                   "• Исключит наряд из статистики",
                                   'Card.TLabel')
        info.pack(anchor='w', pady=(0, 15))
        
        reason_label = styles.create_label(content, "Причина удаления (необязательно):", 'Card.TLabel')
        reason_label.pack(anchor='w', pady=(0, 5))
        
        reason_entry = ttk.Entry(content, font=(styles.DEFAULT_FONT, 11))
        reason_entry.pack(fill='x', pady=(0, 15))
        
        def confirm_delete():
            try:
                reason = reason_entry.get().strip()
                order_service = OrderService(self.db)
                success, message = order_service.delete_work_order(order_id, reason)
                
                confirm_dialog.destroy()
                
                if success:
                    messagebox.showinfo("Успех", message)
                    self.load_page()  # Перезагружаем список
                else:
                    messagebox.showerror("Ошибка", message)
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                log.error(f"ERROR in confirm_delete (delete_selected_order): {error_details}")
                confirm_dialog.destroy()
                messagebox.showerror("Ошибка", f"Не удалось удалить наряд:\n{str(e)}")
        
        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x')
        
        styles.create_button(buttons, "Отмена", confirm_dialog.destroy, 
                           'Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        styles.create_button(buttons, "Удалить", confirm_delete, 
                           'Danger.TButton').pack(side='left', fill='x', expand=True)
    
    def delete_order(self, order_id, dialog):
        """Удалить наряд (мягкое удаление) - вызывается из деталей наряда"""
        from services.order_service import OrderService
        
        # Диалог подтверждения
        confirm_dialog = tk.Toplevel(dialog)
        confirm_dialog.title("Подтверждение удаления")
        confirm_dialog.geometry("450x250")
        confirm_dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(confirm_dialog, dialog)
        confirm_dialog.transient(dialog)
        confirm_dialog.grab_set()
        
        content = ttk.Frame(confirm_dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        warning = styles.create_label(content, f"⚠ Удалить наряд №{order_id}?", 'CardHeading.TLabel')
        warning.pack(anchor='w', pady=(0, 10))
        warning.configure(foreground='#d32f2f')
        
        info = styles.create_label(content, 
                                   "Это действие:\n" +
                                   "• Пометит наряд как удалённый\n" +
                                   "• Отменит начисления ЗП\n" +
                                   "• Исключит наряд из статистики",
                                   'Card.TLabel')
        info.pack(anchor='w', pady=(0, 15))
        
        reason_label = styles.create_label(content, "Причина удаления (необязательно):", 'Card.TLabel')
        reason_label.pack(anchor='w', pady=(0, 5))
        
        reason_entry = ttk.Entry(content, font=(styles.DEFAULT_FONT, 11))
        reason_entry.pack(fill='x', pady=(0, 15))
        
        def confirm_delete():
            try:
                reason = reason_entry.get().strip()
                order_service = OrderService(self.db)
                success, message = order_service.delete_work_order(order_id, reason)
                
                confirm_dialog.destroy()
                dialog.destroy()
                
                if success:
                    messagebox.showinfo("Успех", message)
                    self.load_page()  # Перезагружаем список
                else:
                    messagebox.showerror("Ошибка", message)
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                log.error(f"ERROR in confirm_delete (delete_order): {error_details}")
                confirm_dialog.destroy()
                dialog.destroy()
                messagebox.showerror("Ошибка", f"Не удалось удалить наряд:\n{str(e)}")
        
        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x')
        
        styles.create_button(buttons, "Отмена", confirm_dialog.destroy, 
                           'Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        styles.create_button(buttons, "Удалить", confirm_delete, 
                           'Danger.TButton').pack(side='left', fill='x', expand=True)
