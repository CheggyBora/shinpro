import tkinter as tk
from tkinter import messagebox
from ui import MainWindow
from config import init_db
from init_data import initialize_data
import os

if __name__ == "__main__":
    # Сохраняем переменные окружения X-сервера для открытия PDF
    display = os.environ.get('DISPLAY', '')
    xauthority = os.environ.get('XAUTHORITY', '')
    print(f"X Server: DISPLAY={display}, XAUTHORITY={xauthority}")
    
    # Сохраняем в файл для использования в subprocess
    with open('/tmp/x_display.env', 'w') as f:
        f.write(f"DISPLAY={display}\n")
        f.write(f"XAUTHORITY={xauthority}\n")
    
    try:
        init_db()
        initialize_data()
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
    
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
