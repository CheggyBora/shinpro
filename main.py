import tkinter as tk
from tkinter import messagebox
from ui import MainWindow
from config import init_db
from init_data import initialize_data
import os

if __name__ == "__main__":
    # Сохраняем переменные окружения X-сервера для открытия PDF (только для Linux/Replit)
    import platform
    if platform.system() != 'Windows':
        display = os.environ.get('DISPLAY', '')
        xauthority = os.environ.get('XAUTHORITY', '')
        print(f"X Server: DISPLAY={display}, XAUTHORITY={xauthority}")
        
        # Сохраняем в файл для использования в subprocess
        try:
            with open('/tmp/x_display.env', 'w') as f:
                f.write(f"DISPLAY={display}\n")
                f.write(f"XAUTHORITY={xauthority}\n")
        except:
            pass  # Не критично, если не удалось
    
    try:
        init_db()
        initialize_data()
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
    
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
