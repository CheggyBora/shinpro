import tkinter as tk
from tkinter import ttk
from ui.employees_tab import EmployeesTab
from ui.orders_tab import OrdersTab
from ui.history_tab import HistoryTab
from config import get_db

class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.title("Система учёта шиномонтажа")
        self.root.geometry("1280x800")
        
        self.db = get_db()
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True)
        
        self.employees_tab = EmployeesTab(self.notebook, self.db)
        self.orders_tab = OrdersTab(self.notebook, self.db)
        self.history_tab = HistoryTab(self.notebook, self.db)
        
        self.notebook.add(self.employees_tab.frame, text='Сотрудники')
        self.notebook.add(self.orders_tab.frame, text='Наряды')
        self.notebook.add(self.history_tab.frame, text='История автомобиля')
