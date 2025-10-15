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
        styles.create_button(search_frame, "Найти", self.search_history, 'Primary.TButton').pack(side='left')
        
        history_card = styles.create_card_frame(self.frame)
        history_card.pack(fill='both', expand=True, padx=15, pady=(0, 15))
        
        history_inner = ttk.Frame(history_card, style='White.TFrame')
        history_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(history_inner, "История нарядов", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))
        
        tree_frame = ttk.Frame(history_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        self.history_tree = ttk.Treeview(tree_frame, columns=('Дата', 'Наряд №', 'Услуги', 'Сумма', 'Оплата'), show='headings')
        self.history_tree.heading('Дата', text='Дата')
        self.history_tree.heading('Наряд №', text='Наряд №')
        self.history_tree.heading('Услуги', text='Услуги')
        self.history_tree.heading('Сумма', text='Сумма')
        self.history_tree.heading('Оплата', text='Способ оплаты')
        self.history_tree.column('Дата', width=150)
        self.history_tree.column('Наряд №', width=100)
        self.history_tree.column('Услуги', width=400)
        self.history_tree.column('Сумма', width=100)
        self.history_tree.column('Оплата', width=150)
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
    
    def search_history(self):
        license = self.license_entry.get().strip()
        if not license:
            messagebox.showwarning("Предупреждение", "Введите номер автомобиля")
            return
        
        car = self.db.query(Car).filter(Car.license_plate == license).first()
        if not car:
            messagebox.showinfo("Информация", "Автомобиль не найден")
            return
        
        self.current_license = license
        self.current_page = 1
        self.load_page()
    
    def load_page(self):
        if not self.current_license:
            return
        
        car = self.db.query(Car).filter(Car.license_plate == self.current_license).first()
        if not car:
            return
        
        # Получаем общее количество нарядов
        self.total_orders = self.db.query(WorkOrder).filter(
            WorkOrder.car_id == car.id,
            WorkOrder.status == 'paid'
        ).count()
        
        # Вычисляем количество страниц
        total_pages = (self.total_orders + self.items_per_page - 1) // self.items_per_page
        
        # Получаем наряды для текущей страницы
        offset = (self.current_page - 1) * self.items_per_page
        orders = self.db.query(WorkOrder).options(joinedload(WorkOrder.items)).filter(
            WorkOrder.car_id == car.id,
            WorkOrder.status == 'paid'
        ).order_by(WorkOrder.paid_at.desc()).offset(offset).limit(self.items_per_page).all()
        
        # Очищаем таблицу
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        
        # Заполняем таблицу
        for order in orders:
            items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order.id).all()
            services_list = ', '.join([item.service.name for item in items])
            
            payment_method = 'Наличные' if order.payment_method == 'cash' else 'Безнал'
            
            self.history_tree.insert('', 'end', values=(
                order.paid_at.strftime('%d.%m.%Y %H:%M'),
                order.id,
                services_list[:50] + '...' if len(services_list) > 50 else services_list,
                f"{order.total_amount:.2f}",
                payment_method
            ), tags=(str(order.id),))
        
        # Обновляем информацию о пагинации
        self.info_label.config(text=f"Найдено нарядов: {self.total_orders}")
        self.page_label.config(text=f"Страница {self.current_page} из {total_pages if total_pages > 0 else 1}")
        
        # Управляем кнопками
        self.prev_button.config(state='normal' if self.current_page > 1 else 'disabled')
        self.next_button.config(state='normal' if self.current_page < total_pages else 'disabled')
    
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
        
        order_id = int(self.history_tree.item(selected[0])['tags'][0])
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        
        if not order:
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title(f"Детали наряда #{order_id}")
        dialog.geometry("600x550")
        dialog.configure(bg=styles.COLORS['bg'])
        
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
        
        items_tree = ttk.Treeview(tree_frame, columns=('Услуга', 'Цена', 'Скидка', 'Итого', 'Комментарий'), show='headings')
        items_tree.heading('Услуга', text='Услуга')
        items_tree.heading('Цена', text='Цена')
        items_tree.heading('Скидка', text='Скидка %')
        items_tree.heading('Итого', text='Итого')
        items_tree.heading('Комментарий', text='Комментарий')
        items_tree.pack(side='left', fill='both', expand=True)
        
        items_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=items_tree.yview)
        items_scroll.pack(side='right', fill='y')
        items_tree.config(yscrollcommand=items_scroll.set)
        
        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        for item in items:
            item_total = item.price * (1 - item.discount_percent / 100)
            items_tree.insert('', 'end', values=(
                item.service.name,
                f"{item.price:.2f}",
                item.discount_percent,
                f"{item_total:.2f}",
                item.comment or ""
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
        total_label.configure(font=('Segoe UI', 16, 'bold'), foreground=styles.COLORS['primary'])
        
        styles.create_button(content, "Закрыть", dialog.destroy, 'Secondary.TButton').pack(fill='x', pady=(10, 0))
