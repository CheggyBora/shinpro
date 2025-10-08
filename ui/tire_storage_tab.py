import tkinter as tk
from tkinter import ttk, messagebox
from services.tire_storage_service import TireStorageService
from datetime import datetime
import styles
import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

class TireStorageTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = TireStorageService()
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        
        notebook = ttk.Notebook(self.frame)
        notebook.pack(fill='both', expand=True, padx=15, pady=15)
        
        accept_frame = ttk.Frame(notebook, style='BG.TFrame')
        release_frame = ttk.Frame(notebook, style='BG.TFrame')
        
        notebook.add(accept_frame, text='Приём на хранение')
        notebook.add(release_frame, text='Выдача с хранения')
        
        self.setup_accept_tab(accept_frame)
        self.setup_release_tab(release_frame)
    
    def setup_accept_tab(self, parent):
        card = styles.create_card_frame(parent)
        card.pack(fill='both', expand=True, padx=15, pady=15)
        
        card_inner = ttk.Frame(card, style='White.TFrame')
        card_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(card_inner, "Приём шин на хранение", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        form_frame = ttk.Frame(card_inner, style='White.TFrame')
        form_frame.pack(fill='x', pady=5)
        
        row1 = ttk.Frame(form_frame, style='White.TFrame')
        row1.pack(fill='x', pady=5)
        styles.create_label(row1, "Номер автомобиля:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.car_number_entry = styles.create_entry(row1, width=20)
        self.car_number_entry.pack(side='left', padx=(0, 20))
        
        styles.create_label(row1, "Тип хранения:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.storage_type_var = tk.StringVar(value='Шины')
        storage_combo = ttk.Combobox(row1, textvariable=self.storage_type_var, 
                                     values=['Шины', 'Шины с дисками'], 
                                     state='readonly', width=18, font=styles.FONTS['normal'])
        storage_combo.pack(side='left')
        
        row2 = ttk.Frame(form_frame, style='White.TFrame')
        row2.pack(fill='x', pady=5)
        styles.create_label(row2, "Диаметр:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.diameter_var = tk.StringVar(value='R16')
        diameter_values = [f'R{i}' for i in range(13, 25)]
        diameter_combo = ttk.Combobox(row2, textvariable=self.diameter_var, 
                                      values=diameter_values, 
                                      state='readonly', width=10, font=styles.FONTS['normal'])
        diameter_combo.pack(side='left', padx=(0, 20))
        diameter_combo.bind('<<ComboboxSelected>>', self.update_price)
        
        styles.create_label(row2, "Марка шины:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.brand_entry = styles.create_entry(row2, width=30)
        self.brand_entry.pack(side='left')
        
        row3 = ttk.Frame(form_frame, style='White.TFrame')
        row3.pack(fill='x', pady=5)
        styles.create_label(row3, "Повреждения:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.damage_entry = styles.create_entry(row3, width=50)
        self.damage_entry.pack(side='left')
        
        row4 = ttk.Frame(form_frame, style='White.TFrame')
        row4.pack(fill='x', pady=5)
        styles.create_label(row4, "Износ шины:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.wear_entry = styles.create_entry(row4, width=30)
        self.wear_entry.pack(side='left')
        
        price_frame = ttk.Frame(card_inner, style='White.TFrame')
        price_frame.pack(fill='x', pady=15)
        styles.create_label(price_frame, "Цена хранения:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.price_label = styles.create_label(price_frame, "5000 ₽", 'CardHeading.TLabel')
        self.price_label.pack(side='left')
        
        btn_frame = ttk.Frame(card_inner, style='White.TFrame')
        btn_frame.pack(fill='x', pady=10)
        styles.create_button(btn_frame, "Принять на хранение и печать чека", 
                           self.accept_storage, 'Primary.TButton').pack(side='left')
    
    def setup_release_tab(self, parent):
        card = styles.create_card_frame(parent)
        card.pack(fill='both', expand=True, padx=15, pady=15)
        
        card_inner = ttk.Frame(card, style='White.TFrame')
        card_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(card_inner, "Выдача шин с хранения", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        search_frame = ttk.Frame(card_inner, style='White.TFrame')
        search_frame.pack(fill='x', pady=5)
        styles.create_label(search_frame, "Номер автомобиля:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.search_car_entry = styles.create_entry(search_frame, width=20)
        self.search_car_entry.pack(side='left', padx=(0, 10))
        styles.create_button(search_frame, "Найти", self.search_storage, 'Primary.TButton').pack(side='left')
        
        styles.create_label(card_inner, "Комплекты на хранении:", 'Card.TLabel').pack(anchor='w', pady=(15, 5))
        
        tree_frame = ttk.Frame(card_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True, pady=5)
        
        self.storage_tree = ttk.Treeview(tree_frame, 
                                         columns=('ID', 'Номер авто', 'Тип', 'Диаметр', 'Марка', 'Цена', 'Дата приёма'), 
                                         show='headings', height=10)
        self.storage_tree.heading('ID', text='№')
        self.storage_tree.heading('Номер авто', text='Номер авто')
        self.storage_tree.heading('Тип', text='Тип')
        self.storage_tree.heading('Диаметр', text='Диаметр')
        self.storage_tree.heading('Марка', text='Марка')
        self.storage_tree.heading('Цена', text='Цена')
        self.storage_tree.heading('Дата приёма', text='Дата приёма')
        
        self.storage_tree.column('ID', width=50)
        self.storage_tree.column('Номер авто', width=100)
        self.storage_tree.column('Тип', width=150)
        self.storage_tree.column('Диаметр', width=80)
        self.storage_tree.column('Марка', width=150)
        self.storage_tree.column('Цена', width=100)
        self.storage_tree.column('Дата приёма', width=150)
        
        self.storage_tree.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.storage_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.storage_tree.config(yscrollcommand=scrollbar.set)
        
        btn_frame = ttk.Frame(card_inner, style='White.TFrame')
        btn_frame.pack(fill='x', pady=10)
        styles.create_button(btn_frame, "Выдать комплект", 
                           self.release_storage, 'Success.TButton').pack(side='left')
    
    def update_price(self, event=None):
        diameter = self.diameter_var.get()
        price = self.service.calculate_price(diameter)
        self.price_label.config(text=f"{int(price)} ₽")
    
    def accept_storage(self):
        car_number = self.car_number_entry.get().strip()
        storage_type = self.storage_type_var.get()
        diameter = self.diameter_var.get()
        brand = self.brand_entry.get().strip()
        damage = self.damage_entry.get().strip()
        wear = self.wear_entry.get().strip()
        
        if not car_number:
            messagebox.showerror("Ошибка", "Введите номер автомобиля")
            return
        
        try:
            storage = self.service.accept_storage(
                car_number, storage_type, diameter, brand, damage, wear
            )
            
            self.print_receipt(storage, copies=2)
            
            messagebox.showinfo("Успех", f"Комплект принят на хранение.\nЧек сохранён в receipts/storage_{storage.id}.pdf")
            
            self.car_number_entry.delete(0, tk.END)
            self.brand_entry.delete(0, tk.END)
            self.damage_entry.delete(0, tk.END)
            self.wear_entry.delete(0, tk.END)
            
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
    
    def search_storage(self):
        car_number = self.search_car_entry.get().strip()
        
        if not car_number:
            storages = self.service.get_all_stored()
        else:
            storages = self.service.search_by_car_number(car_number)
        
        for item in self.storage_tree.get_children():
            self.storage_tree.delete(item)
        
        for storage in storages:
            self.storage_tree.insert('', 'end', values=(
                storage.id,
                storage.car_number,
                storage.storage_type,
                storage.diameter,
                storage.brand or '-',
                f"{int(storage.price)} ₽",
                storage.accepted_date.strftime('%d.%m.%Y %H:%M')
            ))
    
    def release_storage(self):
        selected = self.storage_tree.selection()
        if not selected:
            messagebox.showerror("Ошибка", "Выберите комплект для выдачи")
            return
        
        storage_id = self.storage_tree.item(selected[0])['values'][0]
        
        try:
            storage = self.service.release_storage(storage_id)
            
            if storage:
                self.print_release_receipt(storage)
                messagebox.showinfo("Успех", f"Комплект выдан.\nЧек сохранён в receipts/release_{storage.id}.pdf")
                self.search_storage()
            else:
                messagebox.showerror("Ошибка", "Комплект не найден")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
    
    def print_receipt(self, storage, copies=2):
        if not os.path.exists('receipts'):
            os.makedirs('receipts')
        
        filename = f'receipts/storage_{storage.id}.pdf'
        c = canvas.Canvas(filename, pagesize=letter)
        
        for copy in range(copies):
            if copy > 0:
                c.showPage()
            
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, 750, "ЧЕК ПРИЁМА ШИН НА ХРАНЕНИЕ")
            
            c.setFont("Helvetica", 12)
            y = 720
            c.drawString(50, y, f"Чек № {storage.id}")
            y -= 20
            c.drawString(50, y, f"Дата: {storage.accepted_date.strftime('%d.%m.%Y %H:%M')}")
            y -= 30
            c.drawString(50, y, f"Номер автомобиля: {storage.car_number}")
            y -= 20
            c.drawString(50, y, f"Тип хранения: {storage.storage_type}")
            y -= 20
            c.drawString(50, y, f"Диаметр: {storage.diameter}")
            y -= 20
            c.drawString(50, y, f"Марка шины: {storage.brand or '-'}")
            y -= 20
            c.drawString(50, y, f"Повреждения: {storage.damage or 'нет'}")
            y -= 20
            c.drawString(50, y, f"Износ: {storage.wear or '-'}")
            y -= 40
            
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, y, f"Цена хранения: {int(storage.price)} ₽")
            y -= 40
            
            c.setFont("Helvetica", 10)
            c.drawString(50, y, f"Экземпляр {copy + 1} из {copies}")
        
        c.save()
    
    def print_release_receipt(self, storage):
        if not os.path.exists('receipts'):
            os.makedirs('receipts')
        
        filename = f'receipts/release_{storage.id}.pdf'
        c = canvas.Canvas(filename, pagesize=letter)
        
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 750, "ЧЕК ВЫДАЧИ ШИН С ХРАНЕНИЯ")
        
        c.setFont("Helvetica", 12)
        y = 720
        c.drawString(50, y, f"Чек № {storage.id}")
        y -= 20
        c.drawString(50, y, f"Дата приёма: {storage.accepted_date.strftime('%d.%m.%Y %H:%M')}")
        y -= 20
        c.drawString(50, y, f"Дата выдачи: {storage.released_date.strftime('%d.%m.%Y %H:%M')}")
        y -= 30
        c.drawString(50, y, f"Номер автомобиля: {storage.car_number}")
        y -= 20
        c.drawString(50, y, f"Тип хранения: {storage.storage_type}")
        y -= 20
        c.drawString(50, y, f"Диаметр: {storage.diameter}")
        y -= 20
        c.drawString(50, y, f"Марка шины: {storage.brand or '-'}")
        y -= 40
        
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, f"Стоимость хранения: {int(storage.price)} ₽")
        y -= 40
        
        c.setFont("Helvetica", 10)
        c.drawString(50, y, "Шины выданы владельцу")
        
        c.save()
