import tkinter as tk
from tkinter import ttk

COLORS = {
    'primary': '#2563eb',
    'primary_hover': '#1d4ed8',
    'secondary': '#64748b',
    'success': '#10b981',
    'danger': '#ef4444',
    'warning': '#f59e0b',
    'bg': '#f8fafc',
    'bg_card': '#ffffff',
    'text': '#1e293b',
    'text_secondary': '#64748b',
    'border': '#e2e8f0',
    'hover': '#f1f5f9'
}

FONTS = {
    'heading': ('Segoe UI', 14, 'bold'),
    'subheading': ('Segoe UI', 12, 'bold'),
    'normal': ('Segoe UI', 10),
    'small': ('Segoe UI', 9),
    'button': ('Segoe UI', 10, 'bold')
}

def apply_modern_styles(root):
    style = ttk.Style(root)
    
    root.configure(bg=COLORS['bg'])
    
    style.configure('TNotebook', background=COLORS['bg'], borderwidth=0)
    style.configure('TNotebook.Tab', 
                   padding=[20, 10], 
                   font=FONTS['normal'],
                   background=COLORS['bg_card'])
    style.map('TNotebook.Tab',
             background=[('selected', COLORS['primary'])],
             foreground=[('selected', 'white'), ('!selected', COLORS['text'])])
    
    style.configure('Card.TFrame', background=COLORS['bg_card'], relief='flat', borderwidth=1)
    style.configure('TFrame', background=COLORS['bg'])
    style.configure('BG.TFrame', background=COLORS['bg'])
    style.configure('White.TFrame', background=COLORS['bg_card'])
    
    style.configure('TLabel', background=COLORS['bg'], foreground=COLORS['text'], font=FONTS['normal'])
    style.configure('Heading.TLabel', font=FONTS['heading'], foreground=COLORS['text'])
    style.configure('Subheading.TLabel', font=FONTS['subheading'], foreground=COLORS['text'])
    style.configure('Card.TLabel', background=COLORS['bg_card'], foreground=COLORS['text'], font=FONTS['normal'])
    style.configure('CardHeading.TLabel', background=COLORS['bg_card'], font=FONTS['subheading'], foreground=COLORS['text'])
    
    style.configure('Primary.TButton', 
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['primary'],
                   foreground='white')
    style.map('Primary.TButton',
             background=[('active', COLORS['primary_hover'])])
    
    style.configure('Secondary.TButton',
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['secondary'],
                   foreground='white')
    
    style.configure('Success.TButton',
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['success'],
                   foreground='white')
    
    style.configure('Danger.TButton',
                   font=FONTS['button'],
                   padding=[15, 8],
                   background=COLORS['danger'],
                   foreground='white')
    
    style.configure('Service.TButton',
                   font=('Segoe UI', 9),
                   padding=[6, 4],
                   background=COLORS['primary'],
                   foreground='white',
                   relief='flat',
                   borderwidth=0)
    style.map('Service.TButton',
             background=[('active', COLORS['primary_hover'])])
    
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
                   foreground='white',
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
