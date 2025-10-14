import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from services import OrderService, SalaryService, PrintService
from datetime import datetime
import styles

class OrdersTab:
    def __init__(self, parent, db):
        self.db = db
        self.order_service = OrderService(db)
        self.salary_service = SalaryService(db)
        self.print_service = PrintService()
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.active_orders = {}
        
        input_frame = ttk.Frame(self.frame, style='BG.TFrame')
        input_frame.pack(fill='x', padx=15, pady=(15, 10))
        
        styles.create_label(input_frame, "Номер автомобиля:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        
        self.license_entry = styles.create_entry(input_frame, width=20)
        self.license_entry.pack(side='left', padx=(0, 10))
        
        styles.create_button(input_frame, "Создать наряд", self.create_new_order, 'Primary.TButton').pack(side='left', padx=(0, 10))
        
        styles.create_button(input_frame, "💳 Пробить", self.process_payment_for_current_order, 'Success.TButton').pack(side='left')
        
        top_card = styles.create_card_frame(self.frame)
        top_card.pack(fill='x', padx=15, pady=(0, 10))
        
        top_inner = ttk.Frame(top_card, style='White.TFrame')
        top_inner.pack(fill='both', expand=True, padx=15, pady=10)
        
        self.services_frame = ttk.Frame(top_inner, style='White.TFrame')
        self.services_frame.pack(fill='x')
        
        self.load_service_buttons()
        
        tabs_frame = ttk.Frame(self.frame, style='BG.TFrame')
        tabs_frame.pack(fill='x', padx=15, pady=(0, 10))
        
        self.order_notebook = ttk.Notebook(tabs_frame)
        self.order_notebook.pack(fill='both', expand=True)
        
        self.content_frame = ttk.Frame(self.frame, style='BG.TFrame')
        self.content_frame.pack(fill='both', expand=True, padx=15, pady=(0, 15))
        
        self.order_notebook.bind('<<NotebookTabChanged>>', self.on_tab_change)
    
    def load_service_buttons(self):
        services = self.order_service.get_all_services()
        unique_names = list(dict.fromkeys([s.name for s in services]))
        
        column1 = ttk.Frame(self.services_frame, style='White.TFrame')
        column1.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        column2 = ttk.Frame(self.services_frame, style='White.TFrame')
        column2.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        column3 = ttk.Frame(self.services_frame, style='White.TFrame')
        column3.pack(side='left', fill='both', expand=True, padx=(0, 5))
        
        column4 = ttk.Frame(self.services_frame, style='White.TFrame')
        column4.pack(side='left', fill='both', expand=True)
        
        column1_services = [
            'Подкачка/проверка давления', 'Съем+Установка', 'Мойка', 
            'Шиномонтаж', 'Балансировка', 'Герметик обода', 
            'Обработка смазкой', 'Правка литого диска', 
            'Съем+Установка внутреннего колеса'
        ]
        
        column2_services = [
            'Runflat', 'Оптимизация балансировки', 'Замена вентиля', 
            'Установка датчика давления', 'Ремонт жгутом', 
            'Шлифовка бортов диска', 'Шлифовка ступицы', 
            'Косметический ремонт шины', 'Дошиповка (за 1 шип)', 
            'Грязевая покрышка АТ/МТ'
        ]
        
        column3_services = [
            'Зачистка диска от скотча', 'Слесарные работы', 
            'Открутка секретного болта', 'Срыв болта/гайки', 'Прочие услуги',
            'Ремонт грибком', 'Ремонт бокового пореза'
        ]
        
        column4_services = [
            'Вентиль под датчик', 'Вентиль черный', 'Пакет', 
            'Золотник', 'Колпочки',
            'Проверка на герметичность', 'Проверка на балансировку', 
            'Проверка затяжки болтов'
        ]
        
        row1 = 0
        for service_name in unique_names:
            if service_name in column1_services:
                btn = ttk.Button(column1, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row1, column=0, padx=2, pady=2, sticky='ew')
                row1 += 1
        column1.columnconfigure(0, weight=1)
        
        row2 = 0
        for service_name in unique_names:
            if service_name in column2_services:
                btn = ttk.Button(column2, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row2, column=0, padx=2, pady=2, sticky='ew')
                row2 += 1
        column2.columnconfigure(0, weight=1)
        
        row3 = 0
        for service_name in unique_names:
            if service_name in column3_services:
                btn = ttk.Button(column3, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row3, column=0, padx=2, pady=2, sticky='ew')
                row3 += 1
        column3.columnconfigure(0, weight=1)
        
        row4 = 0
        for service_name in unique_names:
            if service_name in column4_services:
                btn = ttk.Button(column4, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row4, column=0, padx=2, pady=2, sticky='ew')
                row4 += 1
        column4.columnconfigure(0, weight=1)
    
    def create_new_order(self):
        license = self.license_entry.get().strip()
        if not license:
            messagebox.showerror("Ошибка", "Введите номер автомобиля")
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Детали наряда")
        dialog.geometry("450x450")
        dialog.configure(bg=styles.COLORS['bg'])
        
        dialog.update_idletasks()
        width = 450
        height = 450
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry(f'{width}x{height}+{x}+{y}')
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(content, f"Создание наряда для {license}", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 20))
        
        styles.create_label(content, "Диаметр колеса*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        diameter_var = tk.StringVar()
        diameter_combo = ttk.Combobox(content, textvariable=diameter_var, 
                                      values=['R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24'],
                                      font=styles.FONTS['normal'])
        diameter_combo.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Тип транспорта*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        vehicle_type_var = tk.StringVar(value='Легковой')
        vehicle_type_combo = ttk.Combobox(content, textvariable=vehicle_type_var, 
                                          values=['Легковой', 'Джип/Кроссовер/Пикап', 'Категория С (коммерческий)'],
                                          font=styles.FONTS['normal'], state='readonly')
        vehicle_type_combo.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Имя клиента:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        client_name_entry = styles.create_entry(content, width=40)
        client_name_entry.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Номер телефона клиента:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        client_phone_entry = styles.create_entry(content, width=40)
        client_phone_entry.pack(fill='x', pady=(0, 20))
        
        def create():
            diameter = diameter_var.get()
            vehicle_type_display = vehicle_type_combo.get()
            client_name = client_name_entry.get().strip() or None
            client_phone = client_phone_entry.get().strip() or None
            
            vehicle_type_map = {
                'Легковой': 'car',
                'Джип/Кроссовер/Пикап': 'suv',
                'Категория С (коммерческий)': 'truck'
            }
            vehicle_type = vehicle_type_map.get(vehicle_type_display, 'car')
            
            if not diameter:
                messagebox.showerror("Ошибка", "Заполните диаметр колеса")
                return
            
            try:
                order = self.order_service.create_order(license, diameter, vehicle_type, None, client_name, client_phone)
                self.open_order_tab(order)
                self.license_entry.delete(0, tk.END)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        styles.create_button(content, "Создать наряд", create, 'Primary.TButton').pack(fill='x')
    
    def open_order_tab(self, order):
        tab_frame = ttk.Frame(self.order_notebook)
        tab_title = f"  #{order.id}: {order.car.license_plate}  "
        self.order_notebook.add(tab_frame, text=tab_title)
        
        order_widget = OrderWidget(tab_frame, order, self.db, self.order_service, 
                                   self.salary_service, self.print_service, self.close_order_tab)
        self.active_orders[order.id] = order_widget
        
        self.order_notebook.select(tab_frame)
    
    def close_order_tab(self, order_id):
        if order_id in self.active_orders:
            widget = self.active_orders[order_id]
            self.order_notebook.forget(widget.frame)
            del self.active_orders[order_id]
    
    def add_service_to_current_order_by_name(self, service_name):
        print(f"!!! BUTTON CLICKED: {service_name}")
        try:
            print(f"Active orders: {list(self.active_orders.keys())}")
            print(f"Notebook tabs: {len(self.order_notebook.tabs())}")
            
            if len(self.order_notebook.tabs()) == 0:
                print("No tabs open!")
                messagebox.showwarning("Предупреждение", "Создайте наряд")
                return
            
            current_index = self.order_notebook.index(self.order_notebook.select())
            tabs = self.order_notebook.tabs()
            
            print(f"Current tab index: {current_index}")
            print(f"Total tabs: {len(tabs)}")
            
            if current_index < 0 or current_index >= len(tabs):
                messagebox.showwarning("Предупреждение", "Создайте наряд")
                return
            
            current_tab_widget = self.order_notebook.nametowidget(tabs[current_index])
            print(f"Current tab widget: {current_tab_widget}")
            
            for order_id, widget in self.active_orders.items():
                print(f"Checking order_id={order_id}, widget.frame={widget.frame}")
                if widget.frame == current_tab_widget:
                    print(f"MATCH! Calling add_service_by_name for order {order_id}")
                    widget.add_service_by_name(service_name)
                    return
            
            print("No matching widget found!")
            messagebox.showwarning("Ошибка", "Не удалось найти активный наряд")
        except Exception as e:
            print(f"!!! ERROR in add_service_to_current_order_by_name: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("Ошибка", str(e))
    
    def add_service_to_current_order(self, service):
        current_tab = self.order_notebook.select()
        if not current_tab:
            messagebox.showwarning("Предупреждение", "Создайте наряд")
            return
        
        for order_id, widget in self.active_orders.items():
            if str(widget.frame) == current_tab:
                widget.add_service(service)
                break
    
    def process_payment_for_current_order(self):
        """Обработать оплату для текущего активного наряда"""
        try:
            current_index = self.order_notebook.index(self.order_notebook.select())
            tabs = self.order_notebook.tabs()
            
            if current_index < 0 or current_index >= len(tabs):
                messagebox.showwarning("Предупреждение", "Создайте наряд")
                return
            
            current_tab_widget = self.order_notebook.nametowidget(tabs[current_index])
            
            for order_id, widget in self.active_orders.items():
                if widget.frame == current_tab_widget:
                    widget.process_payment()
                    return
            
            messagebox.showwarning("Ошибка", "Не удалось найти активный наряд")
        except Exception as e:
            print(f"ERROR in process_payment_for_current_order: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("Ошибка", str(e))
    
    def on_tab_change(self, event):
        pass

class OrderWidget:
    def __init__(self, frame, order, db, order_service, salary_service, print_service, close_callback):
        self.frame = frame
        self.order = order
        self.db = db
        self.order_service = order_service
        self.salary_service = salary_service
        self.print_service = print_service
        self.close_callback = close_callback
        
        # КОМПАКТНЫЙ ИНТЕРФЕЙС
        main_container = ttk.Frame(frame)
        main_container.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Заголовок: информация слева, цены справа
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill='x', pady=(0, 5))
        
        # Информация о наряде (слева)
        info_frame = ttk.Frame(header_frame)
        info_frame.pack(side='left', fill='both', expand=True)
        
        ttk.Label(info_frame, text=f"Машина: {order.car.license_plate} | Диаметр: {order.wheel_diameter}", font=('Arial', 11, 'bold')).pack(anchor='w', pady=2)
        
        if order.client:
            client_info = order.client.name or ""
            if order.client.phone:
                client_info += f" ({order.client.phone})"
            ttk.Label(info_frame, text=f"Клиент: {client_info}", font=('Arial', 10)).pack(anchor='w', pady=2)
        
        # Цены (справа)
        price_frame = ttk.Frame(header_frame)
        price_frame.pack(side='right', padx=(10, 0))
        
        self.price_label = ttk.Label(price_frame, text="0.00 руб.", font=('Arial', 16, 'bold'), foreground='#2563eb')
        self.price_label.pack(anchor='e', pady=1)
        
        self.discount_price_label = ttk.Label(price_frame, text="", font=('Arial', 14, 'bold'), foreground='#059669')
        self.discount_price_label.pack(anchor='e', pady=1)
        
        # Список услуг
        ttk.Label(main_container, text="Услуги:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(5, 3))
        
        tree_frame = ttk.Frame(main_container)
        tree_frame.pack(fill='both', expand=True, pady=3)
        
        self.items_tree = ttk.Treeview(tree_frame, columns=('Услуга', 'Цена', 'Скидка', 'Итого'), show='headings', height=5)
        self.items_tree.heading('Услуга', text='Услуга')
        self.items_tree.heading('Цена', text='Цена')
        self.items_tree.heading('Скидка', text='Скидка %')
        self.items_tree.heading('Итого', text='Итого')
        self.items_tree.pack(side='left', fill='both', expand=True)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.items_tree.yview)
        tree_scroll.pack(side='right', fill='y')
        self.items_tree.config(yscrollcommand=tree_scroll.set)
        
        self.items_tree.bind('<Double-1>', self.edit_item)
        self.items_tree.bind('<Delete>', self.delete_item)
        
        # Скидка (компактно)
        discount_frame = ttk.Frame(main_container)
        discount_frame.pack(fill='x', pady=3)
        ttk.Label(discount_frame, text="Скидка:", font=('Arial', 9)).pack(side='left', padx=3)
        self.general_discount_var = tk.StringVar(value='0')
        discount_combo = ttk.Combobox(discount_frame, textvariable=self.general_discount_var, values=['0', '5', '10', '15'], width=8)
        discount_combo.pack(side='left', padx=3)
        ttk.Button(discount_frame, text="OK", command=self.apply_general_discount).pack(side='left', padx=3)
        
        # КНОПКИ (компактно)
        button_frame = ttk.Frame(main_container)
        button_frame.pack(fill='x', pady=3)
        
        ttk.Button(button_frame, text="💳 Пробить", command=self.process_payment).pack(side='left', padx=3)
        ttk.Button(button_frame, text="Закрыть", command=lambda: self.close_callback(order.id)).pack(side='left', padx=3)
        
        # Загрузка данных
        self.refresh_items()
    
    def add_service_by_name(self, service_name):
        from models import Service
        vehicle_type = self.order.vehicle_type
        
        service = self.db.query(Service).filter(
            Service.name == service_name,
            Service.vehicle_type == vehicle_type
        ).first()
        
        if not service:
            service = self.db.query(Service).filter(
                Service.name == service_name,
                Service.vehicle_type == 'all'
            ).first()
        
        if service:
            self.add_service(service)
        else:
            messagebox.showerror("Ошибка", f"Услуга '{service_name}' не найдена")
    
    def add_service(self, service):
        try:
            self.order_service.add_service_to_order(self.order.id, service.id)
            self.refresh_items()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
    
    def edit_item(self, event):
        selected = self.items_tree.selection()
        if not selected:
            return
        
        item_id = int(self.items_tree.item(selected[0])['tags'][0])
        item = next((i for i in self.order_service.get_order_items(self.order.id) if i.id == item_id), None)
        
        if not item:
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Редактировать услугу")
        
        is_editable = item.service.editable_price
        dialog_height = "400" if is_editable else "320"
        dialog.geometry(f"450x{dialog_height}")
        dialog.configure(bg=styles.COLORS['bg'])
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(content, f"Услуга: {item.service.name}", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 20))
        
        price_entry = None
        if is_editable:
            styles.create_label(content, "Цена (редактируемая):", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
            price_entry = styles.create_entry(content, width=50)
            price_entry.insert(0, str(item.price))
            price_entry.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Комментарий:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        comment_entry = styles.create_entry(content, width=50)
        comment_entry.insert(0, item.comment or "")
        comment_entry.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Скидка (для правки дисков):", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        discount_var = tk.StringVar(value=str(item.discount_percent))
        discount_combo = ttk.Combobox(content, textvariable=discount_var, values=['0', '10', '20'],
                                      font=styles.FONTS['normal'])
        discount_combo.pack(fill='x', pady=(0, 20))
        
        def save():
            try:
                if is_editable and price_entry:
                    new_price = float(price_entry.get())
                    self.order_service.update_item_price(item_id, new_price, int(discount_var.get()), comment_entry.get())
                else:
                    self.order_service.update_item_discount(item_id, int(discount_var.get()), comment_entry.get())
                self.refresh_items()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Ошибка", "Введите корректную цену")
        
        styles.create_button(content, "Сохранить", save, 'Primary.TButton').pack(fill='x')
    
    def delete_item(self, event):
        selected = self.items_tree.selection()
        if not selected:
            return
        
        if messagebox.askyesno("Подтверждение", "Удалить услугу?"):
            item_id = int(self.items_tree.item(selected[0])['tags'][0])
            self.order_service.delete_item(item_id)
            self.refresh_items()
    
    def apply_general_discount(self):
        discount = int(self.general_discount_var.get())
        self.order_service.update_general_discount(self.order.id, discount)
        self.db.refresh(self.order)
        self.refresh_items()
    
    def process_payment(self):
        total = self.order_service.calculate_total(self.order.id)
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Оплата")
        dialog.geometry("400x250")
        dialog.configure(bg=styles.COLORS['bg'])
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        total_label = styles.create_label(content, f"Сумма к оплате: {total:.2f} руб.", 'CardHeading.TLabel')
        total_label.pack(pady=(0, 20))
        total_label.configure(font=('Segoe UI', 16, 'bold'), foreground=styles.COLORS['primary'])
        
        payment_var = tk.StringVar(value='cash')
        
        radio_frame = ttk.Frame(content, style='White.TFrame')
        radio_frame.pack(fill='x', pady=(0, 20))
        
        ttk.Radiobutton(radio_frame, text="Наличные", variable=payment_var, value='cash').pack(anchor='w', pady=5)
        ttk.Radiobutton(radio_frame, text="Безналичный расчёт", variable=payment_var, value='card').pack(anchor='w', pady=5)
        
        def pay():
            try:
                self.salary_service.process_payment(self.order.id, payment_var.get(), total)
                self.db.refresh(self.order)
                
                items = self.order_service.get_order_items(self.order.id)
                receipt_file = self.print_service.generate_receipt(self.order, items, total)
                
                messagebox.showinfo("Успех", f"Оплата проведена!\nЧек сохранён: {receipt_file}")
                dialog.destroy()
                self.close_callback(self.order.id)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        styles.create_button(content, "Оплатить", pay, 'Success.TButton').pack(fill='x')
    
    def refresh_items(self):
        try:
            for item in self.items_tree.get_children():
                self.items_tree.delete(item)
            
            items = self.order_service.get_order_items(self.order.id)
            
            # Рассчитываем общую цену и цену со скидкой
            total_without_discount = 0
            for item in items:
                total_without_discount += item.price
                item_total = item.price * (1 - item.discount_percent / 100)
                self.items_tree.insert('', 'end', values=(
                    item.service.name,
                    f"{item.price:.2f}",
                    item.discount_percent,
                    f"{item_total:.2f}"
                ), tags=(str(item.id),))
            
            total_with_discount = self.order_service.calculate_total(self.order.id)
            
            # Обновляем лейблы с ценами
            self.price_label.config(text=f"{total_without_discount:.2f} руб.")
            
            if total_with_discount < total_without_discount:
                self.discount_price_label.config(text=f"{total_with_discount:.2f} руб. со скидкой")
            else:
                self.discount_price_label.config(text="")
                
        except Exception as e:
            self.price_label.config(text="0.00 руб.")
            self.discount_price_label.config(text="")
