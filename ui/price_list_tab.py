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
        
        # Заголовок
        header_frame = ttk.Frame(self.frame, style='BG.TFrame')
        header_frame.pack(fill='x', padx=15, pady=(15, 10))
        
        styles.create_label(header_frame, "Управление прайс-листом", 'Heading.TLabel').pack(side='left')
        
        # Кнопки
        btn_frame = ttk.Frame(self.frame, style='BG.TFrame')
        btn_frame.pack(fill='x', padx=15, pady=(0, 10))
        
        styles.create_button(btn_frame, "Легковой", lambda: self.filter_by_vehicle_type('car'), 'Service.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(btn_frame, "Джип/Кроссовер", lambda: self.filter_by_vehicle_type('suv'), 'Service.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(btn_frame, "Категория С", lambda: self.filter_by_vehicle_type('truck'), 'Service.TButton').pack(side='left', padx=(0, 5))
        
        styles.create_button(btn_frame, "💾 Сохранить изменения", self.save_changes, 'Success.TButton').pack(side='right')
        
        # Карточка с таблицей
        card = styles.create_card_frame(self.frame)
        card.pack(fill='both', expand=True, padx=15, pady=(0, 15))
        
        card_inner = ttk.Frame(card, style='White.TFrame')
        card_inner.pack(fill='both', expand=True, padx=15, pady=15)
        
        # Таблица с прокруткой
        tree_frame = ttk.Frame(card_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side='right', fill='y')
        
        # Колонки: Услуга, R13-R24
        columns = ['Услуга', 'R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22', 'R23', 'R24']
        
        self.tree = ttk.Treeview(tree_frame, columns=columns, show='headings', yscrollcommand=scrollbar.set, height=20)
        scrollbar.config(command=self.tree.yview)
        
        # Настройка колонок
        self.tree.column('Услуга', width=250, anchor='w')
        self.tree.heading('Услуга', text='Услуга')
        
        for col in columns[1:]:
            self.tree.column(col, width=80, anchor='center')
            self.tree.heading(col, text=col)
        
        self.tree.pack(fill='both', expand=True)
        
        # Двойной клик для редактирования
        self.tree.bind('<Double-1>', self.on_double_click)
        
        # Загружаем данные
        self.load_services()
    
    def filter_by_vehicle_type(self, vehicle_type):
        """Фильтр по типу транспорта"""
        self.current_vehicle_type = vehicle_type
        self.load_services()
    
    def load_services(self):
        """Загрузить услуги из БД"""
        # Очищаем таблицу
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Загружаем услуги: конкретного типа + универсальные ('all')
        services = self.db.query(Service).filter(
            (Service.vehicle_type == self.current_vehicle_type) | (Service.vehicle_type == 'all')
        ).order_by(Service.name).all()
        
        if not services:
            messagebox.showwarning("Предупреждение", f"Нет услуг для типа транспорта: {self.current_vehicle_type}")
            return
        
        for service in services:
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
        # Получаем элемент и колонку
        item = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        
        if not item or column == '#1':  # Не редактируем название услуги
            return
        
        # Проверяем PIN
        if not self.check_admin_pin():
            return
        
        # Определяем индекс колонки (R13=1, R14=2, и т.д.)
        column_index = int(column.replace('#', '')) - 1
        
        if column_index < 1:  # Не редактируем название
            return
        
        # Получаем текущее значение
        current_value = self.tree.item(item)['values'][column_index]
        
        # Запрашиваем новое значение
        new_value = simpledialog.askfloat(
            "Изменить цену",
            f"Введите новую цену:\n(текущая: {current_value} руб.)",
            initialvalue=current_value,
            minvalue=0
        )
        
        if new_value is not None:
            # Обновляем в таблице
            values = list(self.tree.item(item)['values'])
            values[column_index] = int(new_value)
            self.tree.item(item, values=values)
            
            # Помечаем как измененное
            self.tree.item(item, tags=self.tree.item(item)['tags'] + ('modified',))
    
    def check_admin_pin(self):
        """Проверка PIN-кода администратора"""
        settings = self.db.query(Settings).filter(Settings.key == 'admin_pin').first()
        stored_pin = settings.value if settings else '0000'
        
        pin = simpledialog.askstring("Требуется PIN-код", "Введите PIN администратора:", show='*')
        
        if pin != stored_pin:
            messagebox.showerror("Ошибка", "Неверный PIN-код!")
            return False
        
        return True
    
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
