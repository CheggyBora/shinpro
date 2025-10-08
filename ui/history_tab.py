import tkinter as tk
from tkinter import ttk, messagebox
from models import Car, WorkOrder, WorkOrderItem
from sqlalchemy.orm import joinedload

class HistoryTab:
    def __init__(self, parent, db):
        self.db = db
        self.frame = ttk.Frame(parent)
        
        search_frame = ttk.Frame(self.frame)
        search_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(search_frame, text="Номер автомобиля:", font=('Arial', 12, 'bold')).pack(side='left', padx=5)
        self.license_entry = ttk.Entry(search_frame, width=20)
        self.license_entry.pack(side='left', padx=5)
        ttk.Button(search_frame, text="Найти", command=self.search_history).pack(side='left', padx=5)
        
        ttk.Label(self.frame, text="История нарядов:", font=('Arial', 12, 'bold')).pack(anchor='w', padx=10, pady=5)
        
        self.history_tree = ttk.Treeview(self.frame, columns=('Дата', 'Наряд №', 'Услуги', 'Сумма', 'Оплата'), show='headings')
        self.history_tree.heading('Дата', text='Дата')
        self.history_tree.heading('Наряд №', text='Наряд №')
        self.history_tree.heading('Услуги', text='Услуги')
        self.history_tree.heading('Сумма', text='Сумма')
        self.history_tree.heading('Оплата', text='Способ оплаты')
        self.history_tree.column('Дата', width=150)
        self.history_tree.column('Наряд №', width=100)
        self.history_tree.column('Услуги', width=400)
        self.history_tree.column('Сумма', width=100)
        self.history_tree.column('Оплата', width=150)
        self.history_tree.pack(fill='both', expand=True, padx=10, pady=5)
        self.history_tree.bind('<Double-1>', self.show_order_details)
    
    def search_history(self):
        license = self.license_entry.get().strip()
        if not license:
            messagebox.showwarning("Предупреждение", "Введите номер автомобиля")
            return
        
        car = self.db.query(Car).filter(Car.license_plate == license).first()
        if not car:
            messagebox.showinfo("Информация", "Автомобиль не найден")
            return
        
        orders = self.db.query(WorkOrder).options(joinedload(WorkOrder.items)).filter(
            WorkOrder.car_id == car.id,
            WorkOrder.status == 'paid'
        ).order_by(WorkOrder.paid_at.desc()).all()
        
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        
        for order in orders:
            items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order.id).all()
            services_list = ', '.join([item.service.name for item in items])
            
            payment_method = 'Наличные' if order.payment_method == 'cash' else 'Безнал'
            
            self.history_tree.insert('', 'end', values=(
                order.paid_at.strftime('%d.%m.%Y %H:%M'),
                order.id,
                services_list[:50] + '...' if len(services_list) > 50 else services_list,
                f"{order.total_amount:.2f}",
                payment_method
            ), tags=(str(order.id),))
    
    def show_order_details(self, event):
        selected = self.history_tree.selection()
        if not selected:
            return
        
        order_id = int(self.history_tree.item(selected[0])['tags'][0])
        order = self.db.query(WorkOrder).filter(WorkOrder.id == order_id).first()
        
        if not order:
            return
        
        dialog = tk.Toplevel(self.frame)
        dialog.title(f"Детали наряда #{order_id}")
        dialog.geometry("500x400")
        
        info_frame = ttk.Frame(dialog)
        info_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(info_frame, text=f"Наряд #{order.id}", font=('Arial', 14, 'bold')).pack(anchor='w')
        ttk.Label(info_frame, text=f"Дата: {order.paid_at.strftime('%d.%m.%Y %H:%M')}").pack(anchor='w')
        ttk.Label(info_frame, text=f"Автомобиль: {order.car.license_plate}").pack(anchor='w')
        if order.client:
            client_info = f"{order.client.name or ''}"
            if order.client.client_number:
                client_info += f" (#{order.client.client_number})"
            ttk.Label(info_frame, text=f"Клиент: {client_info}").pack(anchor='w')
        ttk.Label(info_frame, text=f"Диаметр: {order.wheel_diameter}").pack(anchor='w')
        
        ttk.Label(dialog, text="Услуги:", font=('Arial', 12, 'bold')).pack(anchor='w', padx=10, pady=5)
        
        items_tree = ttk.Treeview(dialog, columns=('Услуга', 'Цена', 'Скидка', 'Итого', 'Комментарий'), show='headings')
        items_tree.heading('Услуга', text='Услуга')
        items_tree.heading('Цена', text='Цена')
        items_tree.heading('Скидка', text='Скидка %')
        items_tree.heading('Итого', text='Итого')
        items_tree.heading('Комментарий', text='Комментарий')
        items_tree.pack(fill='both', expand=True, padx=10, pady=5)
        
        items = self.db.query(WorkOrderItem).filter(WorkOrderItem.work_order_id == order_id).all()
        for item in items:
            item_total = item.price * (1 - item.discount_percent / 100)
            items_tree.insert('', 'end', values=(
                item.service.name,
                f"{item.price:.2f}",
                item.discount_percent,
                f"{item_total:.2f}",
                item.comment or ""
            ))
        
        total_frame = ttk.Frame(dialog)
        total_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Label(total_frame, text=f"Общая скидка: {order.general_discount}%").pack(anchor='w')
        ttk.Label(total_frame, text=f"Автоскидка 5%: {'Да' if order.auto_discount else 'Нет'}").pack(anchor='w')
        payment_method = 'Наличные' if order.payment_method == 'cash' else 'Безналичный'
        ttk.Label(total_frame, text=f"Способ оплаты: {payment_method}").pack(anchor='w')
        ttk.Label(total_frame, text=f"ИТОГО: {order.total_amount:.2f} руб.", font=('Arial', 14, 'bold')).pack(anchor='w', pady=5)
        
        ttk.Button(dialog, text="Закрыть", command=dialog.destroy).pack(pady=10)
