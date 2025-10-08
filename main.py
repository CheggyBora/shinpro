import tkinter as tk
from ui import MainWindow
from config import init_db
from init_data import initialize_data

if __name__ == "__main__":
    init_db()
    initialize_data()
    
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
