import tkinter as tk
from tkinter import ttk
import platform
import os
import sys

# Определение шрифта в зависимости от платформы
def get_default_font_name():
    """Возвращает имя подходящего шрифта для текущей платформы с поддержкой кириллицы"""
    system = platform.system()
    
    if system == 'Windows':
        # На Windows используем Arial
        return 'Arial'
    else:
        # На Linux/Mac будет использоваться DejaVu Sans (регистрируется в main_window.py)
        return 'DejaVu Sans'

def register_dejavu_font():
    """Регистрирует DejaVu Sans шрифт для Tkinter (вызывать ПОСЛЕ создания root window)"""
    system = platform.system()
    
    if system == 'Windows':
        return  # На Windows используем системный Arial
    
    try:
        from tkinter import font as tkfont
        
        # Определяем путь к шрифту
        if getattr(sys, 'frozen', False):
            # Для PyInstaller EXE
            base_path = sys._MEIPASS
        else:
            # Для обычного запуска - styles.py находится в корневой директории
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        font_path = os.path.join(base_path, "fonts", "DejaVuSans.ttf")
        
        if os.path.exists(font_path):
            # Проверяем, что шрифт не зарегистрирован
            if 'DejaVu Sans' not in tkfont.families():
                print(f"✓ Регистрация DejaVu Sans шрифта для GUI: {font_path}")
            return True
        else:
            print(f"✗ ВНИМАНИЕ: Файл шрифта не найден: {font_path}")
            return False
    except Exception as e:
        print(f"✗ Ошибка при регистрации шрифта: {e}")
        return False

# Получаем имя шрифта (регистрация будет позже в main_window.py)
DEFAULT_FONT = get_default_font_name()

COLORS = {
    'primary': '#2563eb',
    'primary_hover': '#1d4ed8',
    'primary_dark': '#1e40af',
    'secondary': '#64748b',
    'success': '#10b981',
    'danger': '#ef4444',
    'warning': '#f59e0b',
    'bg': '#f8fafc',
    'bg_card': '#ffffff',
    'text': '#1e293b',
    'text_secondary': '#64748b',
    'gray': '#64748b',
    'border': '#e2e8f0',
    'hover': '#f1f5f9'
}

FONTS = {
    'heading': (DEFAULT_FONT, 14, 'bold'),
    'subheading': (DEFAULT_FONT, 12, 'bold'),
    'normal': (DEFAULT_FONT, 10),
    'small': (DEFAULT_FONT, 9),
    'button': (DEFAULT_FONT, 10, 'bold')
}

def apply_modern_styles(root):
    style = ttk.Style(root)
    
    root.configure(bg=COLORS['bg'])
    
    style.configure('TNotebook', background=COLORS['bg'], borderwidth=0)
    style.configure('TNotebook.Tab', 
                   padding=[20, 10], 
                   font=FONTS['normal'],
                   background='#f5e6d3',
                   foreground='black')
    style.map('TNotebook.Tab',
             background=[('selected', '#f5e6d3')],
             foreground=[('selected', 'black'), ('!selected', 'black')])
    
    style.configure('Card.TFrame', background=COLORS['bg_card'], relief='flat', borderwidth=1)
    style.configure('TFrame', background=COLORS['bg'])
    style.configure('BG.TFrame', background=COLORS['bg'])
    style.configure('White.TFrame', background=COLORS['bg_card'])
    
    style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['text'], font=FONTS['normal'])
    style.configure('Heading.TLabel', font=FONTS['heading'], foreground=COLORS['text'])
    style.configure('Subheading.TLabel', font=FONTS['subheading'], foreground=COLORS['text'])
    style.configure('Card.TLabel', background=COLORS['bg_card'], foreground=COLORS['text'], font=FONTS['normal'])
    style.configure('CardHeading.TLabel', background=COLORS['bg_card'], font=FONTS['subheading'], foreground=COLORS['text'])
    style.configure('CardTitle.TLabel', background=COLORS['bg_card'], font=(DEFAULT_FONT, 13, 'bold'), foreground=COLORS['text'])
    style.configure('CardValue.TLabel', background=COLORS['bg_card'], font=(DEFAULT_FONT, 24, 'bold'), foreground=COLORS['primary'])
    style.configure('ServiceHeading.TLabel', background='#f5e6d3', foreground='black', font=FONTS['normal'], padding=[5, 3])
    
    style.configure('Primary.TButton', 
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['primary'],
                   foreground='black')
    style.map('Primary.TButton',
             background=[('active', COLORS['primary_hover'])])
    
    style.configure('Secondary.TButton',
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['secondary'],
                   foreground='black')
    
    style.configure('Success.TButton',
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['success'],
                   foreground='black')
    
    style.configure('Danger.TButton',
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['danger'],
                   foreground='black')
    
    style.configure('Service.TButton',
                   font=(DEFAULT_FONT, 10, 'bold'),
                   padding=[6, 4],
                   background='#f5e6d3',
                   foreground='#1e293b',
                   relief='flat',
                   borderwidth=0)
    style.map('Service.TButton',
             background=[('active', '#e8d4ba')])
    
    style.configure('TEntry', 
                   fieldbackground=COLORS['bg_card'],
                   font=FONTS['normal'],
                   borderwidth=1,
                   relief='solid')
    
    style.configure('Treeview',
                   background=COLORS['bg_card'],
                   foreground=COLORS['text'],
                   fieldbackground=COLORS['bg_card'],
                   font=FONTS['normal'],
                   rowheight=30,
                   borderwidth=0)
    style.configure('Treeview.Heading',
                   background=COLORS['primary'],
                   foreground='black',
                   font=FONTS['subheading'],
                   relief='flat')
    style.map('Treeview',
             background=[('selected', COLORS['primary'])],
             foreground=[('selected', 'white')])
    
    style.configure('TCombobox',
                   fieldbackground=COLORS['bg_card'],
                   font=FONTS['normal'],
                   arrowsize=15)
    
    style.configure('TScrollbar',
                   background=COLORS['border'],
                   troughcolor=COLORS['bg'],
                   borderwidth=0,
                   arrowsize=14)

def create_card_frame(parent):
    frame = ttk.Frame(parent, style='Card.TFrame')
    frame.configure(relief='solid', borderwidth=1)
    return frame

def create_button(parent, text, command, style='Primary.TButton'):
    return ttk.Button(parent, text=text, command=command, style=style)

def create_label(parent, text, style='TLabel'):
    return ttk.Label(parent, text=text, style=style)

def create_entry(parent, width=20):
    entry = ttk.Entry(parent, width=width)
    entry.configure(font=FONTS['normal'])
    return entry

def center_window(window, parent=None):
    """Центрирует окно на экране или относительно родительского окна"""
    window.update_idletasks()
    
    if parent:
        # Центрируем относительно родительского окна
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        window_width = window.winfo_width()
        window_height = window.winfo_height()
        
        x = parent_x + (parent_width - window_width) // 2
        y = parent_y + (parent_height - window_height) // 2
    else:
        # Центрируем на экране
        window_width = window.winfo_width()
        window_height = window.winfo_height()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
    
    window.geometry(f'+{x}+{y}')
