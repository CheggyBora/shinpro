import tkinter as tk
from tkinter import ttk, messagebox
from models import Car, WorkOrder, WorkOrderItem
from sqlalchemy.orm import joinedload
import styles

class HistoryTab:
    def __init__(self, parent, db):
        self.db = db
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.current_page = 1
        self.items_per_page = 30
        self.total_orders = 0
        self.current_license = None
        
        search_card = styles.create_card_frame(self.frame)
        search_card.pack(fill='x', padx=15, pady=(15, 10))
        
        search_inner = ttk.Frame(search_card, style='White.TFrame')
        search_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(search_inner, "Поиск по номеру автомобиля", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        search_frame = ttk.Frame(search_inner, style='White.TFrame')
        search_frame.pack(fill='x')
        
        styles.create_label(search_frame, "Номер автомобиля:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.license_entry = styles.create_entry(search_frame, width=20)
        self.license_entry.pack(side='left', padx=(0, 10))
        styles.create_button(search_frame, "Найти", self.search_history, 'Primary.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(search_frame, "Показать все", self.show_all_history, 'Secondary.TButton').pack(side='left')
        
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
        self.delete_button = styles.create_button(pagination_frame, "🗑️ Удалить выбранный наряд", 
                                                  self.delete_selected_order, 'Danger.TButton')
        self.delete_button.pack(side='right', padx=(10, 0))
        
        # Загружаем все наряды при открытии вкладки
        self.load_page()
    
    def search_history(self):
        license = self.license_entry.get().strip()
        if not license:
            messagebox.showwarning("Предупреждение", "Введите номер автомобиля")
            return
        
        try:
            car = self.db.query(Car).filter(Car.license_plate == license).first()
            if not car:
                messagebox.showinfo("Информация", "Автомобиль не найден")
                return
            
            self.current_license = license
            self.current_page = 1
            self.load_page()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось выполнить поиск:\n{str(e)}")
    
    def show_all_history(self):
        self.current_license = None
        self.license_entry.delete(0, 'end')
        self.current_page = 1
        self.load_page()
    
    def load_page(self):
        try:
            # Формируем запрос в зависимости от наличия фильтра
            query = self.db.query(WorkOrder).options(joinedload(WorkOrder.items))
            
            if self.current_license:
                # Фильтр по номеру автомобиля
                car = self.db.query(Car).filter(Car.license_plate == self.current_license).first()
                if not car:
                    return
                query = query.filter(WorkOrder.car_id == car.id)
            
            # Получаем общее количество нарядов (включая удалённые)
            self.total_orders = query.filter(WorkOrder.status == 'paid').count()
            
            # Вычисляем количество страниц
            total_pages = (self.total_orders + self.items_per_page - 1) // self.items_per_page
            
            # Получаем наряды для текущей страницы (включая удалённые)
            offset = (self.current_page - 1) * self.items_per_page
            orders = query.filter(WorkOrder.status == 'paid').order_by(WorkOrder.paid_at.desc()).offset(offset).limit(self.items_per_page).all()
            
            # Очищаем таблицу
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            
            # Настраиваем тег для удалённых нарядов
            self.history_tree.tag_configure('deleted', foreground='#dc3545')
            
            # Заполняем таблицу
            for order in orders:
                items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order.id).all()
                total_services = sum(item.quantity for item in items)
                services_text = f"{total_services} {'услуга' if total_services == 1 else 'услуг' if total_services > 4 or total_services == 0 else 'услуги'}"
                
                payment_method = 'Наличные' if order.payment_method == 'cash' else 'Безнал'
                
                # Определяем статус (красный крестик для удалённых)
                status_icon = '❌' if order.is_deleted else ''
                
                # Определяем теги
                tags = (str(order.id), 'deleted') if order.is_deleted else (str(order.id),)
                
                self.history_tree.insert('', 'end', values=(
                    status_icon,
                    order.paid_at.strftime('%d.%m.%Y %H:%M'),
                    order.id,
                    order.car.license_plate,
                    services_text,
                    f"{order.total_amount:.2f} ₽",
                    payment_method
                ), tags=tags)
            
            # Обновляем информацию о пагинации
            info_text = f"Найдено нарядов: {self.total_orders}" if self.current_license else f"Всего нарядов: {self.total_orders}"
            self.info_label.config(text=info_text)
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
            print(f"ERROR in show_order_details: {error_details}")
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось загрузить детали наряда:\n{str(e)}")
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title(f"Детали наряда #{order_id}")
        dialog.geometry("750x650")
        dialog.configure(bg=styles.COLORS['bg'])
        
        # Центрируем окно
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f'{width}x{height}+{x}+{y}')
        
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
        
        styles.create_button(buttons_frame, "🗑️ Удалить наряд", 
                           lambda: self.delete_order(order_id, dialog), 
                           'Danger.TButton').pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        styles.create_button(buttons_frame, "Закрыть", dialog.destroy, 'Secondary.TButton').pack(side='left', fill='x', expand=True)
    
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
        confirm_dialog.grab_set()
        
        content = ttk.Frame(confirm_dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        warning = styles.create_label(content, f"⚠️ Удалить наряд №{order_id}?", 'CardHeading.TLabel')
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
                print(f"ERROR in confirm_delete (delete_selected_order): {error_details}")
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
        confirm_dialog.transient(dialog)
        confirm_dialog.grab_set()
        
        content = ttk.Frame(confirm_dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        warning = styles.create_label(content, f"⚠️ Удалить наряд №{order_id}?", 'CardHeading.TLabel')
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
                print(f"ERROR in confirm_delete (delete_order): {error_details}")
                confirm_dialog.destroy()
                dialog.destroy()
                messagebox.showerror("Ошибка", f"Не удалось удалить наряд:\n{str(e)}")
        
        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x')
        
        styles.create_button(buttons, "Отмена", confirm_dialog.destroy, 
                           'Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        styles.create_button(buttons, "Удалить", confirm_delete, 
                           'Danger.TButton').pack(side='left', fill='x', expand=True)
