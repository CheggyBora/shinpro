import tkinter as tk
from tkinter import messagebox
from ui import MainWindow
from config import init_db
from init_data import initialize_data

if __name__ == "__main__":
    try:
        init_db()
        initialize_data()
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
    
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
