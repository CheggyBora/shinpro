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

def _two_lines(name, limit):
    """
    Длинное название — в две строки по пробелу ближе к середине: плитка
    узкая, а «Подкачка/проверка давления» иначе обрезается.
    """
    if len(name) <= limit or ' ' not in name:
        return name
    middle = len(name) // 2
    spaces = [i for i, ch in enumerate(name) if ch == ' ']
    cut = min(spaces, key=lambda i: abs(i - middle))
    return name[:cut] + '\n' + name[cut + 1:]


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
        # Какое направление выбрано сверху: шиномонтаж или мойка
        # (services/directions.py). Кнопки услуг и вкладки нарядов — его
        from services import directions as _directions
        self.mode = _directions.enabled(db)[0]
        
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
        
        styles.create_button(input_frame, "Создать наряд", self.create_new_order, 'Primary.TButton').pack(side='left', padx=(0, 6))
        # Наряд по фото: телефон снимает машину, номер читается сам
        # (docs/order_photo.md)
        self.qr_button = styles.create_button(input_frame, "QR", self.show_phone_code,
                                              'Secondary.TButton')
        self.qr_button.pack(side='left', padx=(0, 10))
        self._pending_arrival = None
        # «Пробить» — после QR: прячем и возвращаем QR на его место
        self._qr_anchor = None
        
        self._pay_button = styles.create_button(input_frame, "Пробить", self.process_payment_for_current_order, 'Success.TButton')
        self._pay_button.pack(side='left')
        self.refresh_qr()
        
        # Лента задач на сегодня: всегда на виду, без окон и «ОК».
        # Скоро — жёлтая, просрочено — красная (docs/calendar.md)
        self.app = None
        self.tasks_strip = tk.Frame(self.frame, bg=styles.COLORS['bg_card'],
                                    highlightthickness=1,
                                    highlightbackground=styles.COLORS['border'])
        self.tasks_strip.pack(fill='x', padx=15, pady=(0, 10))
        self.refresh_tasks()

        # Кнопки услуг слева, наряд справа — оба на всю высоту (решение
        # владельца 28.10.2026). Раньше кнопки стояли над нарядом, и наряду
        # оставалась нижняя треть: на мониторе 1920×1080 была видна одна
        # позиция, на 1366×768 — ни одной
        body = ttk.Frame(self.frame, style='BG.TFrame')
        body.pack(fill='both', expand=True, padx=15, pady=(0, 15))
        body.columnconfigure(0, weight=9, uniform='halves')
        body.columnconfigure(1, weight=11, uniform='halves')
        body.rowconfigure(0, weight=1)

        top_card = styles.create_card_frame(body)
        top_card.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        top_inner = ttk.Frame(top_card, style='White.TFrame')
        top_inner.pack(fill='both', expand=True, padx=12, pady=10)

        self.services_frame = ttk.Frame(top_inner, style='White.TFrame')
        self.services_frame.pack(fill='both', expand=True)

        self.load_service_buttons()

        # Наряды — справа, на всю оставшуюся высоту
        tabs_frame = ttk.Frame(body, style='BG.TFrame')
        tabs_frame.grid(row=0, column=1, sticky='nsew')

        self.order_notebook = ttk.Notebook(tabs_frame)
        self.order_notebook.pack(fill='both', expand=True)



    def load_service_buttons(self):
        """
        Построить кнопки услуг из прайс-листа.

        Список кнопок больше не вписан в код: имена берутся из прайса,
        а порядок по колонкам — из настроек. Поэтому услуга, добавленная
        в прайс-лист, сразу получает кнопку, а удалённая — теряет её.
        """
        from services.service_layout import build_columns

        services = [s for s in self.order_service.get_all_services()
                    if (getattr(s, 'direction', None) or 'tire') == self.mode]
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

        # Крупные плитки в три колонки на всю высоту (решение владельца
        # 28.10.2026). Порядок — как в раскладке из настроек: колонка за
        # колонкой, сверху вниз. Шрифт — по экрану: на 1366×768 крупный
        # не влезает
        names = [name for column in columns for name in column]
        tiles = 3
        rows = max(1, (len(names) + tiles - 1) // tiles)
        style = ttk.Style()
        style.configure('Tile.Service.TButton', font=(styles.DEFAULT_FONT, 11, 'bold'),
                        padding=(4, 0), anchor='center', justify='center')

        def fit(event, rows=rows):
            # Две строки шрифта должны влезть в плитку: на 1920×1080 плитка
            # высокая — 11 жирным, на 1366×768 низкая — мельче
            tile = event.height / rows - 6
            size = 11 if tile >= 46 else 10 if tile >= 40 else 9 if tile >= 35 else 8
            if size != getattr(self, '_tile_font', None):
                self._tile_font = size
                style.configure('Tile.Service.TButton', font=(styles.DEFAULT_FONT, size, 'bold'))

        self.services_frame.bind('<Configure>', fit)

        for index, service_name in enumerate(names):
            ttk.Button(
                self.services_frame, text=_two_lines(service_name, 20),
                command=lambda name=service_name: self.add_service_to_current_order_by_name(name),
                style='Tile.Service.TButton'
            ).grid(row=index % rows, column=index // rows, padx=3, pady=3, sticky='nsew')
        for column in range(tiles):
            self.services_frame.columnconfigure(column, weight=1, uniform='tile')
        for row in range(rows):
            self.services_frame.rowconfigure(row, weight=1, uniform='tile')

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
        
        # Подсказка — к этому номеру: набрали другой — она не годится
        if self.prefilled_data is not None:
            self.prefilled_data['plate'] = selected_plate

        # Автоматически открываем диалог создания наряда
        self.create_new_order()
    
    def refresh_qr(self):
        """QR — только там, где наряд по фото включён (своё у шинки и мойки)."""
        from services import directions as _directions
        try:
            on = _directions.photo_on(self.db, self.mode)
        except Exception:
            self.db.rollback()
            on = False
        if on and not self.qr_button.winfo_ismapped():
            self.qr_button.pack(side='left', padx=(0, 10), before=self._pay_button)
        elif not on:
            self.qr_button.pack_forget()

    def show_phone_code(self):
        from ui.arrival_dialog import PhoneCodeDialog
        PhoneCodeDialog(self.frame, self.db)

    def open_arrival(self, arrival):
        """
        Машина с телефона: окно создания с номером, клиентом и снимком.
        Наряд создаёт приёмщик — сам по себе он не появится.
        """
        if self.app is not None:
            self.app.show_orders()
        self._pending_arrival = arrival
        self.license_var.set(normalize_plate(arrival.get('plate') or ''))
        self.select_plate(arrival.get('plate') or '')
        # Окно не открылось (нет номера) — машина не должна прилипнуть к
        # следующему наряду, набранному руками
        self._pending_arrival = None

    def _arrival_done(self, arrival, order_id=None):
        """Сказать серверу, что машина разобрана, — в фоне: связь бывает медленной."""
        import threading

        def worker():
            from config import SessionLocal
            from services.arrival_service import ArrivalService
            db = SessionLocal()
            try:
                ArrivalService(db).done(arrival['id'], order_id)
            finally:
                db.close()

        threading.Thread(target=worker, daemon=True).start()

    def create_new_order(self):
        arrival, self._pending_arrival = getattr(self, '_pending_arrival', None), None
        # Подсказка из списка номеров годится только для этого номера:
        # раньше выбранная машина А подставляла клиента в наряд машины Б
        prefilled, self.prefilled_data = getattr(self, 'prefilled_data', None), None
        open_dialog = getattr(self, 'create_dialog', None)
        if open_dialog is not None and open_dialog.winfo_exists():
            # Второе окно — второй наряд на ту же машину
            open_dialog.lift()
            open_dialog.focus_force()
            return
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
        # Открыто ли окно создания — машина с телефона ждёт, пока закроют
        self.create_dialog = dialog
        dialog.geometry("470x760")
        dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, f"Создание наряда для {license}"
                            + (" · с телефона" if arrival else ""),
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))

        # Машина с телефона: снимок сбоку — будущая обложка наряда.
        # Закрыли окно, не создав, — машина снимается
        if arrival is not None:
            from services.arrival_service import load_image, show_full
            image = load_image(arrival['photo'], 200, 150) if arrival.get('photo') else None
            if image is not None:
                photo = tk.Label(content, image=image, cursor='hand2', bd=0,
                                 bg=styles.COLORS['bg_card'])
                photo.image = image
                photo.pack(anchor='w', pady=(0, 10))
                photo.bind('<Button-1>', lambda e: show_full(dialog, arrival['photo']))

            def dismiss():
                self._arrival_done(arrival, None)
                dialog.destroy()

            dialog.protocol('WM_DELETE_WINDOW', dismiss)
            dialog.geometry("470x900")

        # Предзаполненные данные — только если номер тот же, что выбирали
        if prefilled is not None and prefilled.get('plate') not in (None, license):
            prefilled = None

        # На что приехал: шиномонтаж, мойка или оба. Если на объекте
        # работает одно направление — выбирать нечего
        from services import directions as _directions
        enabled_directions = _directions.enabled(self.db)
        chosen_on_phone = (arrival or {}).get('directions') or []
        direction_vars = {d: tk.BooleanVar(value=(d in chosen_on_phone) if chosen_on_phone else (d == self.mode))
                          for d in enabled_directions}
        wash_class_var = tk.StringVar()
        if len(enabled_directions) > 1:
            styles.create_label(content, "Направление*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
            row = ttk.Frame(content, style='White.TFrame')
            row.pack(fill='x', pady=(0, 10))
            for d in enabled_directions:
                ttk.Checkbutton(row, text=_directions.TITLES[d], variable=direction_vars[d]).pack(
                    side='left', padx=(0, 14))
        # Мастеров выбирают на наряд (тумблер в настройках) — исполнители
        # шиномонтажа отмечаются сразу при создании
        performer_vars = {}
        if _directions.tire_assign(self.db) and _directions.TIRE in enabled_directions:
            from ui.order_screen.directions import wash_people
            styles.create_label(content, "Исполнители шиномонтажа*:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
            people_row = ttk.Frame(content, style='White.TFrame')
            people_row.pack(fill='x', pady=(0, 10))
            for person in wash_people(self.db)[:8]:
                performer_vars[person.id] = tk.BooleanVar(value=False)
                ttk.Checkbutton(people_row, text=person.title,
                                variable=performer_vars[person.id]).pack(side='left', padx=(0, 10))

        if _directions.WASH in enabled_directions:
            known = self.order_service.get_car_by_license_plate(license)
            if known is not None and known.wash_class:
                wash_class_var.set(_directions.class_title(known.wash_class))
            styles.create_label(content, "Класс для мойки:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
            ttk.Combobox(content, textvariable=wash_class_var, state='readonly',
                         values=[_directions.WASH_CLASS_TITLES[k] for k in _directions.WASH_CLASSES],
                         font=styles.FONTS['normal']).pack(fill='x', pady=(0, 12))

        styles.create_label(content, "Диаметр колеса (для шиномонтажа):", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
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

            chosen_directions = [d for d, var in direction_vars.items() if var.get()]
            if not chosen_directions:
                messagebox.showerror("Ошибка", "Отметьте, на что приехал: шиномонтаж или мойка")
                return
            wash_class = _directions.class_by_title(wash_class_var.get())
            if _directions.WASH in chosen_directions and not wash_class:
                messagebox.showerror("Ошибка", "Для мойки выберите класс машины")
                return
            if _directions.TIRE in chosen_directions and not diameter:
                messagebox.showerror("Ошибка", "Заполните диаметр колеса")
                return
            performers = [pid for pid, var in performer_vars.items() if var.get()]
            if performer_vars and _directions.TIRE in chosen_directions and not performers:
                messagebox.showerror("Ошибка", "Отметьте, кто будет делать шиномонтаж")
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
                    wheels_assembled=wheels_options.get(wheels_var.get()),
                    directions=chosen_directions,
                    wash_class=wash_class
                )
                if performers:
                    self.order_service.set_order_masters(order.id, performers)
                # Машина встаёт на пост: без номера поста программа
                # считала бы его свободным и позвала бы туда очередь.
                # Пост мойки наряд занял сам при создании
                from services.live_queue_service import LiveQueueService
                queue = LiveQueueService(self.db)
                wheels = wheels_options.get(wheels_var.get())
                if queue.enabled() and _directions.TIRE in chosen_directions:
                    order.post_number = queue.first_free_post()
                    if wheels is not None:
                        order.package_minutes = queue.package_minutes(wheels)
                    self.db.commit()
                if arrival is not None:
                    from services.arrival_service import ArrivalService
                    ArrivalService(self.db).attach(order, arrival.get('photo'))
                    self._arrival_done(arrival, order.id)
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
    
    STRIP_LIMIT = 6

    def refresh_tasks(self):
        from services.calendar_service import CalendarService
        from ui.task_dialog import CATEGORY_COLORS
        for child in self.tasks_strip.winfo_children():
            child.destroy()
        try:
            service = CalendarService(self.db)
            tasks = service.strip()
            from services import directions as _directions
            wash = _directions.wash_on(self.db)
        except Exception:
            self.db.rollback()
            return
        tk.Label(self.tasks_strip, text='Сегодня:' if tasks else 'Сегодня задач нет',
                 bg=styles.COLORS['bg_card'], fg=styles.COLORS['text_secondary'],
                 font=(styles.DEFAULT_FONT, 9)).pack(side='left', padx=(8, 6), pady=5)
        colors = {'overdue': ('#b91c1c', '#fee2e2'), 'soon': ('#92400e', '#fef3c7')}
        from utils import as_naive, get_moscow_time
        today = as_naive(get_moscow_time()).date()
        for task in tasks[:self.STRIP_LIMIT]:
            state = service.state(task)
            fg, bg = colors.get(state) or (styles.COLORS['text'], styles.COLORS['bg_subtle'])
            when = task.due_time or ''
            if task.due_date < today:
                when = f'{task.due_date:%d.%m}'
            text = f'{when} {task.title}'.strip()
            # Календарь общий: задачи мойки помечены «М»
            if wash and (task.direction or 'tire') == 'wash':
                text = f'М · {text}'
            if task.license_plate and task.license_plate not in text:
                text += f' · {task.license_plate}'
            chip = tk.Label(self.tasks_strip, text=text[:48], bg=bg, fg=fg, cursor='hand2',
                            padx=8, pady=2, font=(styles.DEFAULT_FONT, 9))
            chip.pack(side='left', padx=(0, 4), pady=4)
            dot = CATEGORY_COLORS.get(task.category, CATEGORY_COLORS['work'])[0]
            chip.config(highlightthickness=2, highlightbackground=dot)
            chip.bind('<Button-1>', lambda e, t=task: self._open_task(t))
        if len(tasks) > self.STRIP_LIMIT:
            more = tk.Label(self.tasks_strip, text=f'+{len(tasks) - self.STRIP_LIMIT}',
                            bg=styles.COLORS['bg_card'], fg=styles.COLORS['primary'],
                            cursor='hand2', font=(styles.DEFAULT_FONT, 9, 'underline'))
            more.pack(side='left', padx=4)
            more.bind('<Button-1>', lambda e: self.app and self.app.show_calendar())

    def _open_task(self, task):
        from ui.task_dialog import open_task
        open_task(self.frame, self.db, task, on_saved=self._tasks_changed)

    def _tasks_changed(self):
        self.refresh_tasks()
        for widget in self.active_orders.values():
            if hasattr(widget, 'refresh_tasks'):
                widget.refresh_tasks()
        if self.app is not None:
            self.app._calendar_refresh()

    def open_plate(self, plate):
        """Открыть наряд на номер — из «всё по машине»."""
        if self.app is not None:
            self.app.show_orders()
        self.license_var.set(plate)
        self.select_plate(plate)

    def set_mode(self, mode):
        """Переключили направление: свои кнопки услуг и свои наряды."""
        from services import directions as _directions
        self.mode = mode
        self._service_buttons_signature = None
        self.load_service_buttons()
        for order_id, widget in self.active_orders.items():
            tab = widget.frame
            try:
                state = 'normal' if mode in _directions.parse(widget.order.directions) else 'hidden'
                self.order_notebook.tab(tab, state=state)
            except Exception:
                pass
            if hasattr(widget, 'refresh_directions'):
                widget.refresh_directions()
        self.refresh_tasks()
        if hasattr(self, 'qr_button'):
            self.refresh_qr()

    def open_order_tab(self, order):
        tab_frame = ttk.Frame(self.order_notebook)
        tab_title = f"  #{order.id}: {order.car.license_plate}  "
        # Обложка на вкладке: когда открыто пять нарядов, машину находишь
        # глазами, а не по номеру
        from services.arrival_service import cover_file, load_image
        cover = cover_file(order, self.db)
        tab_image = load_image(cover, 36, 27) if cover else None
        if tab_image is not None:
            self.order_notebook.add(tab_frame, text=tab_title, image=tab_image, compound='left')
        else:
            self.order_notebook.add(tab_frame, text=tab_title)
        
        order_widget = OrderWidget(tab_frame, order, self.db, self.order_service, 
                                   self.salary_service, self.print_service, self.close_order_tab, self)
        self.active_orders[order.id] = order_widget
        order_widget._tab_image = tab_image

        self.order_notebook.select(tab_frame)

    def close_order_tab(self, order_id):
        if order_id in self.active_orders:
            widget = self.active_orders[order_id]
            # Отменяем отложенное автосохранение: вкладки уже не будет,
            # а обращение к разрушенному виджету уронит программу
            widget.cancel_autosave()
            self.order_notebook.forget(widget.frame)
            # Без destroy закрытый наряд со всеми виджетами и картинками
            # оставался в памяти до конца дня
            widget.frame.destroy()
            del self.active_orders[order_id]
    
    def current_widget(self):
        """
        Наряд на открытой вкладке или None. Пустой select() бывает, когда все
        вкладки скрыты переключателем направлений: раньше это падало с
        «Invalid slave specification» (ревью 26.10.2026).
        """
        current = self.order_notebook.select()
        if not current:
            return None
        for widget in self.active_orders.values():
            if str(widget.frame) == str(current):
                return widget
        return None

    def add_service_to_current_order_by_name(self, service_name):
        widget = self.current_widget()
        if widget is None:
            messagebox.showwarning("Предупреждение", "Создайте или откройте наряд")
            return
        try:
            widget.add_service_by_name(service_name)
        except Exception as e:
            self.db.rollback()
            log.error(f"Услуга «{service_name}» не добавилась: {e}")
            messagebox.showerror("Ошибка", str(e))

    def process_payment_for_current_order(self):
        """Обработать оплату для текущего активного наряда"""
        widget = self.current_widget()
        if widget is None:
            messagebox.showwarning("Предупреждение", "Создайте или откройте наряд")
            return
        try:
            widget.process_payment()
        except Exception as e:
            self.db.rollback()
            log.error(f"Оплата не открылась: {e}")
            messagebox.showerror("Ошибка", str(e))
