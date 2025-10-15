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
        
        # Autocomplete combobox для номера автомобиля
        self.license_var = tk.StringVar()
        self.license_entry = ttk.Combobox(input_frame, textvariable=self.license_var, width=20, font=styles.FONTS['normal'])
        self.license_entry.pack(side='left', padx=(0, 10))
        
        # Загружаем список номеров
        self.all_license_plates = []
        self.update_license_plates_list()
        
        # Привязываем обработчики событий
        self.license_entry.bind('<KeyRelease>', self.on_license_key_release)
        self.license_entry.bind('<<ComboboxSelected>>', self.on_license_selected)
        
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
            'Съем+Установка', 'Мойка', 
            'Шиномонтаж', 'Балансировка', 'Герметик обода', 
            'Обработка смазкой', 'Правка литого диска',
            'Ремонт грибком', 'Ремонт жгутом'
        ]
        
        column2_services = [
            'Runflat', 'Оптимизация балансировки', 'Замена вентиля', 
            'Установка датчика давления', 
            'Шлифовка бортов диска', 'Шлифовка ступицы', 
            'Косметический ремонт шины', 'Дошиповка (за 1 шип)', 
            'Грязевая покрышка АТ/МТ'
        ]
        
        column3_services = [
            'Зачистка диска от скотча', 'Слесарные работы', 
            'Открутка секретного болта', 'Срыв болта/гайки', 'Прочие услуги',
            'Ремонт бокового пореза', 'Подкачка/проверка давления',
            'Съем+Установка внутреннего колеса'
        ]
        
        column4_services = [
            'Вентиль под датчик', 'Вентиль черный', 'Пакет', 
            'Золотник', 'Колпочки',
            'Проверка на герметичность', 'Проверка на балансировку', 
            'Проверка затяжки болтов'
        ]
        
        row1 = 0
        for service_name in column1_services:
            if service_name in unique_names:
                btn = ttk.Button(column1, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row1, column=0, padx=2, pady=2, sticky='ew')
                row1 += 1
        column1.columnconfigure(0, weight=1)
        
        row2 = 0
        for service_name in column2_services:
            if service_name in unique_names:
                btn = ttk.Button(column2, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row2, column=0, padx=2, pady=2, sticky='ew')
                row2 += 1
        column2.columnconfigure(0, weight=1)
        
        row3 = 0
        for service_name in column3_services:
            if service_name in unique_names:
                btn = ttk.Button(column3, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row3, column=0, padx=2, pady=2, sticky='ew')
                row3 += 1
        column3.columnconfigure(0, weight=1)
        
        row4 = 0
        for service_name in column4_services:
            if service_name in unique_names:
                btn = ttk.Button(column4, text=service_name, 
                               command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                               style='Service.TButton')
                btn.grid(row=row4, column=0, padx=2, pady=2, sticky='ew')
                row4 += 1
        column4.columnconfigure(0, weight=1)
    
    def update_license_plates_list(self):
        """Загрузить список всех номеров машин"""
        self.all_license_plates = self.order_service.get_all_license_plates()
        self.license_entry['values'] = self.all_license_plates
    
    def on_license_key_release(self, event):
        """Фильтровать список номеров при вводе (прогрессивная фильтрация)"""
        # Игнорируем специальные клавиши
        if event.keysym in ('Up', 'Down', 'Left', 'Right', 'Return', 'Tab'):
            return
            
        typed = self.license_var.get().lower()
        
        if typed == '':
            self.license_entry['values'] = self.all_license_plates
        else:
            # Фильтруем список номеров по введенному тексту
            filtered = [plate for plate in self.all_license_plates if plate.lower().startswith(typed)]
            self.license_entry['values'] = filtered
    
    def on_license_selected(self, event):
        """Автозаполнение характеристик при выборе номера из списка"""
        selected_plate = self.license_var.get()
        if not selected_plate:
            return
        
        # Получаем последний наряд для этой машины
        last_order = self.order_service.get_last_order_for_car(selected_plate)
        
        if last_order:
            # Сохраняем данные для автозаполнения при создании нового наряда
            self.prefilled_data = {
                'diameter': last_order.wheel_diameter,
                'vehicle_type': last_order.vehicle_type,
                'client_name': last_order.client.name if last_order.client else None,
                'client_phone': last_order.client.phone if last_order.client else None
            }
        else:
            self.prefilled_data = None
    
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
        
        # Получаем предзаполненные данные если есть
        prefilled = getattr(self, 'prefilled_data', None)
        
        styles.create_label(content, "Диаметр колеса*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        diameter_var = tk.StringVar(value=prefilled['diameter'] if prefilled else '')
        diameter_combo = ttk.Combobox(content, textvariable=diameter_var, 
                                      values=['R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24'],
                                      font=styles.FONTS['normal'], state='readonly')
        diameter_combo.pack(fill='x', pady=(0, 15))
        
        # Автозаполнение типа транспорта
        vehicle_type_map_reverse = {
            'car': 'Легковой',
            'suv': 'Джип/Кроссовер/Пикап',
            'truck': 'Категория С (коммерческий)'
        }
        default_vehicle_type = 'Легковой'
        if prefilled and prefilled.get('vehicle_type'):
            default_vehicle_type = vehicle_type_map_reverse.get(prefilled['vehicle_type'], 'Легковой')
        
        styles.create_label(content, "Тип транспорта*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        vehicle_type_var = tk.StringVar(value=default_vehicle_type)
        vehicle_type_combo = ttk.Combobox(content, textvariable=vehicle_type_var, 
                                          values=['Легковой', 'Джип/Кроссовер/Пикап', 'Категория С (коммерческий)'],
                                          font=styles.FONTS['normal'], state='readonly')
        vehicle_type_combo.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Имя клиента:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        client_name_entry = styles.create_entry(content, width=40)
        if prefilled and prefilled.get('client_name'):
            client_name_entry.insert(0, prefilled['client_name'])
        client_name_entry.pack(fill='x', pady=(0, 15))
        
        styles.create_label(content, "Номер телефона клиента:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        client_phone_entry = styles.create_entry(content, width=40)
        if prefilled and prefilled.get('client_phone'):
            client_phone_entry.insert(0, prefilled['client_phone'])
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
        main_container.pack(fill='both', expand=True, padx=5, pady=3)
        
        # Верхняя строка: машина, скидки, цены
        top_frame = ttk.Frame(main_container)
        top_frame.pack(fill='x', pady=(0, 2))
        
        # Машина и клиент (слева)
        info_frame = ttk.Frame(top_frame)
        info_frame.pack(side='left')
        
        vehicle_type_map = {
            'car': 'Легковой',
            'suv': 'Джип/Кроссовер/Пикап',
            'truck': 'Категория С (коммерческий)'
        }
        vehicle_type_display = vehicle_type_map.get(order.vehicle_type, order.vehicle_type)
        
        ttk.Label(info_frame, text=f"Машина: {order.car.license_plate} | Класс: {vehicle_type_display} | Диаметр: {order.wheel_diameter}", font=('Arial', 10, 'bold')).pack(anchor='w')
        
        if order.client:
            client_info = order.client.name or ""
            if order.client.phone:
                client_info += f" ({order.client.phone})"
            client_text = f"Клиент: {client_info}"
            if order.auto_discount:
                client_text += " (Автоскидка: 5%)"
            ttk.Label(info_frame, text=client_text, font=('Arial', 9), foreground='#059669' if order.auto_discount else 'black').pack(anchor='w')
        
        # Сотрудники (под машиной)
        self.employees_label = ttk.Label(info_frame, text="", font=('Arial', 9), foreground='#64748b')
        self.employees_label.pack(anchor='w')
        
        # Скидки (левее)
        discount_frame = ttk.Frame(top_frame)
        discount_frame.pack(side='left', padx=(15, 0))
        
        ttk.Label(discount_frame, text="Скидки:", font=('Arial', 11, 'bold')).pack(anchor='w')
        
        disc_row = ttk.Frame(discount_frame)
        disc_row.pack()
        
        ttk.Label(disc_row, text="Диски:", font=('Arial', 10)).pack(side='left', padx=(0, 3))
        self.rim_discount_var = tk.StringVar(value='0')
        rim_combo = ttk.Combobox(disc_row, textvariable=self.rim_discount_var, values=['0', '10', '20'], 
                                 width=5, font=('Arial', 10), state='readonly')
        rim_combo.pack(side='left', padx=(0, 3))
        ttk.Button(disc_row, text="OK", command=self.apply_rim_discount, width=3).pack(side='left', padx=(0, 10))
        
        ttk.Label(disc_row, text="Общ:", font=('Arial', 10)).pack(side='left', padx=(0, 3))
        self.general_discount_var = tk.StringVar(value='0')
        general_combo = ttk.Combobox(disc_row, textvariable=self.general_discount_var, values=['0', '10', '15'], 
                                      width=5, font=('Arial', 10), state='readonly')
        general_combo.pack(side='left', padx=(0, 3))
        ttk.Button(disc_row, text="OK", command=self.apply_general_discount, width=3).pack(side='left')
        
        # Цены (справа)
        price_frame = ttk.Frame(top_frame)
        price_frame.pack(side='right')
        
        self.price_label = ttk.Label(price_frame, text="0.00 руб.", font=('Arial', 14, 'bold'), foreground='#2563eb')
        self.price_label.pack(anchor='e')
        
        self.discount_price_label = ttk.Label(price_frame, text="", font=('Arial', 12, 'bold'), foreground='#059669')
        self.discount_price_label.pack(anchor='e')
        
        # Список услуг
        ttk.Label(main_container, text="Услуги:", font=('Arial', 9, 'bold'), style='ServiceHeading.TLabel').pack(fill='x', pady=(2, 1))
        
        tree_frame = ttk.Frame(main_container)
        tree_frame.pack(fill='both', expand=True)
        
        self.items_tree = ttk.Treeview(tree_frame, columns=('Услуга', 'Кол-во', 'Цена', 'Скидка', 'Итого'), show='headings', height=5)
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
        
        self.items_tree.bind('<Double-1>', self.edit_item)
        self.items_tree.bind('<Delete>', self.delete_item)
        
        
        # Загрузка данных
        self.refresh_items()
    
    def add_service_by_name(self, service_name):
        from models import Service
        vehicle_type = self.order.vehicle_type
        
        try:
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
        except Exception as e:
            # При ошибке соединения откатываем транзакцию и пробуем снова
            self.db.rollback()
            try:
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
            except Exception as e2:
                messagebox.showerror("Ошибка", f"Ошибка добавления услуги: {str(e2)}")
    
    def add_service(self, service):
        try:
            self.order_service.add_service_to_order(self.order.id, service.id)
            self.refresh_items()
        except Exception as e:
            # При ошибке соединения откатываем и пробуем снова
            self.db.rollback()
            try:
                self.order_service.add_service_to_order(self.order.id, service.id)
                self.refresh_items()
            except Exception as e2:
                messagebox.showerror("Ошибка", str(e2))
    
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
        dialog_height = "480" if is_editable else "400"
        dialog.geometry(f"450x{dialog_height}")
        dialog.configure(bg=styles.COLORS['bg'])
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(content, f"Услуга: {item.service.name}", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 20))
        
        # Количество
        styles.create_label(content, "Количество:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        quantity_entry = styles.create_entry(content, width=50)
        quantity_entry.insert(0, str(item.quantity))
        quantity_entry.pack(fill='x', pady=(0, 15))
        
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
                quantity = int(quantity_entry.get())
                if quantity < 1:
                    messagebox.showerror("Ошибка", "Количество должно быть больше 0")
                    return
                    
                if is_editable and price_entry:
                    new_price = float(price_entry.get())
                    self.order_service.update_item_full(item_id, quantity, new_price, int(discount_var.get()), comment_entry.get())
                else:
                    self.order_service.update_item_full(item_id, quantity, item.price, int(discount_var.get()), comment_entry.get())
                self.refresh_items()
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Ошибка", "Введите корректные значения")
        
        styles.create_button(content, "Сохранить", save, 'Primary.TButton').pack(fill='x')
    
    def delete_item(self, event):
        selected = self.items_tree.selection()
        if not selected:
            return
        
        item_id = int(self.items_tree.item(selected[0])['tags'][0])
        self.order_service.delete_item(item_id)
        self.refresh_items()
    
    def apply_rim_discount(self):
        discount = int(self.rim_discount_var.get())
        self.order_service.update_rim_discount(self.order.id, discount)
        self.db.refresh(self.order)
        self.refresh_items()
    
    def apply_general_discount(self):
        discount = int(self.general_discount_var.get())
        self.order_service.update_general_discount(self.order.id, discount)
        self.db.refresh(self.order)
        self.refresh_items()
    
    def process_payment(self):
        import os
        import platform
        
        total = self.order_service.calculate_total(self.order.id)
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Оплата")
        dialog.geometry("400x300")
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
        
        def pay_and_print():
            try:
                self.salary_service.process_payment(self.order.id, payment_var.get(), total)
                self.db.refresh(self.order)
                
                items = self.order_service.get_order_items(self.order.id)
                receipt_file = self.print_service.generate_receipt(self.order, items, total)
                
                # Автоматическая печать для Windows
                if platform.system() == 'Windows':
                    os.startfile(receipt_file, "print")
                    messagebox.showinfo("Успех", f"Оплата проведена!\nЧек отправлен на печать")
                else:
                    # Для Linux/Mac используем lp
                    try:
                        import subprocess
                        subprocess.run(['lp', receipt_file], check=True)
                        messagebox.showinfo("Успех", f"Оплата проведена!\nЧек отправлен на печать")
                    except:
                        messagebox.showinfo("Успех", f"Оплата проведена!\nЧек сохранён: {receipt_file}")
                
                dialog.destroy()
                self.close_callback(self.order.id)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        def preview_only():
            try:
                items = self.order_service.get_order_items(self.order.id)
                receipt_file = self.print_service.generate_receipt(self.order, items, total)
                abs_path = os.path.abspath(receipt_file)
                
                # Просто открыть PDF для просмотра
                if platform.system() == 'Windows':
                    os.startfile(receipt_file)
                    messagebox.showinfo("Просмотр", f"Чек открыт для просмотра:\n{receipt_file}")
                elif platform.system() == 'Darwin':
                    # macOS
                    import subprocess
                    subprocess.Popen(['open', receipt_file])
                    messagebox.showinfo("Просмотр", f"Чек открыт для просмотра:\n{receipt_file}")
                else:
                    # Linux (Replit) - используем evince
                    import subprocess
                    try:
                        subprocess.Popen(['evince', abs_path])
                        messagebox.showinfo("Просмотр", f"Чек открыт для просмотра:\n{abs_path}")
                    except Exception as e:
                        messagebox.showwarning("Информация", f"Чек создан и сохранён:\n{abs_path}\n\nОткройте его вручную в файловом менеджере.")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        # Две кнопки: Оплатить (печать) и Просмотр
        button_frame = ttk.Frame(content, style='White.TFrame')
        button_frame.pack(fill='x', pady=(10, 0))
        
        styles.create_button(button_frame, "🖨 Оплатить", pay_and_print, 'Success.TButton').pack(side='left', fill='x', expand=True, padx=(0, 5))
        styles.create_button(button_frame, "👁 Просмотр", preview_only, 'Primary.TButton').pack(side='left', fill='x', expand=True, padx=(5, 0))
    
    def refresh_items(self):
        try:
            for item in self.items_tree.get_children():
                self.items_tree.delete(item)
            
            items = self.order_service.get_order_items(self.order.id)
            self.db.refresh(self.order)
        except Exception as e:
            # При ошибке соединения откатываем и пробуем снова
            self.db.rollback()
            for item in self.items_tree.get_children():
                self.items_tree.delete(item)
            
            items = self.order_service.get_order_items(self.order.id)
            self.db.refresh(self.order)
        
        # Определяем какая скидка применяется (они заменяют друг друга)
        final_discount = 0
        if self.order.general_discount > 0:
            final_discount = self.order.general_discount
        elif self.order.rim_discount > 0:
            final_discount = self.order.rim_discount
        elif self.order.auto_discount:
            final_discount = 5
        
        # Обновляем значения в комбобоксах
        self.rim_discount_var.set(str(self.order.rim_discount))
        self.general_discount_var.set(str(self.order.general_discount))
        
        # Рассчитываем общую цену
        total_without_discount = 0
        for item in items:
            # Цена с учетом скидки на позицию и количества
            item_after_own_discount = item.price * item.quantity * (1 - item.discount_percent / 100)
            total_without_discount += item_after_own_discount
            
            # Итоговая цена позиции с общей скидкой
            item_total = item_after_own_discount * (1 - final_discount / 100)
            
            # Показываем общую скидку в колонке если она есть
            discount_display = f"{item.discount_percent}%" if item.discount_percent > 0 else f"{final_discount}%" if final_discount > 0 else "0%"
            
            self.items_tree.insert('', 'end', values=(
                item.service.name,
                item.quantity,
                f"{item.price:.2f}",
                discount_display,
                f"{item_total:.2f}"
            ), tags=(str(item.id),))
        
        total_with_discount = self.order_service.calculate_total(self.order.id)
        
        # Обновляем лейблы с ценами
        self.price_label.config(text=f"{total_without_discount:.2f} руб.")
        
        if total_with_discount < total_without_discount:
            self.discount_price_label.config(text=f"{total_with_discount:.2f} руб. со скидкой")
        else:
            self.discount_price_label.config(text="")
        
        # Обновляем список сотрудников
        self.update_employees_display()
    
    def update_employees_display(self):
        """Обновляет отображение сотрудников, работающих над нарядом"""
        try:
            from models import SalaryTransaction
            
            # Если наряд оплачен, показываем сотрудников из транзакций
            if self.order.status == 'paid':
                transactions = self.db.query(SalaryTransaction).filter(
                    SalaryTransaction.work_order_id == self.order.id
                ).all()
                
                if transactions:
                    employee_ids = [str(t.employee_id) for t in transactions]
                    employees_text = "№" + ", №".join(employee_ids)
                    self.employees_label.config(text=employees_text, foreground='#64748b')
                else:
                    self.employees_label.config(text="")
            else:
                # Если наряд не оплачен, показываем сохранённых сотрудников из наряда
                if self.order.employee_ids:
                    employee_ids = self.order.employee_ids.split(',')
                    employees_text = "№" + ", №".join(employee_ids)
                    self.employees_label.config(text=employees_text, foreground='#059669')
                else:
                    self.employees_label.config(text="Нет сотрудников", foreground='#dc2626')
        except Exception as e:
            # При ошибке соединения откатываем и пробуем снова
            try:
                self.db.rollback()
                
                from models import SalaryTransaction
                
                if self.order.status == 'paid':
                    transactions = self.db.query(SalaryTransaction).filter(
                        SalaryTransaction.work_order_id == self.order.id
                    ).all()
                    
                    if transactions:
                        employee_ids = [str(t.employee_id) for t in transactions]
                        employees_text = "№" + ", №".join(employee_ids)
                        self.employees_label.config(text=employees_text, foreground='#64748b')
                    else:
                        self.employees_label.config(text="")
                else:
                    if self.order.employee_ids:
                        employee_ids = self.order.employee_ids.split(',')
                        employees_text = "№" + ", №".join(employee_ids)
                        self.employees_label.config(text=employees_text, foreground='#059669')
                    else:
                        self.employees_label.config(text="Нет сотрудников", foreground='#dc2626')
            except Exception as e2:
                print(f"Error updating employees display: {e2}")
                # Если не удалось получить данные, просто не показываем
                self.employees_label.config(text="")
