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
        
        styles.create_button(input_frame, "Создать наряд", self.create_new_order, 'Primary.TButton').pack(side='left')
        
        top_card = styles.create_card_frame(self.frame)
        top_card.pack(fill='x', padx=15, pady=(0, 10))
        
        top_inner = ttk.Frame(top_card, style='White.TFrame')
        top_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        styles.create_label(top_inner, "Панель услуг", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))
        
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
        current_tab = self.order_notebook.select()
        if not current_tab:
            messagebox.showwarning("Предупреждение", "Создайте наряд")
            return
        
        for order_id, widget in self.active_orders.items():
            if str(widget.frame) == current_tab:
                widget.add_service_by_name(service_name)
                break
    
    def add_service_to_current_order(self, service):
        current_tab = self.order_notebook.select()
        if not current_tab:
            messagebox.showwarning("Предупреждение", "Создайте наряд")
            return
        
        for order_id, widget in self.active_orders.items():
            if str(widget.frame) == current_tab:
                widget.add_service(service)
                break
    
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
        
        main_frame = ttk.Frame(frame, style='BG.TFrame')
        main_frame.pack(fill='both', expand=True, padx=15, pady=15)
        
        info_card = styles.create_card_frame(main_frame)
        info_card.pack(fill='x', pady=(0, 15))
        
        info_inner = ttk.Frame(info_card, style='White.TFrame')
        info_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        styles.create_label(info_inner, f"Номер машины: {order.car.license_plate}", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))
        styles.create_label(info_inner, f"Диаметр: {order.wheel_diameter}", 'Card.TLabel').pack(anchor='w', pady=2)
        
        if order.client:
            client_info = order.client.name or ""
            if order.client.phone:
                client_info += f" ({order.client.phone})"
            styles.create_label(info_inner, f"Клиент: {client_info}", 'Card.TLabel').pack(anchor='w', pady=2)
        
        auto_discount_text = "Автоскидка 5%: ✓" if order.auto_discount else "Автоскидка 5%: ✗"
        auto_discount_color = styles.COLORS['success'] if order.auto_discount else styles.COLORS['text_secondary']
        label = styles.create_label(info_inner, auto_discount_text, 'Card.TLabel')
        label.pack(anchor='w', pady=2)
        label.configure(foreground=auto_discount_color)
        
        from models import WorkShift, Employee
        active_shifts = db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()
        if active_shifts:
            employee_names = []
            for shift in active_shifts:
                employee = db.query(Employee).filter(Employee.id == shift.employee_id).first()
                if employee:
                    employee_names.append(f"#{employee.id} ({employee.salary_percent}%)")
            
            if employee_names:
                emp_label = styles.create_label(info_inner, f"Сотрудники на смене: {', '.join(employee_names)}", 'Card.TLabel')
                emp_label.pack(anchor='w', pady=(8, 2))
                emp_label.configure(foreground=styles.COLORS['primary'], font=('Segoe UI', 10, 'bold'))
        
        items_card = styles.create_card_frame(main_frame)
        items_card.pack(fill='both', expand=True, pady=(0, 15))
        
        items_inner = ttk.Frame(items_card, style='White.TFrame')
        items_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        styles.create_label(items_inner, "Список услуг", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))
        
        tree_frame = ttk.Frame(items_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        self.items_tree = ttk.Treeview(tree_frame, columns=('Услуга', 'Цена', 'Скидка', 'Итого'), show='headings', height=10)
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
        
        discount_frame = ttk.Frame(items_inner, style='White.TFrame')
        discount_frame.pack(fill='x')
        
        styles.create_label(discount_frame, "Общая скидка:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.general_discount_var = tk.StringVar(value='0')
        discount_combo = ttk.Combobox(discount_frame, textvariable=self.general_discount_var, 
                                      values=['0', '5', '10', '15'], width=10,
                                      font=styles.FONTS['normal'])
        discount_combo.pack(side='left', padx=(0, 10))
        styles.create_button(discount_frame, "Применить", self.apply_general_discount, 'Secondary.TButton').pack(side='left')
        
        total_card = styles.create_card_frame(main_frame)
        total_card.pack(fill='x', pady=(0, 15))
        
        total_inner = ttk.Frame(total_card, style='White.TFrame')
        total_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        self.total_label = styles.create_label(total_inner, "ИТОГО: 0.00 руб.", 'CardHeading.TLabel')
        self.total_label.pack(anchor='center')
        self.total_label.configure(font=('Segoe UI', 18, 'bold'), foreground=styles.COLORS['primary'])
        
        button_frame = ttk.Frame(main_frame, style='BG.TFrame')
        button_frame.pack(fill='x')
        
        pay_btn = styles.create_button(button_frame, "💳 Пробить наряд (наличные/карта)", self.process_payment, 'Success.TButton')
        pay_btn.pack(side='left', padx=(0, 10))
        pay_btn.configure(padding=[20, 12])
        styles.create_button(button_frame, "Закрыть вкладку", lambda: self.close_callback(order.id), 'Secondary.TButton').pack(side='left')
        
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
        for item in self.items_tree.get_children():
            self.items_tree.delete(item)
        
        items = self.order_service.get_order_items(self.order.id)
        for item in items:
            item_total = item.price * (1 - item.discount_percent / 100)
            self.items_tree.insert('', 'end', values=(
                item.service.name,
                f"{item.price:.2f}",
                item.discount_percent,
                f"{item_total:.2f}"
            ), tags=(str(item.id),))
        
        total = self.order_service.calculate_total(self.order.id)
        self.total_label.config(text=f"ИТОГО: {total:.2f} руб.")
