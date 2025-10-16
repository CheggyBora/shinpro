import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from ui.employees_tab import EmployeesTab
from ui.orders_tab import OrdersTab
from ui.history_tab import HistoryTab
from ui.tire_storage_tab import TireStorageTab
from ui.price_list_tab import PriceListTab
from ui.statistics_tab import StatisticsTab
from config import get_db
from models import Settings
import styles

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Система учёта шиномонтажа")
        self.root.geometry("1280x800")
        
        styles.apply_modern_styles(self.root)
        
        # Регистрируем DejaVu Sans шрифт для кириллицы на Linux
        styles.register_dejavu_font()
        
        self.db = get_db()
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.employees_tab = EmployeesTab(self.notebook, self.db)
        self.orders_tab = OrdersTab(self.notebook, self.db)
        self.history_tab = HistoryTab(self.notebook, self.db)
        self.tire_storage_tab = TireStorageTab(self.notebook, self.db)
        self.statistics_tab = StatisticsTab(self.notebook, self.db)
        self.price_list_tab = PriceListTab(self.notebook, self.db)
        
        self.notebook.add(self.employees_tab.frame, text='  Сотрудники  ')
        self.notebook.add(self.orders_tab.frame, text='  Наряды  ')
        self.notebook.add(self.history_tab.frame, text='  История автомобиля  ')
        self.notebook.add(self.tire_storage_tab.frame, text='  Хранение шин  ')
        self.notebook.add(self.statistics_tab, text='  📊 Отчёты  ')
        self.notebook.add(self.price_list_tab.frame, text='  💰 Прайс-лист  ')
