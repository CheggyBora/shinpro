import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import List
from models import Service, Settings
import styles

class PriceListTab:
    def __init__(self, parent, db):
        self.db = db
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.current_vehicle_type = 'car'
        self.editing_item = None
        self.editing_column = None
        self.is_authenticated = False
        
        # Создаем контейнеры для двух экранов
        self.login_frame = None
        self.content_frame = None
        
        # Показываем экран входа
        self.show_login_screen()
    
    def show_login_screen(self):
        """Показать экран входа с PIN-кодом"""
        # Удаляем предыдущий экран входа если есть
        if self.login_frame:
            self.login_frame.destroy()
        
        # Создаем экран входа
        self.login_frame = ttk.Frame(self.frame, style='BG.TFrame')
        self.login_frame.pack(fill='both', expand=True)
        
        # Центральный контейнер
        center_frame = ttk.Frame(self.login_frame, style='BG.TFrame')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Иконка замка
        lock_label = tk.Label(center_frame, text="🔒", font=(styles.DEFAULT_FONT, 80), bg=styles.COLORS['bg'])
        lock_label.pack(pady=(0, 30))
        
        # Заголовок
        title_label = tk.Label(
            center_frame, 
            text="Доступ к прайс-листу",
            font=(styles.DEFAULT_FONT, 24, 'bold'),
            bg=styles.COLORS['bg'],
            fg=styles.COLORS['text']
        )
        title_label.pack(pady=(0, 10))
        
        # Подзаголовок
        subtitle_label = tk.Label(
            center_frame,
            text="Введите PIN-код администратора",
            font=(styles.DEFAULT_FONT, 14),
            bg=styles.COLORS['bg'],
            fg=styles.COLORS['gray']
        )
        subtitle_label.pack(pady=(0, 40))
        
        # Поле ввода PIN (увеличено в 1.5 раза)
        pin_frame = ttk.Frame(center_frame, style='BG.TFrame')
        pin_frame.pack(pady=(0, 30))
        
        self.pin_entry = tk.Entry(
            pin_frame,
            font=(styles.DEFAULT_FONT, 24),  # Шрифт 24pt (в 1.5 раза больше стандартного)
            show='●',
            width=12,
            justify='center',
            bg='white',
            fg=styles.COLORS['text'],
            relief='solid',
            borderwidth=2
        )
        self.pin_entry.pack()
        self.pin_entry.focus_set()
        
        # Привязка Enter для входа
        self.pin_entry.bind('<Return>', lambda e: self.check_pin())
        
        # Кнопка входа (большая)
        login_btn = tk.Button(
            center_frame,
            text="Войти",
            font=(styles.DEFAULT_FONT, 18, 'bold'),
            bg=styles.COLORS['primary'],
            fg='white',
            activebackground=styles.COLORS['primary_dark'],
            activeforeground='white',
            cursor='hand2',
            relief='flat',
            padx=60,
            pady=15,
            command=self.check_pin
        )
        login_btn.pack()
    
    def check_pin(self):
        """Проверка введенного PIN-кода"""
        settings = self.db.query(Settings).filter(Settings.key == 'admin_pin').first()
        stored_pin = settings.value if settings else '0000'
        
        entered_pin = self.pin_entry.get()
        
        if entered_pin == stored_pin:
            # PIN верный - показываем основной интерфейс
            self.is_authenticated = True
            self.login_frame.destroy()
            self.show_content_screen()
        else:
            # PIN неверный - показываем ошибку
            messagebox.showerror("Ошибка доступа", "Неверный PIN-код!\nДоступ запрещен.")
            self.pin_entry.delete(0, tk.END)
            self.pin_entry.focus_set()
    
    def show_content_screen(self):
        """Показать основной интерфейс прайс-листа"""
        # Создаем основной контейнер
        self.content_frame = ttk.Frame(self.frame, style='BG.TFrame')
        self.content_frame.pack(fill='both', expand=True)
        
        # Заголовок
        header_frame = ttk.Frame(self.content_frame, style='BG.TFrame')
        header_frame.pack(fill='x', padx=15, pady=(15, 10))
        
        styles.create_label(header_frame, "Управление прайс-листом", 'Heading.TLabel').pack(side='left')
        
        # Кнопки
        btn_frame = ttk.Frame(self.content_frame, style='BG.TFrame')
        btn_frame.pack(fill='x', padx=15, pady=(0, 10))
        
        styles.create_button(btn_frame, "Легковой", lambda: self.filter_by_vehicle_type('car'), 'Service.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(btn_frame, "Джип/Кроссовер", lambda: self.filter_by_vehicle_type('suv'), 'Service.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(btn_frame, "Категория С", lambda: self.filter_by_vehicle_type('truck'), 'Service.TButton').pack(side='left', padx=(0, 5))
        
        styles.create_button(btn_frame, "💾 Сохранить изменения", self.save_changes, 'Success.TButton').pack(side='right')
        
        # Карточка с таблицей
        card = styles.create_card_frame(self.content_frame)
        card.pack(fill='both', expand=True, padx=15, pady=(0, 15))
        
        card_inner = ttk.Frame(card, style='White.TFrame')
        card_inner.pack(fill='both', expand=True, padx=15, pady=15)
        
        # Таблица с прокруткой (вертикальная и горизонтальная)
        tree_frame = ttk.Frame(card_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        # Вертикальная прокрутка
        self.v_scrollbar = ttk.Scrollbar(tree_frame, orient='vertical')
        self.v_scrollbar.pack(side='right', fill='y')
        
        # Горизонтальная прокрутка
        self.h_scrollbar = ttk.Scrollbar(tree_frame, orient='horizontal')
        self.h_scrollbar.pack(side='bottom', fill='x')
        
        # Колонки: Услуга, R13-R24 (по умолчанию для легковых)
        columns = ['Услуга', 'R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24']
        self.current_columns = columns
        
        self.tree = ttk.Treeview(
            tree_frame, 
            columns=columns, 
            show='headings', 
            yscrollcommand=self.v_scrollbar.set,
            xscrollcommand=self.h_scrollbar.set,
            height=20
        )
        self.v_scrollbar.config(command=self.tree.yview)
        self.h_scrollbar.config(command=self.tree.xview)
        
        # Настройка колонок
        self.tree.column('Услуга', width=280, anchor='w', minwidth=180)
        self.tree.heading('Услуга', text='Услуга')
        
        for col in columns[1:]:
            self.tree.column(col, width=70, anchor='center', minwidth=60)
            self.tree.heading(col, text=col)
        
        self.tree.pack(fill='both', expand=True)
        
        # Двойной клик для редактирования
        self.tree.bind('<Double-1>', self.on_double_click)
        
        # Загружаем данные
        self.load_services()
    
    def filter_by_vehicle_type(self, vehicle_type):
        """Фильтр по типу транспорта"""
        self.current_vehicle_type = vehicle_type
        self.rebuild_table()
        self.load_services()
    
    def rebuild_table(self):
        """Перестроить таблицу с нужными колонками в зависимости от типа транспорта"""
        # Удаляем старую таблицу
        self.tree.destroy()
        
        # Определяем колонки в зависимости от типа
        if self.current_vehicle_type == 'truck':
            # Для грузовых только R15-R19
            columns = ['Услуга', 'R15', 'R16', 'R17', 'R18', 'R19']
        else:
            # Для легковых и джипов все радиусы
            columns = ['Услуга', 'R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24']
        
        # Создаем новую таблицу
        self.tree = ttk.Treeview(
            self.tree.master, 
            columns=columns, 
            show='headings', 
            yscrollcommand=self.v_scrollbar.set,
            xscrollcommand=self.h_scrollbar.set,
            height=20
        )
        self.v_scrollbar.config(command=self.tree.yview)
        self.h_scrollbar.config(command=self.tree.xview)
        
        # Настройка колонок
        self.tree.column('Услуга', width=280, anchor='w', minwidth=180)
        self.tree.heading('Услуга', text='Услуга')
        
        for col in columns[1:]:
            self.tree.column(col, width=70, anchor='center', minwidth=60)
            self.tree.heading(col, text=col)
        
        self.tree.pack(fill='both', expand=True)
        
        # Двойной клик для редактирования
        self.tree.bind('<Double-1>', self.on_double_click)
        
        # Сохраняем текущие колонки
        self.current_columns = columns
    
    def load_services(self):
        """Загрузить услуги из БД"""
        # Очищаем таблицу
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Загружаем все услуги: конкретного типа + универсальные ('all')
        all_services = self.db.query(Service).filter(
            (Service.vehicle_type == self.current_vehicle_type) | (Service.vehicle_type == 'all')
        ).all()
        
        if not all_services:
            messagebox.showwarning("Предупреждение", f"Нет услуг для типа транспорта: {self.current_vehicle_type}")
            return
        
        # Создаем словарь для быстрого поиска услуг по имени
        services_dict = {s.name: s for s in all_services}
        
        # Порядок услуг как в панели наряда (по столбцам слева направо)
        service_order = [
            # Столбец 1
            'Съем+Установка', 'Мойка', 'Шиномонтаж', 'Балансировка', 'Герметик обода',
            'Обработка смазкой', 'Правка литого диска', 'Ремонт грибком', 'Ремонт жгутом',
            # Столбец 2
            'Runflat', 'Оптимизация балансировки', 'Замена вентиля', 'Установка датчика давления',
            'Шлифовка бортов диска', 'Шлифовка ступицы', 'Косметический ремонт шины',
            'Дошиповка (за 1 шип)', 'Грязевая покрышка АТ/МТ',
            # Столбец 3
            'Зачистка диска от скотча', 'Слесарные работы', 'Открутка секретного болта',
            'Срыв болта/гайки', 'Прочие услуги', 'Ремонт бокового пореза',
            'Подкачка/проверка давления', 'Съем+Установка внутреннего колеса',
            # Столбец 4
            'Вентиль под датчик', 'Вентиль черный', 'Пакет', 'Золотник', 'Колпочки',
            'Проверка на герметичность', 'Проверка на балансировку', 'Проверка затяжки болтов'
        ]
        
        # Добавляем услуги в таблицу в нужном порядке
        for service_name in service_order:
            if service_name in services_dict:
                service = services_dict[service_name]
                
                if self.current_vehicle_type == 'truck':
                    # Для грузовых только R15-R19
                    values = [
                        service.name,
                        service.price_r15 or 0,
                        service.price_r16 or 0,
                        service.price_r17 or 0,
                        service.price_r18 or 0,
                        service.price_r19 or 0
                    ]
                else:
                    # Для легковых и джипов все радиусы
                    values = [
                        service.name,
                        service.price_r13 or 0,
                        service.price_r14 or 0,
                        service.price_r15 or 0,
                        service.price_r16 or 0,
                        service.price_r17 or 0,
                        service.price_r18 or 0,
                        service.price_r19 or 0,
                        service.price_r20 or 0,
                        service.price_r21 or 0,
                        service.price_r22 or 0,
                        service.price_r23 or 0,
                        service.price_r24 or 0
                    ]
                self.tree.insert('', 'end', values=values, tags=(str(service.id),))
    
    def on_double_click(self, event):
        """Обработка двойного клика для редактирования"""
        print(f"🔧 DOUBLE CLICK DETECTED at x={event.x}, y={event.y}")
        
        # Получаем элемент и колонку
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        
        print(f"🔧 Item: {item}, Column: {column}")
        
        if not item or column == '#1':  # Не редактируем название услуги
            print(f"🔧 SKIP: No item or column is #1")
            return
        
        # Определяем индекс колонки (R13=1, R14=2, и т.д.)
        column_index = int(column.replace('#', '')) - 1
        
        print(f"🔧 Column index: {column_index}")
        
        if column_index < 1:  # Не редактируем название
            print(f"🔧 SKIP: Column index < 1")
            return
        
        # Получаем текущее значение
        current_value = self.tree.item(item)['values'][column_index]
        
        print(f"🔧 Current value: {current_value}")
        
        # Запрашиваем новое значение
        new_value = simpledialog.askfloat(
            "Изменить цену",
            f"Введите новую цену:\n(текущая: {current_value} руб.)",
            initialvalue=current_value,
            minvalue=0,
            parent=self.frame.winfo_toplevel()
        )
        
        print(f"🔧 New value: {new_value}")
        
        if new_value is not None:
            # Обновляем в таблице
            values = list(self.tree.item(item)['values'])
            values[column_index] = int(new_value)
            self.tree.item(item, values=values)
            
            # Помечаем как измененное
            self.tree.item(item, tags=self.tree.item(item)['tags'] + ('modified',))
            print(f"🔧 Price updated to {int(new_value)}")
    
    def save_changes(self):
        """Сохранить изменения в БД"""
        modified_items = [item for item in self.tree.get_children() if 'modified' in self.tree.item(item)['tags']]
        
        if not modified_items:
            messagebox.showinfo("Информация", "Нет изменений для сохранения")
            return
        
        try:
            for item in modified_items:
                values = self.tree.item(item)['values']
                service_id = int(self.tree.item(item)['tags'][0])
                
                service = self.db.query(Service).filter(Service.id == service_id).first()
                
                if service:
                    if self.current_vehicle_type == 'truck':
                        # Для грузовых сохраняем только R15-R19
                        service.price_r15 = int(values[1])
                        service.price_r16 = int(values[2])
                        service.price_r17 = int(values[3])
                        service.price_r18 = int(values[4])
                        service.price_r19 = int(values[5])
                    else:
                        # Для легковых и джипов все радиусы
                        service.price_r13 = int(values[1])
                        service.price_r14 = int(values[2])
                        service.price_r15 = int(values[3])
                        service.price_r16 = int(values[4])
                        service.price_r17 = int(values[5])
                        service.price_r18 = int(values[6])
                        service.price_r19 = int(values[7])
                        service.price_r20 = int(values[8])
                        service.price_r21 = int(values[9])
                        service.price_r22 = int(values[10])
                        service.price_r23 = int(values[11])
                        service.price_r24 = int(values[12])
            
            self.db.commit()
            messagebox.showinfo("Успех", f"Сохранено изменений: {len(modified_items)}")
            
            # Перезагружаем данные
            self.load_services()
            
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить изменения:\n{str(e)}")
