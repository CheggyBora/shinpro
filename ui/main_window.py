import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from ui.employees_tab import EmployeesTab
from ui.orders_tab import OrdersTab
from ui.history_tab import HistoryTab
from ui.tire_storage_tab import TireStorageTab
from ui.price_list_tab import PriceListTab
from config import get_db
from models import Settings
import styles

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Система учёта шиномонтажа")
        self.root.geometry("1280x800")
        
        styles.apply_modern_styles(self.root)
        
        self.db = get_db()
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.employees_tab = EmployeesTab(self.notebook, self.db)
        self.orders_tab = OrdersTab(self.notebook, self.db)
        self.history_tab = HistoryTab(self.notebook, self.db)
        self.tire_storage_tab = TireStorageTab(self.notebook, self.db)
        self.price_list_tab = PriceListTab(self.notebook, self.db)
        
        self.notebook.add(self.employees_tab.frame, text='  Сотрудники  ')
        self.notebook.add(self.orders_tab.frame, text='  Наряды  ')
        self.notebook.add(self.history_tab.frame, text='  История автомобиля  ')
        self.notebook.add(self.tire_storage_tab.frame, text='  Хранение шин  ')
        self.notebook.add(self.price_list_tab.frame, text='  💰 Прайс-лист  ')
        
        # Запоминаем индекс вкладки "Прайс-лист"
        self.price_list_tab_index = 4
        self.previous_tab_index = 0
        
        # Привязываем обработчик события переключения вкладок
        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)
    
    def on_tab_changed(self, event):
        """Обработчик переключения вкладок - проверяет PIN для прайс-листа"""
        current_tab_index = self.notebook.index(self.notebook.select())
        
        # Если переключаемся на вкладку "Прайс-лист"
        if current_tab_index == self.price_list_tab_index:
            # Проверяем PIN
            if not self.check_admin_pin():
                # Если PIN неверный - возвращаемся на предыдущую вкладку
                self.notebook.select(self.previous_tab_index)
                return
        
        # Запоминаем текущую вкладку как предыдущую
        self.previous_tab_index = current_tab_index
    
    def check_admin_pin(self):
        """Проверка PIN-кода администратора"""
        settings = self.db.query(Settings).filter(Settings.key == 'admin_pin').first()
        stored_pin = settings.value if settings else '0000'
        
        pin = simpledialog.askstring("Требуется PIN-код администратора", "Введите PIN для доступа к прайс-листу:", show='*')
        
        if pin != stored_pin:
            messagebox.showerror("Ошибка", "Неверный PIN-код!\nДоступ к прайс-листу запрещен.")
            return False
        
        return True
