import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from services import EmployeeService
from datetime import datetime, timedelta
import styles

class EmployeesTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = EmployeeService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        
        left_frame = ttk.Frame(self.frame, style='BG.TFrame')
        left_frame.pack(side='left', fill='both', expand=True, padx=15, pady=15)
        
        reg_card = styles.create_card_frame(left_frame)
        reg_card.pack(fill='x', pady=(0, 15))
        
        card_inner = ttk.Frame(reg_card, style='White.TFrame')
        card_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(card_inner, "Регистрация сотрудника", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        reg_frame = ttk.Frame(card_inner, style='White.TFrame')
        reg_frame.pack(fill='x', pady=5)
        styles.create_label(reg_frame, "Номер сотрудника:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.employee_id_entry = styles.create_entry(reg_frame, width=15)
        self.employee_id_entry.pack(side='left', padx=(0, 10))
        styles.create_button(reg_frame, "Зарегистрировать", self.register_employee, 'Primary.TButton').pack(side='left')
        
        shift_card = styles.create_card_frame(left_frame)
        shift_card.pack(fill='x', pady=(0, 15))
        
        shift_inner = ttk.Frame(shift_card, style='White.TFrame')
        shift_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(shift_inner, "Управление сменами", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        shift_frame = ttk.Frame(shift_inner, style='White.TFrame')
        shift_frame.pack(fill='x', pady=5)
        styles.create_label(shift_frame, "Номер сотрудника:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.shift_employee_entry = styles.create_entry(shift_frame, width=15)
        self.shift_employee_entry.pack(side='left', padx=(0, 10))
        styles.create_button(shift_frame, "Начать смену", self.start_shift, 'Success.TButton').pack(side='left', padx=(0, 5))
        styles.create_button(shift_frame, "Закончить смену", self.end_shift, 'Danger.TButton').pack(side='left')
        
        styles.create_label(shift_inner, "Текущие смены:", 'Card.TLabel').pack(anchor='w', pady=(15, 5))
        
        shifts_frame = ttk.Frame(shift_inner, style='White.TFrame')
        shifts_frame.pack(fill='x')
        self.active_shifts_list = tk.Listbox(shifts_frame, height=5, font=styles.FONTS['normal'], 
                                            bg=styles.COLORS['bg'], fg=styles.COLORS['text'],
                                            selectbackground=styles.COLORS['primary'],
                                            relief='flat', borderwidth=1)
        self.active_shifts_list.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(shifts_frame, orient='vertical', command=self.active_shifts_list.yview)
        scrollbar.pack(side='right', fill='y')
        self.active_shifts_list.config(yscrollcommand=scrollbar.set)
        
        emp_card = styles.create_card_frame(left_frame)
        emp_card.pack(fill='both', expand=True)
        
        emp_inner = ttk.Frame(emp_card, style='White.TFrame')
        emp_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        header_frame = ttk.Frame(emp_inner, style='White.TFrame')
        header_frame.pack(fill='x', pady=(0, 10))
        styles.create_label(header_frame, "Список сотрудников", 'CardHeading.TLabel').pack(side='left')
        styles.create_button(header_frame, "Изменить ставку", self.change_salary_percent, 'Secondary.TButton').pack(side='right')
        
        tree_frame = ttk.Frame(emp_inner, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)
        
        self.employees_tree = ttk.Treeview(tree_frame, columns=('ID', 'Ставка %', 'Дата регистрации'), show='headings', height=8)
        self.employees_tree.heading('ID', text='Номер')
        self.employees_tree.heading('Ставка %', text='Ставка %')
        self.employees_tree.heading('Дата регистрации', text='Дата регистрации')
        self.employees_tree.column('ID', width=100)
        self.employees_tree.column('Ставка %', width=100)
        self.employees_tree.column('Дата регистрации', width=150)
        self.employees_tree.pack(side='left', fill='both', expand=True)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.employees_tree.yview)
        tree_scroll.pack(side='right', fill='y')
        self.employees_tree.config(yscrollcommand=tree_scroll.set)
        
        right_frame = ttk.Frame(self.frame, style='BG.TFrame')
        right_frame.pack(side='right', fill='both', expand=True, padx=15, pady=15)
        
        salary_card = styles.create_card_frame(right_frame)
        salary_card.pack(fill='both', expand=True)
        
        salary_inner = ttk.Frame(salary_card, style='White.TFrame')
        salary_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(salary_inner, "Просмотр зарплаты", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        salary_frame = ttk.Frame(salary_inner, style='White.TFrame')
        salary_frame.pack(fill='x', pady=(0, 10))
        styles.create_label(salary_frame, "Номер сотрудника:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.salary_employee_entry = styles.create_entry(salary_frame, width=15)
        self.salary_employee_entry.pack(side='left')
        
        date_frame = ttk.Frame(salary_inner, style='White.TFrame')
        date_frame.pack(fill='x', pady=(0, 10))
        styles.create_label(date_frame, "Дата от:", 'Card.TLabel').pack(side='left', padx=(0, 5))
        self.date_from_entry = styles.create_entry(date_frame, width=12)
        self.date_from_entry.insert(0, (datetime.now() - timedelta(days=30)).strftime('%d.%m.%Y'))
        self.date_from_entry.pack(side='left', padx=(0, 15))
        styles.create_label(date_frame, "до:", 'Card.TLabel').pack(side='left', padx=(0, 5))
        self.date_to_entry = styles.create_entry(date_frame, width=12)
        self.date_to_entry.insert(0, datetime.now().strftime('%d.%m.%Y'))
        self.date_to_entry.pack(side='left')
        
        styles.create_button(salary_inner, "Показать зарплату", self.show_salary, 'Primary.TButton').pack(pady=(0, 15))
        
        salary_tree_frame = ttk.Frame(salary_inner, style='White.TFrame')
        salary_tree_frame.pack(fill='both', expand=True, pady=(0, 10))
        
        self.salary_tree = ttk.Treeview(salary_tree_frame, columns=('Дата', 'Сумма'), show='headings')
        self.salary_tree.heading('Дата', text='Дата')
        self.salary_tree.heading('Сумма', text='Заработано')
        self.salary_tree.column('Дата', width=200)
        self.salary_tree.column('Сумма', width=200)
        self.salary_tree.pack(side='left', fill='both', expand=True)
        
        salary_scroll = ttk.Scrollbar(salary_tree_frame, orient='vertical', command=self.salary_tree.yview)
        salary_scroll.pack(side='right', fill='y')
        self.salary_tree.config(yscrollcommand=salary_scroll.set)
        
        self.total_label = styles.create_label(salary_inner, "Итого: 0.00 руб.", 'CardHeading.TLabel')
        self.total_label.pack(anchor='e', pady=(10, 0))
        
        self.refresh_employees()
        self.refresh_active_shifts()
    
    def register_employee(self):
        try:
            emp_id = int(self.employee_id_entry.get())
            self.service.register_employee(emp_id)
            messagebox.showinfo("Успех", f"Сотрудник {emp_id} зарегистрирован")
            self.employee_id_entry.delete(0, tk.END)
            self.refresh_employees()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
    
    def change_salary_percent(self):
        selected = self.employees_tree.selection()
        if not selected:
            messagebox.showwarning("Предупреждение", "Выберите сотрудника")
            return
        
        emp_id = int(self.employees_tree.item(selected[0])['values'][0])
        
        pin = simpledialog.askstring("PIN-код", "Введите админский PIN-код:", show='*')
        if not pin:
            return
        
        new_percent = simpledialog.askfloat("Новая ставка", "Введите новый процент зарплаты:")
        if new_percent is None:
            return
        
        try:
            self.service.update_salary_percent(emp_id, new_percent, pin)
            messagebox.showinfo("Успех", f"Ставка обновлена на {new_percent}%")
            self.refresh_employees()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
    
    def start_shift(self):
        try:
            emp_id = int(self.shift_employee_entry.get())
            self.service.start_shift(emp_id)
            messagebox.showinfo("Успех", f"Смена начата для сотрудника {emp_id}")
            self.shift_employee_entry.delete(0, tk.END)
            self.refresh_active_shifts()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
    
    def end_shift(self):
        try:
            emp_id = int(self.shift_employee_entry.get())
            self.service.end_shift(emp_id)
            messagebox.showinfo("Успех", f"Смена закончена для сотрудника {emp_id}")
            self.shift_employee_entry.delete(0, tk.END)
            self.refresh_active_shifts()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
    
    def show_salary(self):
        try:
            emp_id = int(self.salary_employee_entry.get())
            date_from = datetime.strptime(self.date_from_entry.get(), '%d.%m.%Y')
            date_to = datetime.strptime(self.date_to_entry.get(), '%d.%m.%Y') + timedelta(days=1) - timedelta(seconds=1)
            
            transactions = self.service.get_salary_report(emp_id, date_from, date_to)
            
            for item in self.salary_tree.get_children():
                self.salary_tree.delete(item)
            
            # Группируем транзакции по дням
            daily_data = {}
            for trans in transactions:
                date_key = trans.transaction_date.date()
                if date_key not in daily_data:
                    daily_data[date_key] = {'count': 0, 'total': 0}
                daily_data[date_key]['count'] += 1
                daily_data[date_key]['total'] += trans.amount
            
            # Сортируем по дате и добавляем в таблицу
            total = 0
            for date_key in sorted(daily_data.keys()):
                data = daily_data[date_key]
                self.salary_tree.insert('', 'end', values=(
                    date_key.strftime('%d.%m.%Y'),
                    f"{data['total']:.2f}"
                ))
                total += data['total']
            
            self.total_label.config(text=f"Итого: {total:.2f} руб.")
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
    
    def refresh_employees(self):
        for item in self.employees_tree.get_children():
            self.employees_tree.delete(item)
        
        employees = self.service.get_all_employees()
        for emp in employees:
            self.employees_tree.insert('', 'end', values=(
                emp.id,
                f"{emp.salary_percent:.1f}",
                emp.created_at.strftime('%d.%m.%Y')
            ))
    
    def refresh_active_shifts(self):
        self.active_shifts_list.delete(0, tk.END)
        shifts = self.service.get_active_shifts()
        for shift in shifts:
            self.active_shifts_list.insert(tk.END, f"Сотрудник {shift.employee_id} с {shift.start_time.strftime('%H:%M')}")
