import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from services import OrderService, SalaryService, PrintService, ClientService
from services.shift_service import ShiftService
from models import Client
from utils import normalize_plate, normalize_phone, format_phone, retry_after_rollback
from datetime import datetime
import styles
from logger import log

# Экран одного наряда живёт в ui/order_screen: он разросся до
# полутора тысяч строк вместе с этим файлом
from ui.order_screen import OrderWidget

class OrdersTab:
    def __init__(self, parent, db, employees_tab=None):
        self.db = db
        self.order_service = OrderService(db)
        self.salary_service = SalaryService(db)
        self.print_service = PrintService()
        self.shift_service = ShiftService(db)
        self.client_service = ClientService(db)
        self.employees_tab = employees_tab
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.active_orders = {}
        
        input_frame = ttk.Frame(self.frame, style='BG.TFrame')
        input_frame.pack(fill='x', padx=15, pady=(15, 10))
        
        styles.create_label(input_frame, "Номер автомобиля:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        
        # Контейнер для Entry + Listbox (кастомный автокомплит)
        self.autocomplete_container = ttk.Frame(input_frame, style='BG.TFrame')
        self.autocomplete_container.pack(side='left', padx=(0, 10))
        
        # Entry для ввода номера
        self.license_var = tk.StringVar()
        self.license_entry = ttk.Entry(self.autocomplete_container, textvariable=self.license_var, width=22, font=styles.FONTS['normal'])
        self.license_entry.pack()
        
        # Listbox для отображения подсказок (скрыт по умолчанию)
        self.listbox_frame = tk.Frame(self.autocomplete_container, bg='white', relief='solid', borderwidth=1)
        self.autocomplete_listbox = tk.Listbox(self.listbox_frame, height=6, font=styles.FONTS['normal'], exportselection=False)
        self.autocomplete_listbox.pack(fill='both', expand=True)
        
        # Загружаем список номеров
        self.all_license_plates = []
        self.update_license_plates_list()
        
        # Привязываем обработчики событий
        self.license_entry.bind('<KeyRelease>', self.on_license_key_release)
        self.autocomplete_listbox.bind('<Button-1>', self.on_listbox_select)
        self.autocomplete_listbox.bind('<Return>', self.on_listbox_select)
        self.license_entry.bind('<Down>', self.on_down_arrow)
        self.license_entry.bind('<Return>', self.on_entry_return)
        
        styles.create_button(input_frame, "Создать наряд", self.create_new_order, 'Primary.TButton').pack(side='left', padx=(0, 10))
        
        styles.create_button(input_frame, "Пробить", self.process_payment_for_current_order, 'Success.TButton').pack(side='left')
        
        top_card = styles.create_card_frame(self.frame)
        top_card.pack(fill='x', padx=15, pady=(0, 10))
        
        top_inner = ttk.Frame(top_card, style='White.TFrame')
        top_inner.pack(fill='both', expand=True, padx=15, pady=10)
        
        self.services_frame = ttk.Frame(top_inner, style='White.TFrame')
        self.services_frame.pack(fill='x')
        
        self.load_service_buttons()
        
        # Область нарядов должна занимать всё оставшееся место.
        # Раньше она паковалась как fill='x' и получала только свою
        # естественную высоту, а всё свободное пространство забирал
        # пустой фрейм под ней — из-за этого таблица услуг схлопывалась.
        tabs_frame = ttk.Frame(self.frame, style='BG.TFrame')
        tabs_frame.pack(fill='both', expand=True, padx=15, pady=(0, 15))

        self.order_notebook = ttk.Notebook(tabs_frame)
        self.order_notebook.pack(fill='both', expand=True)

        self.order_notebook.bind('<<NotebookTabChanged>>', self.on_tab_change)


    def load_service_buttons(self):
        """
        Построить кнопки услуг из прайс-листа.

        Список кнопок больше не вписан в код: имена берутся из прайса,
        а порядок по колонкам — из настроек. Поэтому услуга, добавленная
        в прайс-лист, сразу получает кнопку, а удалённая — теряет её.
        """
        from services.service_layout import build_columns, COLUMN_COUNT

        services = self.order_service.get_all_services()
        unique_names = list(dict.fromkeys([s.name for s in services]))
        columns = build_columns(self.db, unique_names)

        # Метод вызывают при каждом возврате в раздел. Перерисовываем
        # только когда набор кнопок правда изменился: иначе кнопки
        # моргали бы на ровном месте
        signature = tuple(tuple(column) for column in columns)
        if signature == getattr(self, '_service_buttons_signature', None):
            return
        self._service_buttons_signature = signature

        for child in self.services_frame.winfo_children():
            child.destroy()

        for index in range(COLUMN_COUNT):
            # У последней колонки отступа справа нет — иначе она
            # отъезжает от края
            right_padding = 0 if index == COLUMN_COUNT - 1 else 5
            frame = ttk.Frame(self.services_frame, style='White.TFrame')
            frame.pack(side='left', fill='both', expand=True, padx=(0, right_padding))
            frame.columnconfigure(0, weight=1)

            for row, service_name in enumerate(columns[index]):
                ttk.Button(
                    frame, text=service_name,
                    command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                    style='Service.TButton'
                ).grid(row=row, column=0, padx=3 if index == 0 else 2,
                       pady=2, sticky='ew')

    def update_license_plates_list(self):
        """Загрузить список всех номеров машин"""
        self.all_license_plates = self.order_service.get_all_license_plates()
    
    def on_license_key_release(self, event):
        """Фильтровать и показывать список при вводе"""
        # Игнорируем специальные клавиши
        if event.keysym in ('Down', 'Up', 'Return', 'Escape'):
            return
            
        # Нормализуем ввод: набранное латиницей "a123" должно находить "А123..."
        typed = normalize_plate(self.license_var.get())

        # Очищаем список
        self.autocomplete_listbox.delete(0, tk.END)

        if typed == '':
            # Скрываем список если пусто
            self.hide_autocomplete_list()
        else:
            # Сначала номера, начинающиеся с введённого, затем содержащие его:
            # так можно искать и по началу номера, и по одним цифрам
            starts = [p for p in self.all_license_plates if normalize_plate(p).startswith(typed)]
            contains = [p for p in self.all_license_plates
                        if typed in normalize_plate(p) and p not in starts]
            filtered = starts + contains

            if filtered:
                for plate in filtered:
                    self.autocomplete_listbox.insert(tk.END, plate)
                self.show_autocomplete_list()
            else:
                self.hide_autocomplete_list()
    
    def show_autocomplete_list(self):
        """Показать список подсказок под полем ввода"""
        self.listbox_frame.pack(fill='x')
    
    def hide_autocomplete_list(self):
        """Скрыть список подсказок"""
        self.listbox_frame.pack_forget()
    
    def on_down_arrow(self, event):
        """Переход к списку при нажатии стрелки вниз"""
        if self.autocomplete_listbox.size() > 0:
            self.autocomplete_listbox.focus_set()
            self.autocomplete_listbox.selection_set(0)
            self.autocomplete_listbox.activate(0)
        return 'break'
    
    def on_entry_return(self, event):
        """Обработка Enter в поле ввода"""
        # Если есть первый элемент в списке, выбираем его
        if self.autocomplete_listbox.size() > 0:
            selected_plate = self.autocomplete_listbox.get(0)
            self.select_plate(selected_plate)
        return 'break'
    
    def on_listbox_select(self, event):
        """Выбор элемента из списка"""
        if self.autocomplete_listbox.curselection():
            index = self.autocomplete_listbox.curselection()[0]
            selected_plate = self.autocomplete_listbox.get(index)
            self.select_plate(selected_plate)
    
    def select_plate(self, plate):
        """Установить выбранный номер и автозаполнить данные"""
        selected_plate = normalize_plate(plate)
        self.license_var.set(selected_plate)
        self.hide_autocomplete_list()

        if not selected_plate:
            return

        # Сначала пытаемся получить данные из машины (приоритет)
        car = self.order_service.get_car_by_license_plate(selected_plate)

        if car and car.vehicle_type and car.wheel_diameter:
            # Данные из Car (запомненные параметры машины)
            self.prefilled_data = {
                'diameter': car.wheel_diameter,
                'vehicle_type': car.vehicle_type,
                'client_name': None,
                'client_phone': None,
                'client_id': None
            }
        else:
            # Если нет данных в Car, получаем из последнего наряда
            last_order = self.order_service.get_last_order_for_car(selected_plate)
            if last_order:
                self.prefilled_data = {
                    'diameter': last_order.wheel_diameter,
                    'vehicle_type': last_order.vehicle_type,
                    'client_name': None,
                    'client_phone': None,
                    'client_id': None
                }
            else:
                self.prefilled_data = None

        # Владельца берём из самой машины: он закреплён за ней и не зависит
        # от того, какой наряд был последним
        if self.prefilled_data is not None:
            owner = car.client if car else None
            if owner is None:
                last_order = self.order_service.get_last_order_for_car(selected_plate)
                owner = last_order.client if last_order else None
            if owner is not None:
                self.prefilled_data['client_id'] = owner.id
                self.prefilled_data['client_name'] = owner.name
                self.prefilled_data['client_phone'] = owner.phone
            else:
                self.prefilled_data = None
        
        # Автоматически открываем диалог создания наряда
        self.create_new_order()
    
    def create_new_order(self):
        license = normalize_plate(self.license_entry.get())
        if not license:
            messagebox.showerror("Ошибка", "Введите номер автомобиля")
            return

        # Проверяем наличие открытой смены
        current_shift = self.shift_service.get_current_shift()
        if not current_shift:
            messagebox.showwarning("Предупреждение", "Откройте смену перед началом работы")
            return

        dialog = tk.Toplevel(self.frame)
        dialog.title("Детали наряда")
        dialog.geometry("470x620")
        dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, f"Создание наряда для {license}", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))

        # Получаем предзаполненные данные если есть
        prefilled = getattr(self, 'prefilled_data', None)

        styles.create_label(content, "Диаметр колеса*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        diameter_var = tk.StringVar(value=prefilled['diameter'] if prefilled else '')
        diameter_combo = ttk.Combobox(content, textvariable=diameter_var,
                                      values=['R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24'],
                                      font=styles.FONTS['normal'], state='readonly')
        diameter_combo.pack(fill='x', pady=(0, 12))

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
        vehicle_type_combo.pack(fill='x', pady=(0, 12))

        # Колёса в сборе или нет. От этого втрое отличается время работы,
        # поэтому спрашиваем сразу и запоминаем за машиной.
        wheels_options = {
            'Не выяснено': None,
            'В сборе (на дисках)': True,
            'Без дисков (только шины)': False,
        }
        wheels_reverse = {True: 'В сборе (на дисках)', False: 'Без дисков (только шины)'}

        car = self.order_service.get_car_by_license_plate(license)
        default_wheels = wheels_reverse.get(
            car.wheels_assembled if car else None, 'Не выяснено')

        styles.create_label(content, "Колёса:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        wheels_var = tk.StringVar(value=default_wheels)
        ttk.Combobox(content, textvariable=wheels_var, values=list(wheels_options.keys()),
                     font=styles.FONTS['normal'], state='readonly').pack(fill='x', pady=(0, 12))

        # ---------------------------------------------------------------
        # Клиент
        # ---------------------------------------------------------------
        ttk.Separator(content, orient='horizontal').pack(fill='x', pady=(5, 10))

        client_header = ttk.Frame(content, style='White.TFrame')
        client_header.pack(fill='x', pady=(0, 5))
        styles.create_label(client_header, "Клиент", 'CardHeading.TLabel').pack(side='left')
        styles.create_button(client_header, "Найти клиента",
                             lambda: open_client_search(), 'Secondary.TButton').pack(side='right')

        # Выбранный клиент хранится тут: None = будет создан новый по телефону
        selected = {'client_id': prefilled.get('client_id') if prefilled else None}

        styles.create_label(content, "Номер телефона:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        client_phone_entry = styles.create_entry(content, width=40)
        if prefilled and prefilled.get('client_phone'):
            client_phone_entry.insert(0, format_phone(prefilled['client_phone']))
        client_phone_entry.pack(fill='x', pady=(0, 10))

        styles.create_label(content, "Имя клиента:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        client_name_entry = styles.create_entry(content, width=40)
        if prefilled and prefilled.get('client_name'):
            client_name_entry.insert(0, prefilled['client_name'])
        client_name_entry.pack(fill='x', pady=(0, 8))

        # Строка состояния: новый клиент или постоянный, и сколько у него машин
        client_status = ttk.Label(content, text="", font=(styles.DEFAULT_FONT, 9),
                                  foreground='#64748b', wraplength=410, justify='left')
        client_status.pack(anchor='w', pady=(0, 12))

        def show_client(client):
            """Показать сведения о выбранном клиенте и подставить его данные."""
            if client is None:
                selected['client_id'] = None
                client_status.config(text="Новый клиент — будет добавлен в базу",
                                     foreground='#64748b')
                return

            selected['client_id'] = client.id

            client_phone_entry.delete(0, tk.END)
            client_phone_entry.insert(0, format_phone(client.phone) if client.phone else '')
            client_name_entry.delete(0, tk.END)
            client_name_entry.insert(0, client.name or '')

            summary = self.client_service.get_client_summary(client.id)
            plates = [c.license_plate for c in summary['cars']]
            other = [p for p in plates if p != license]

            text = f"Постоянный клиент · визитов: {summary['visits']}"
            if other:
                text += f"\nДругие машины: {', '.join(other)}"
            if license not in plates:
                text += f"\nМашина {license} будет закреплена за этим клиентом"
            client_status.config(text=text, foreground='#059669')

        def lookup_by_phone(event=None):
            """Когда кассир ввёл телефон — сразу проверяем, знаем ли мы клиента."""
            phone = client_phone_entry.get().strip()
            if not phone:
                show_client(None)
                return
            existing = self.client_service.find_by_phone(phone)
            show_client(existing)

        client_phone_entry.bind('<FocusOut>', lookup_by_phone)
        client_phone_entry.bind('<Return>', lookup_by_phone)

        def open_client_search():
            chosen = self.open_client_search_dialog(dialog)
            if chosen is not None:
                show_client(chosen)

        # Начальное состояние строки
        if selected['client_id']:
            existing = self.db.query(Client).filter(Client.id == selected['client_id']).first()
            show_client(existing)
        else:
            lookup_by_phone()

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

            # Если кассир правил телефон после выбора клиента, ищем заново:
            # выбранный ранее клиент мог перестать соответствовать введённому номеру
            client_id = selected['client_id']
            if client_id is not None and client_phone:
                current = self.db.query(Client).filter(Client.id == client_id).first()
                if current and normalize_phone(current.phone) != normalize_phone(client_phone):
                    client_id = None

            try:
                order = self.order_service.create_order(
                    license, diameter, vehicle_type,
                    client_name=client_name,
                    client_phone=client_phone,
                    client_id=client_id,
                    wheels_assembled=wheels_options.get(wheels_var.get())
                )
                self.open_order_tab(order)
                self.license_entry.delete(0, tk.END)
                self.update_license_plates_list()
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        styles.create_button(content, "Создать наряд", create, 'Primary.TButton').pack(fill='x')

    def open_client_search_dialog(self, parent):
        """
        Окно поиска клиента. Возвращает выбранного клиента или None.

        Искать можно как угодно: по телефону (хватит последних цифр),
        по имени или по госномеру любой из машин клиента.
        """
        result = {'client': None}

        dialog = tk.Toplevel(parent)
        dialog.title("Поиск клиента")
        dialog.geometry("640x460")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(parent)
        dialog.grab_set()
        styles.center_window(dialog, parent)

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, "Поиск по телефону, имени или номеру машины",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 12))

        search_row = ttk.Frame(content, style='White.TFrame')
        search_row.pack(fill='x', pady=(0, 12))

        query_entry = styles.create_entry(search_row, width=36)
        query_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        query_entry.focus_set()

        tree = ttk.Treeview(content, columns=('Имя', 'Телефон', 'Машины'),
                            show='headings', height=12)
        tree.heading('Имя', text='Имя')
        tree.heading('Телефон', text='Телефон')
        tree.heading('Машины', text='Машины')
        tree.column('Имя', width=170, anchor='w')
        tree.column('Телефон', width=150, anchor='center')
        tree.column('Машины', width=250, anchor='w')

        status = ttk.Label(content, text="", font=(styles.DEFAULT_FONT, 9), foreground='#64748b')

        def do_search(event=None):
            for row in tree.get_children():
                tree.delete(row)

            query = query_entry.get().strip()
            if not query:
                status.config(text="Введите телефон, имя или номер машины")
                return

            found = self.client_service.search(query)
            if not found:
                status.config(text=f"По запросу «{query}» никого не нашлось", foreground='#dc2626')
                return

            for client in found:
                plates = [c.license_plate for c in self.client_service.get_client_cars(client.id)]
                tree.insert('', 'end', values=(
                    client.name or 'без имени',
                    format_phone(client.phone) if client.phone else '—',
                    ', '.join(plates) if plates else '—'
                ), tags=(str(client.id),))

            status.config(text=f"Найдено: {len(found)}", foreground='#059669')

        def choose(event=None):
            selection = tree.selection()
            if not selection:
                return
            client_id = int(tree.item(selection[0])['tags'][0])
            result['client'] = self.db.query(Client).filter(Client.id == client_id).first()
            dialog.destroy()

        styles.create_button(search_row, "Найти", do_search, 'Primary.TButton').pack(side='left')
        query_entry.bind('<Return>', do_search)

        tree.pack(fill='both', expand=True, pady=(0, 8))
        tree.bind('<Double-1>', choose)
        status.pack(anchor='w', pady=(0, 10))

        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x')
        styles.create_button(buttons, "Выбрать", choose, 'Success.TButton').pack(side='left', fill='x', expand=True, padx=(0, 5))
        styles.create_button(buttons, "Отмена", dialog.destroy, 'Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(5, 0))

        parent.wait_window(dialog)
        return result['client']
    
    def open_order_tab(self, order):
        tab_frame = ttk.Frame(self.order_notebook)
        tab_title = f"  #{order.id}: {order.car.license_plate}  "
        self.order_notebook.add(tab_frame, text=tab_title)
        
        order_widget = OrderWidget(tab_frame, order, self.db, self.order_service, 
                                   self.salary_service, self.print_service, self.close_order_tab, self)
        self.active_orders[order.id] = order_widget
        
        self.order_notebook.select(tab_frame)
    
    def close_order_tab(self, order_id):
        if order_id in self.active_orders:
            widget = self.active_orders[order_id]
            # Отменяем отложенное автосохранение: вкладки уже не будет,
            # а обращение к разрушенному виджету уронит программу
            widget.cancel_autosave()
            self.order_notebook.forget(widget.frame)
            del self.active_orders[order_id]
    
    def add_service_to_current_order_by_name(self, service_name):
        log.debug(f"!!! BUTTON CLICKED: {service_name}")
        try:
            log.debug(f"Active orders: {list(self.active_orders.keys())}")
            log.debug(f"Notebook tabs: {len(self.order_notebook.tabs())}")
            
            if len(self.order_notebook.tabs()) == 0:
                log.debug("No tabs open!")
                messagebox.showwarning("Предупреждение", "Создайте наряд")
                return
            
            current_index = self.order_notebook.index(self.order_notebook.select())
            tabs = self.order_notebook.tabs()
            
            log.debug(f"Current tab index: {current_index}")
            log.debug(f"Total tabs: {len(tabs)}")
            
            if current_index < 0 or current_index >= len(tabs):
                messagebox.showwarning("Предупреждение", "Создайте наряд")
                return
            
            current_tab_widget = self.order_notebook.nametowidget(tabs[current_index])
            log.debug(f"Current tab widget: {current_tab_widget}")
            
            for order_id, widget in self.active_orders.items():
                log.debug(f"Checking order_id={order_id}, widget.frame={widget.frame}")
                if widget.frame == current_tab_widget:
                    log.debug(f"MATCH! Calling add_service_by_name for order {order_id}")
                    widget.add_service_by_name(service_name)
                    return
            
            log.debug("No matching widget found!")
            messagebox.showwarning("Ошибка", "Не удалось найти активный наряд")
        except Exception as e:
            log.error(f"!!! ERROR in add_service_to_current_order_by_name: {e}")
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
            log.error(f"ERROR in process_payment_for_current_order: {e}")
            import traceback
            traceback.print_exc()
            messagebox.showerror("Ошибка", str(e))
    
    def on_tab_change(self, event):
        pass
