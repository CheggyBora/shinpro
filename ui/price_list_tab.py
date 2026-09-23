import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import List
from models import Service, Settings
import styles
from logger import log

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
        
        # Значок замка: рисуем сами, а не эмодзи — его Windows не отображает
        lock_canvas = tk.Canvas(center_frame, width=90, height=90,
                                bg=styles.COLORS['bg'], highlightthickness=0)
        lock_canvas.create_arc(28, 18, 62, 56, start=0, extent=180, style='arc',
                               outline=styles.COLORS['secondary'], width=7)
        lock_canvas.create_rectangle(20, 46, 70, 82,
                                     fill=styles.COLORS['secondary'], outline='')
        lock_canvas.create_oval(41, 58, 49, 66, fill=styles.COLORS['bg_card'], outline='')
        lock_canvas.pack(pady=(0, 25))
        
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
        from services import AuthService, AuditService

        try:
            entered_pin = self.pin_entry.get()

            if AuthService(self.db).verify_pin(entered_pin):
                # PIN верный - показываем основной интерфейс
                self.is_authenticated = True
                self.login_frame.destroy()
                self.show_content_screen()
            else:
                # PIN неверный - записываем попытку и показываем ошибку
                AuditService(self.db).log(
                    AuditService.PIN_FAILED,
                    "Неверный PIN при входе в прайс-лист"
                )
                messagebox.showerror("Ошибка доступа", "Неверный PIN-код!\nДоступ запрещен.")
                self.pin_entry.delete(0, tk.END)
                self.pin_entry.focus_set()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Ошибка при проверке PIN: {str(e)}")
            self.pin_entry.delete(0, tk.END)
            self.pin_entry.focus_set()
    
    def show_consumables_and_duration(self):
        """
        Окно «Расходники и время»: себестоимость материалов и длительность
        по каждой услуге.

        Отдельно от таблицы цен: и то, и другое не зависит от диаметра,
        поэтому одно поле на услугу, а не двенадцать.
        """
        from models import Service
        from services import AuditService

        dialog = tk.Toplevel(self.frame)
        dialog.title("Расходники и время услуг")
        dialog.geometry("820x600")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(self.frame.winfo_toplevel())
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, "Расходники и время услуг",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))
        ttk.Label(content,
                  text="Себестоимость материалов вычитается из суммы наряда до расчёта зарплаты. "
                       "Время нужно для очереди и записи. От диаметра колеса не зависят.\n"
                       "Двойной клик по ячейке — изменить.",
                  font=(styles.DEFAULT_FONT, 9), foreground='#64748b',
                  wraplength=760, justify='left').pack(anchor='w', pady=(0, 12))

        tree_frame = ttk.Frame(content, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)

        tree = ttk.Treeview(tree_frame,
                            columns=('Услуга', 'Тип', 'Расходник', 'Время', 'Скидка'),
                            show='headings')
        tree.heading('Услуга', text='Услуга')
        tree.heading('Тип', text='Транспорт')
        tree.heading('Расходник', text='Расходник, руб.')
        tree.heading('Время', text='Время, мин')
        tree.heading('Скидка', text='Макс. скидка, %')
        tree.column('Услуга', width=290, anchor='w')
        tree.column('Тип', width=110, anchor='center')
        tree.column('Расходник', width=130, anchor='center')
        tree.column('Время', width=110, anchor='center')
        tree.column('Скидка', width=130, anchor='center')
        tree.pack(side='left', fill='both', expand=True)

        scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.config(yscrollcommand=scroll.set)

        type_names = {'car': 'Легковой', 'suv': 'Джип', 'truck': 'Категория С', 'all': 'Любой'}

        def load():
            for row in tree.get_children():
                tree.delete(row)
            services = self.db.query(Service).filter(
                Service.is_active == True
            ).order_by(Service.name, Service.vehicle_type).all()
            for service in services:
                limit = service.max_discount_percent
                tree.insert('', 'end', values=(
                    service.name,
                    type_names.get(service.vehicle_type, service.vehicle_type),
                    f"{service.consumable_cost or 0:.0f}",
                    f"{service.duration_minutes or 0}",
                    "без ограничений" if limit is None or limit >= 100 else f"{limit}"
                ), tags=(str(service.id),))
            return len(services)

        count = load()

        def edit_cell(event):
            if tree.identify_region(event.x, event.y) != 'cell':
                return
            column = tree.identify_column(event.x)
            selection = tree.selection()
            if not selection or column not in ('#3', '#4', '#5'):
                return

            service_id = int(tree.item(selection[0])['tags'][0])
            service = self.db.query(Service).filter(Service.id == service_id).first()
            if not service:
                return

            if column == '#3':
                title, prompt = "Себестоимость расходников", "Себестоимость материалов, руб.:"
                current, maximum = service.consumable_cost or 0, None
            elif column == '#4':
                title, prompt = "Время выполнения", "Сколько минут занимает услуга:"
                current, maximum = service.duration_minutes or 0, None
            else:
                title = "Максимальная скидка"
                prompt = ("Наибольшая скидка на эту услугу, %\n"
                          "(100 — без ограничений):")
                current, maximum = (service.max_discount_percent
                                    if service.max_discount_percent is not None else 100), 100

            value = simpledialog.askfloat(
                title, f"«{service.name}»\n\n{prompt}",
                initialvalue=current, minvalue=0, maxvalue=maximum, parent=dialog
            )
            if value is None:
                return

            try:
                if column == '#3':
                    old, new = service.consumable_cost or 0, round(float(value), 2)
                    service.consumable_cost = new
                    what = 'расходник'
                elif column == '#4':
                    old, new = service.duration_minutes or 0, int(value)
                    service.duration_minutes = new
                    what = 'время'
                else:
                    old = service.max_discount_percent if service.max_discount_percent is not None else 100
                    new = int(value)
                    service.max_discount_percent = new
                    what = 'макс. скидка'

                if old != new:
                    self.db.commit()
                    AuditService(self.db).log(
                        AuditService.PRICE_CHANGE,
                        f"«{service.name}» — {what}: {old:.0f} -> {new:.0f}",
                        entity_type='service', entity_id=service.id
                    )
                load()
            except Exception as e:
                self.db.rollback()
                messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}", parent=dialog)

        tree.bind('<Double-1>', edit_cell)

        ttk.Label(content, text=f"Услуг: {count}", font=(styles.DEFAULT_FONT, 9),
                  foreground='#64748b').pack(anchor='w', pady=(10, 0))

        styles.create_button(content, "Закрыть", dialog.destroy, 'Secondary.TButton').pack(
            fill='x', pady=(10, 0))

    def show_settings(self):
        """Настройки программы: Telegram, папка отчётов, автозакрытие смены."""
        from ui.settings_dialog import open_settings
        try:
            open_settings(self.frame, self.db)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось открыть настройки: {e}")

    def show_audit_log(self):
        """Окно с журналом действий: кто что менял и удалял."""
        from services import AuditService

        dialog = tk.Toplevel(self.frame)
        dialog.title("Журнал действий")
        dialog.geometry("900x520")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(self.frame.winfo_toplevel())
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, "Журнал действий", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))
        ttk.Label(content,
                  text="Записываются удаление нарядов, изменение цен и ставок зарплаты, "
                       "выдача шин и неудачные попытки ввода PIN-кода.",
                  font=(styles.DEFAULT_FONT, 9), foreground='#64748b',
                  wraplength=840, justify='left').pack(anchor='w', pady=(0, 12))

        tree_frame = ttk.Frame(content, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)

        tree = ttk.Treeview(tree_frame, columns=('Когда', 'Действие', 'Подробности'),
                            show='headings')
        tree.heading('Когда', text='Когда')
        tree.heading('Действие', text='Действие')
        tree.heading('Подробности', text='Подробности')
        tree.column('Когда', width=140, anchor='center')
        tree.column('Действие', width=190, anchor='w')
        tree.column('Подробности', width=490, anchor='w')
        tree.pack(side='left', fill='both', expand=True)

        scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.config(yscrollcommand=scroll.set)

        try:
            entries = AuditService(self.db).get_recent(limit=500)
            for entry in entries:
                when = entry.created_at.strftime('%d.%m.%Y %H:%M') if entry.created_at else ''
                tree.insert('', 'end', values=(
                    when,
                    AuditService.title(entry.action),
                    entry.description or ''
                ))

            summary = f"Записей: {len(entries)}" if entries else "Журнал пока пуст"
        except Exception as e:
            self.db.rollback()
            summary = f"Не удалось прочитать журнал: {e}"

        ttk.Label(content, text=summary, font=(styles.DEFAULT_FONT, 9),
                  foreground='#64748b').pack(anchor='w', pady=(10, 0))

        styles.create_button(content, "Закрыть", dialog.destroy, 'Secondary.TButton').pack(
            fill='x', pady=(10, 0))

    def show_change_pin(self):
        """Окно смены админского PIN-кода."""
        from services import AuthService, AuditService

        dialog = tk.Toplevel(self.frame)
        dialog.title("Смена PIN-кода")
        dialog.geometry("420x320")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, "Смена PIN-кода", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))

        styles.create_label(content, "Текущий PIN-код:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        old_entry = tk.Entry(content, show='●', font=styles.FONTS['normal'], justify='center')
        old_entry.pack(fill='x', pady=(0, 12))
        old_entry.focus_set()

        styles.create_label(content, "Новый PIN-код:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        new_entry = tk.Entry(content, show='●', font=styles.FONTS['normal'], justify='center')
        new_entry.pack(fill='x', pady=(0, 12))

        styles.create_label(content, "Повторите новый PIN-код:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        repeat_entry = tk.Entry(content, show='●', font=styles.FONTS['normal'], justify='center')
        repeat_entry.pack(fill='x', pady=(0, 15))

        def apply_change():
            if new_entry.get() != repeat_entry.get():
                messagebox.showerror("Ошибка", "Новый PIN-код и повтор не совпадают", parent=dialog)
                return
            try:
                AuthService(self.db).change_pin(old_entry.get(), new_entry.get())
                AuditService(self.db).log(AuditService.PIN_CHANGED, "PIN-код изменён")
                messagebox.showinfo("Готово", "PIN-код изменён", parent=dialog)
                dialog.destroy()
            except ValueError as e:
                messagebox.showerror("Ошибка", str(e), parent=dialog)
            except Exception as e:
                self.db.rollback()
                messagebox.showerror("Ошибка", f"Не удалось сменить PIN: {e}", parent=dialog)

        styles.create_button(content, "Сменить", apply_change, 'Primary.TButton').pack(fill='x')

    def show_content_screen(self):
        """Показать основной интерфейс прайс-листа"""
        # Создаем основной контейнер
        self.content_frame = ttk.Frame(self.frame, style='BG.TFrame')
        self.content_frame.pack(fill='both', expand=True)
        
        # Заголовок
        header_frame = ttk.Frame(self.content_frame, style='BG.TFrame')
        header_frame.pack(fill='x', padx=15, pady=(15, 10))
        
        styles.create_label(header_frame, "Управление прайс-листом", 'Heading.TLabel').pack(side='left')

        styles.create_button(header_frame, "Журнал действий",
                             self.show_audit_log, 'Secondary.TButton').pack(side='right')
        styles.create_button(header_frame, "Настройки",
                             self.show_settings, 'Secondary.TButton').pack(
                                 side='right', padx=(0, 5))
        styles.create_button(header_frame, "Расходники и время",
                             self.show_consumables_and_duration, 'Secondary.TButton').pack(
                                 side='right', padx=(0, 5))
        styles.create_button(header_frame, "Сменить PIN",
                             self.show_change_pin, 'Secondary.TButton').pack(side='right', padx=(0, 5))

        # Пока стоит код по умолчанию, предупреждаем владельца
        try:
            from services import AuthService
            if AuthService(self.db).is_default_pin():
                warning = ttk.Label(
                    self.content_frame,
                    text="⚠ Установлен PIN-код по умолчанию (0000). "
                         "Смените его — сейчас цены и ставки зарплаты может изменить кто угодно.",
                    font=(styles.DEFAULT_FONT, 9), foreground='#dc2626', wraplength=1100
                )
                warning.pack(anchor='w', padx=15, pady=(0, 5))
        except Exception as e:
            log.error(f"Не удалось проверить PIN: {e}")


        # Кнопки
        btn_frame = ttk.Frame(self.content_frame, style='BG.TFrame')
        btn_frame.pack(fill='x', padx=15, pady=(0, 10))
        
        styles.create_button(btn_frame, "Легковой", lambda: self.filter_by_vehicle_type('car'), 'Service.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(btn_frame, "Джип/Кроссовер", lambda: self.filter_by_vehicle_type('suv'), 'Service.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(btn_frame, "Категория С", lambda: self.filter_by_vehicle_type('truck'), 'Service.TButton').pack(side='left', padx=(0, 5))
        
        styles.create_button(btn_frame, "Сохранить изменения", self.save_changes, 'Success.TButton').pack(side='right')
        
        # Карточка с ценами на хранение
        storage_card = styles.create_card_frame(self.content_frame)
        storage_card.pack(fill='x', padx=15, pady=(0, 15))
        
        storage_inner = ttk.Frame(storage_card, style='White.TFrame')
        storage_inner.pack(fill='both', expand=True, padx=15, pady=15)
        
        storage_title = styles.create_label(storage_inner, "Цены на хранение шин", 'CardHeading.TLabel')
        storage_title.pack(anchor='w', pady=(0, 10))
        
        # Таблица цен на хранение
        storage_grid = ttk.Frame(storage_inner, style='White.TFrame')
        storage_grid.pack(fill='x')
        
        # Создаём поля для ввода - индивидуальная цена для каждого размера
        self.storage_price_vars = {}
        
        # Индивидуальные размеры с дефолтными ценами
        storage_sizes = [
            ('storage_price_r13', 'R13', 4000),
            ('storage_price_r14', 'R14', 4000),
            ('storage_price_r15', 'R15', 4000),
            ('storage_price_r16', 'R16', 5000),
            ('storage_price_r17', 'R17', 5000),
            ('storage_price_r18', 'R18', 5000),
            ('storage_price_r19', 'R19', 6000),
            ('storage_price_r20', 'R20', 6000),
            ('storage_price_r21', 'R21', 8000),
            ('storage_price_r22', 'R22', 8000),
            ('storage_price_r23', 'R23', 8000),
            ('storage_price_r24', 'R24', 8000),
        ]
        
        # Размещаем в 4 колонки для компактности
        columns_container = ttk.Frame(storage_grid, style='White.TFrame')
        columns_container.pack(fill='x')
        
        # Создаём 4 колонки
        column_frames = []
        for i in range(4):
            col_frame = ttk.Frame(columns_container, style='White.TFrame')
            col_frame.pack(side='left', fill='y', expand=True, padx=10)
            column_frames.append(col_frame)
        
        for idx, (key, label, default) in enumerate(storage_sizes):
            # Получаем текущую цену из БД
            setting = self.db.query(Settings).filter(Settings.key == key).first()
            current_price = float(setting.value) if setting else default
            
            # Размещаем в соответствующей колонке
            col_idx = idx // 3  # По 3 элемента в каждой колонке
            row_frame = ttk.Frame(column_frames[col_idx], style='White.TFrame')
            row_frame.pack(fill='x', pady=5)
            
            label_widget = styles.create_label(row_frame, f"{label}:", 'Card.TLabel')
            label_widget.pack(side='left', padx=(0, 10))
            
            var = tk.StringVar(value=str(int(current_price)))
            self.storage_price_vars[key] = var
            
            entry = ttk.Entry(row_frame, textvariable=var, width=8, font=(styles.DEFAULT_FONT, 12))
            entry.pack(side='left', padx=(0, 5))
            
            styles.create_label(row_frame, "₽", 'Card.TLabel').pack(side='left')
        
        # Карточка с таблицей услуг
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
            'Ремонт кордовой заплаткой',
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
        log.debug(f"DOUBLE CLICK DETECTED at x={event.x}, y={event.y}")
        
        # Получаем элемент и колонку
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        
        log.debug(f"Item: {item}, Column: {column}")
        
        if not item or column == '#1':  # Не редактируем название услуги
            log.debug(f"SKIP: No item or column is #1")
            return
        
        # Определяем индекс колонки (R13=1, R14=2, и т.д.)
        column_index = int(column.replace('#', '')) - 1
        
        log.debug(f"Column index: {column_index}")
        
        if column_index < 1:  # Не редактируем название
            log.debug(f"SKIP: Column index < 1")
            return
        
        # Получаем текущее значение
        current_value = self.tree.item(item)['values'][column_index]
        
        log.debug(f"Current value: {current_value}")
        
        # Запрашиваем новое значение
        new_value = simpledialog.askfloat(
            "Изменить цену",
            f"Введите новую цену:\n(текущая: {current_value} руб.)",
            initialvalue=current_value,
            minvalue=0,
            parent=self.frame.winfo_toplevel()
        )
        
        log.debug(f"New value: {new_value}")
        
        if new_value is not None:
            # Обновляем в таблице
            values = list(self.tree.item(item)['values'])
            values[column_index] = int(new_value)
            self.tree.item(item, values=values)
            
            # Помечаем как измененное
            current_tags = self.tree.item(item)['tags']
            log.debug(f"Current tags: {current_tags}, type: {type(current_tags)}")
            
            # Конвертируем в список для универсальности
            if isinstance(current_tags, str):
                new_tags = [current_tags, 'modified']
            elif isinstance(current_tags, tuple):
                new_tags = list(current_tags) + ['modified']
            else:
                new_tags = list(current_tags) + ['modified']
            
            self.tree.item(item, tags=tuple(new_tags))
            log.debug(f"New tags: {self.tree.item(item)['tags']}")
            log.debug(f"Price updated to {int(new_value)}")
    
    def save_changes(self):
        """Сохранить изменения в БД"""
        log.debug("=== SAVE CHANGES НАЧАЛО ===")
        # Копим описания изменений для журнала действий
        price_changes = []
        all_items = self.tree.get_children()
        log.debug(f"Всего элементов в таблице: {len(all_items)}")
        
        for item in all_items:
            item_tags = self.tree.item(item)['tags']
            log.debug(f"Item tags: {item_tags}, 'modified' in tags: {'modified' in item_tags}")
        
        modified_items = [item for item in self.tree.get_children() if 'modified' in self.tree.item(item)['tags']]
        total_changes = len(modified_items)
        log.debug(f"Найдено измененных услуг: {total_changes}")
        
        # Проверяем изменения в ценах на хранение
        storage_changes = 0
        for key, var in self.storage_price_vars.items():
            try:
                new_price = float(var.get())
                setting = self.db.query(Settings).filter(Settings.key == key).first()
                if setting:
                    if float(setting.value) != new_price:
                        storage_changes += 1
                else:
                    storage_changes += 1
            except ValueError:
                pass
        
        total_changes += storage_changes
        
        if total_changes == 0:
            messagebox.showinfo("Информация", "Нет изменений для сохранения")
            return
        
        try:
            # Сохраняем цены на хранение
            for key, var in self.storage_price_vars.items():
                try:
                    new_price = float(var.get())
                    setting = self.db.query(Settings).filter(Settings.key == key).first()
                    if setting:
                        if float(setting.value) != new_price:
                            size = key.replace('storage_price_', '').upper()
                            price_changes.append(
                                f"Хранение {size}: {float(setting.value):.0f} -> {new_price:.0f}")
                        setting.value = str(int(new_price))
                    else:
                        new_setting = Settings(key=key, value=str(int(new_price)))
                        self.db.add(new_setting)
                except ValueError:
                    messagebox.showerror("Ошибка", f"Неверное значение цены для {key}")
                    return
            
            # Сохраняем изменённые услуги
            for item in modified_items:
                values = self.tree.item(item)['values']
                tags = self.tree.item(item)['tags']
                log.debug(f"Processing item with tags: {tags}, type: {type(tags)}")
                log.debug(f"Values: {values}")
                
                # Tags может быть списком [69, 'modified'], берем первый элемент
                service_id = int(tags[0])
                log.debug(f"Service ID: {service_id}")
                
                service = self.db.query(Service).filter(Service.id == service_id).first()
                log.debug(f"Found service: {service.name if service else 'None'}")
                
                if service:
                    # Запоминаем прежние цены, чтобы записать в журнал,
                    # что именно поменялось
                    price_fields = [f'price_r{n}' for n in range(13, 25)]
                    old_prices = {f: getattr(service, f) for f in price_fields}

                    if self.current_vehicle_type == 'truck':
                        # Для грузовых сохраняем только R15-R19
                        service.price_r15 = int(float(values[1]))
                        service.price_r16 = int(float(values[2]))
                        service.price_r17 = int(float(values[3]))
                        service.price_r18 = int(float(values[4]))
                        service.price_r19 = int(float(values[5]))
                    else:
                        # Для легковых и джипов все радиусы
                        service.price_r13 = int(float(values[1]))
                        service.price_r14 = int(float(values[2]))
                        service.price_r15 = int(float(values[3]))
                        service.price_r16 = int(float(values[4]))
                        service.price_r17 = int(float(values[5]))
                        service.price_r18 = int(float(values[6]))
                        service.price_r19 = int(float(values[7]))
                        service.price_r20 = int(float(values[8]))
                        service.price_r21 = int(float(values[9]))
                        service.price_r22 = int(float(values[10]))
                        service.price_r23 = int(float(values[11]))
                        service.price_r24 = int(float(values[12]))

                    changes = [
                        f"{field.replace('price_', '').upper()}: {old_prices[field]:.0f} -> {getattr(service, field):.0f}"
                        for field in price_fields
                        if old_prices[field] != getattr(service, field)
                    ]
                    if changes:
                        price_changes.append(f"«{service.name}» — {', '.join(changes)}")

            self.db.commit()

            # Записываем в журнал, что именно изменилось
            from services import AuditService
            audit = AuditService(self.db)
            for line in price_changes:
                audit.log(AuditService.PRICE_CHANGE, line,
                          entity_type='service', commit=False)
            if price_changes:
                self.db.commit()

            messagebox.showinfo("Успех", f"Сохранено изменений: {total_changes}")
            
            # Перезагружаем данные
            self.load_services()
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            log.error(f"ERROR: {error_details}")
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить изменения:\n{str(e)}")
