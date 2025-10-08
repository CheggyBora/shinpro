import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from services import OrderService, SalaryService, PrintService
from datetime import datetime

class OrdersTab:
    def __init__(self, parent, db):
        self.db = db
        self.order_service = OrderService(db)
        self.salary_service = SalaryService(db)
        self.print_service = PrintService()
        self.frame = ttk.Frame(parent)
        self.active_orders = {}
        
        top_frame = ttk.Frame(self.frame)
        top_frame.pack(fill='x', padx=10, pady=5)
        
        services_label = ttk.Label(top_frame, text="Кнопки услуг:", font=('Arial', 10, 'bold'))
        services_label.pack(anchor='w')
        
        self.services_frame = ttk.Frame(top_frame)
        self.services_frame.pack(fill='x', pady=5)
        
        self.load_service_buttons()
        
        tabs_frame = ttk.Frame(self.frame)
        tabs_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Button(tabs_frame, text="+ Новый наряд", command=self.create_new_order).pack(side='left', padx=5)
        
        self.order_notebook = ttk.Notebook(tabs_frame)
        self.order_notebook.pack(side='left', fill='both', expand=True)
        
        self.content_frame = ttk.Frame(self.frame)
        self.content_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        self.order_notebook.bind('<<NotebookTabChanged>>', self.on_tab_change)
    
    def load_service_buttons(self):
        services = self.order_service.get_all_services()
        for i, service in enumerate(services):
            btn = ttk.Button(self.services_frame, text=service.name, 
                           command=lambda s=service: self.add_service_to_current_order(s))
            btn.grid(row=i//5, column=i%5, padx=2, pady=2, sticky='ew')
    
    def create_new_order(self):
        dialog = tk.Toplevel(self.frame)
        dialog.title("Новый наряд")
        dialog.geometry("400x250")
        
        ttk.Label(dialog, text="Номер машины*:").pack(pady=5)
        license_entry = ttk.Entry(dialog, width=30)
        license_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Диаметр колеса*:").pack(pady=5)
        diameter_var = tk.StringVar()
        diameter_combo = ttk.Combobox(dialog, textvariable=diameter_var, 
                                      values=['R13', 'R14', 'R15', 'R16', 'R17', 'R18', 'R19', 'R20', 'R21', 'R22'],
                                      width=28)
        diameter_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Номер клиента:").pack(pady=5)
        client_number_entry = ttk.Entry(dialog, width=30)
        client_number_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Имя клиента:").pack(pady=5)
        client_name_entry = ttk.Entry(dialog, width=30)
        client_name_entry.pack(pady=5)
        
        def create():
            license = license_entry.get().strip()
            diameter = diameter_var.get()
            client_number = client_number_entry.get().strip() or None
            client_name = client_name_entry.get().strip() or None
            
            if not license or not diameter:
                messagebox.showerror("Ошибка", "Заполните обязательные поля")
                return
            
            try:
                order = self.order_service.create_order(license, diameter, client_number, client_name)
                self.open_order_tab(order)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        ttk.Button(dialog, text="Создать", command=create).pack(pady=10)
    
    def open_order_tab(self, order):
        tab_frame = ttk.Frame(self.order_notebook)
        tab_title = f"#{order.id}: {order.car.license_plate}"
        self.order_notebook.add(tab_frame, text=tab_title)
        
        order_widget = OrderWidget(tab_frame, order, self.db, self.order_service, 
                                   self.salary_service, self.print_service, self.close_order_tab)
        self.active_orders[order.id] = order_widget
        
        self.order_notebook.select(tab_frame)
    
    def close_order_tab(self, order_id):
        if order_id in self.active_orders:
            widget = self.active_orders[order_id]
            self.order_notebook.forget(widget.frame)
            del self.active_orders[order_id]
    
    def add_service_to_current_order(self, service):
        current_tab = self.order_notebook.select()
        if not current_tab:
            messagebox.showwarning("Предупреждение", "Создайте наряд")
            return
        
        for order_id, widget in self.active_orders.items():
            if str(widget.frame) == current_tab:
                widget.add_service(service)
                break
    
    def on_tab_change(self, event):
        pass

class OrderWidget:
    def __init__(self, frame, order, db, order_service, salary_service, print_service, close_callback):
        self.frame = frame
        self.order = order
        self.db = db
        self.order_service = order_service
        self.salary_service = salary_service
        self.print_service = print_service
        self.close_callback = close_callback
        
        info_frame = ttk.Frame(frame)
        info_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(info_frame, text=f"Номер машины: {order.car.license_plate}", font=('Arial', 10, 'bold')).pack(anchor='w')
        ttk.Label(info_frame, text=f"Диаметр: {order.wheel_diameter}").pack(anchor='w')
        if order.client:
            client_info = order.client.name or ""
            if order.client.client_number:
                client_info += f" (#{order.client.client_number})"
            ttk.Label(info_frame, text=f"Клиент: {client_info}").pack(anchor='w')
        ttk.Label(info_frame, text=f"Автоскидка 5%: {'✓' if order.auto_discount else '✗'}").pack(anchor='w')
        
        ttk.Label(frame, text="Список услуг:", font=('Arial', 10, 'bold')).pack(anchor='w', padx=10, pady=5)
        
        self.items_tree = ttk.Treeview(frame, columns=('Услуга', 'Цена', 'Скидка', 'Итого'), show='headings', height=10)
        self.items_tree.heading('Услуга', text='Услуга')
        self.items_tree.heading('Цена', text='Цена')
        self.items_tree.heading('Скидка', text='Скидка %')
        self.items_tree.heading('Итого', text='Итого')
        self.items_tree.pack(fill='both', expand=True, padx=10, pady=5)
        self.items_tree.bind('<Double-1>', self.edit_item)
        self.items_tree.bind('<Delete>', self.delete_item)
        
        discount_frame = ttk.Frame(frame)
        discount_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Label(discount_frame, text="Общая скидка:").pack(side='left')
        self.general_discount_var = tk.StringVar(value='0')
        discount_combo = ttk.Combobox(discount_frame, textvariable=self.general_discount_var, 
                                      values=['0', '5', '10', '15'], width=10)
        discount_combo.pack(side='left', padx=5)
        ttk.Button(discount_frame, text="Применить", command=self.apply_general_discount).pack(side='left', padx=5)
        
        self.total_label = ttk.Label(frame, text="ИТОГО: 0.00 руб.", font=('Arial', 14, 'bold'))
        self.total_label.pack(pady=10)
        
        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=5)
        ttk.Button(button_frame, text="Оплатить", command=self.process_payment).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Закрыть вкладку", command=lambda: self.close_callback(order.id)).pack(side='left', padx=5)
        
        self.refresh_items()
    
    def add_service(self, service):
        try:
            self.order_service.add_service_to_order(self.order.id, service.id)
            self.refresh_items()
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
    
    def edit_item(self, event):
        selected = self.items_tree.selection()
        if not selected:
            return
        
        item_id = int(self.items_tree.item(selected[0])['tags'][0])
        item = next((i for i in self.order_service.get_order_items(self.order.id) if i.id == item_id), None)
        
        if not item:
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Редактировать услугу")
        dialog.geometry("350x200")
        
        ttk.Label(dialog, text=f"Услуга: {item.service.name}").pack(pady=5)
        
        ttk.Label(dialog, text="Комментарий:").pack(pady=5)
        comment_entry = ttk.Entry(dialog, width=40)
        comment_entry.insert(0, item.comment or "")
        comment_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Скидка (для правки дисков):").pack(pady=5)
        discount_var = tk.StringVar(value=str(item.discount_percent))
        discount_combo = ttk.Combobox(dialog, textvariable=discount_var, values=['0', '10', '20'], width=10)
        discount_combo.pack(pady=5)
        
        def save():
            self.order_service.update_item_discount(item_id, int(discount_var.get()), comment_entry.get())
            self.refresh_items()
            dialog.destroy()
        
        ttk.Button(dialog, text="Сохранить", command=save).pack(pady=10)
    
    def delete_item(self, event):
        selected = self.items_tree.selection()
        if not selected:
            return
        
        if messagebox.askyesno("Подтверждение", "Удалить услугу?"):
            item_id = int(self.items_tree.item(selected[0])['tags'][0])
            self.order_service.delete_item(item_id)
            self.refresh_items()
    
    def apply_general_discount(self):
        discount = int(self.general_discount_var.get())
        self.order_service.update_general_discount(self.order.id, discount)
        self.db.refresh(self.order)
        self.refresh_items()
    
    def process_payment(self):
        total = self.order_service.calculate_total(self.order.id)
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Оплата")
        dialog.geometry("300x150")
        
        ttk.Label(dialog, text=f"Сумма к оплате: {total:.2f} руб.", font=('Arial', 12, 'bold')).pack(pady=10)
        
        payment_var = tk.StringVar(value='cash')
        ttk.Radiobutton(dialog, text="Наличные", variable=payment_var, value='cash').pack(pady=5)
        ttk.Radiobutton(dialog, text="Безналичный расчёт", variable=payment_var, value='card').pack(pady=5)
        
        def pay():
            try:
                self.salary_service.process_payment(self.order.id, payment_var.get(), total)
                self.db.refresh(self.order)
                
                items = self.order_service.get_order_items(self.order.id)
                receipt_file = self.print_service.generate_receipt(self.order, items, total)
                
                messagebox.showinfo("Успех", f"Оплата проведена!\nЧек сохранён: {receipt_file}")
                dialog.destroy()
                self.close_callback(self.order.id)
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        ttk.Button(dialog, text="Оплатить", command=pay).pack(pady=10)
    
    def refresh_items(self):
        for item in self.items_tree.get_children():
            self.items_tree.delete(item)
        
        items = self.order_service.get_order_items(self.order.id)
        for item in items:
            item_total = item.price * (1 - item.discount_percent / 100)
            self.items_tree.insert('', 'end', values=(
                item.service.name,
                f"{item.price:.2f}",
                item.discount_percent,
                f"{item_total:.2f}"
            ), tags=(str(item.id),))
        
        total = self.order_service.calculate_total(self.order.id)
        self.total_label.config(text=f"ИТОГО: {total:.2f} руб.")
