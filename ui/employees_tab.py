import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from services import EmployeeService
from datetime import datetime, timedelta

class EmployeesTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = EmployeeService(db)
        self.frame = ttk.Frame(parent)
        
        left_frame = ttk.Frame(self.frame)
        left_frame.pack(side='left', fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(left_frame, text="Регистрация сотрудника", font=('Arial', 12, 'bold')).pack(pady=5)
        
        reg_frame = ttk.Frame(left_frame)
        reg_frame.pack(fill='x', pady=5)
        ttk.Label(reg_frame, text="Номер сотрудника:").pack(side='left')
        self.employee_id_entry = ttk.Entry(reg_frame, width=15)
        self.employee_id_entry.pack(side='left', padx=5)
        ttk.Button(reg_frame, text="Зарегистрировать", command=self.register_employee).pack(side='left', padx=5)
        
        ttk.Separator(left_frame, orient='horizontal').pack(fill='x', pady=10)
        
        ttk.Label(left_frame, text="Управление сменами", font=('Arial', 12, 'bold')).pack(pady=5)
        
        shift_frame = ttk.Frame(left_frame)
        shift_frame.pack(fill='x', pady=5)
        ttk.Label(shift_frame, text="Номер сотрудника:").pack(side='left')
        self.shift_employee_entry = ttk.Entry(shift_frame, width=15)
        self.shift_employee_entry.pack(side='left', padx=5)
        ttk.Button(shift_frame, text="Начать смену", command=self.start_shift).pack(side='left', padx=5)
        ttk.Button(shift_frame, text="Закончить смену", command=self.end_shift).pack(side='left', padx=5)
        
        ttk.Label(left_frame, text="Текущие смены:").pack(pady=5)
        self.active_shifts_list = tk.Listbox(left_frame, height=5)
        self.active_shifts_list.pack(fill='x', pady=5)
        
        ttk.Separator(left_frame, orient='horizontal').pack(fill='x', pady=10)
        
        ttk.Label(left_frame, text="Список сотрудников", font=('Arial', 12, 'bold')).pack(pady=5)
        
        self.employees_tree = ttk.Treeview(left_frame, columns=('ID', 'Ставка %', 'Дата регистрации'), show='headings', height=8)
        self.employees_tree.heading('ID', text='Номер')
        self.employees_tree.heading('Ставка %', text='Ставка %')
        self.employees_tree.heading('Дата регистрации', text='Дата регистрации')
        self.employees_tree.column('ID', width=100)
        self.employees_tree.column('Ставка %', width=100)
        self.employees_tree.column('Дата регистрации', width=150)
        self.employees_tree.pack(fill='both', expand=True, pady=5)
        
        ttk.Button(left_frame, text="Изменить ставку", command=self.change_salary_percent).pack(pady=5)
        
        right_frame = ttk.Frame(self.frame)
        right_frame.pack(side='right', fill='both', expand=True, padx=10, pady=10)
        
        ttk.Label(right_frame, text="Просмотр зарплаты", font=('Arial', 12, 'bold')).pack(pady=5)
        
        salary_frame = ttk.Frame(right_frame)
        salary_frame.pack(fill='x', pady=5)
        ttk.Label(salary_frame, text="Номер сотрудника:").pack(side='left')
        self.salary_employee_entry = ttk.Entry(salary_frame, width=15)
        self.salary_employee_entry.pack(side='left', padx=5)
        
        date_frame = ttk.Frame(right_frame)
        date_frame.pack(fill='x', pady=5)
        ttk.Label(date_frame, text="Дата от:").pack(side='left')
        self.date_from_entry = ttk.Entry(date_frame, width=12)
        self.date_from_entry.insert(0, (datetime.now() - timedelta(days=30)).strftime('%d.%m.%Y'))
        self.date_from_entry.pack(side='left', padx=5)
        ttk.Label(date_frame, text="до:").pack(side='left')
        self.date_to_entry = ttk.Entry(date_frame, width=12)
        self.date_to_entry.insert(0, datetime.now().strftime('%d.%m.%Y'))
        self.date_to_entry.pack(side='left', padx=5)
        
        ttk.Button(right_frame, text="Показать зарплату", command=self.show_salary).pack(pady=5)
        
        self.salary_tree = ttk.Treeview(right_frame, columns=('Дата', 'Наряд', 'Сумма'), show='headings')
        self.salary_tree.heading('Дата', text='Дата')
        self.salary_tree.heading('Наряд', text='Наряд №')
        self.salary_tree.heading('Сумма', text='Заработано')
        self.salary_tree.pack(fill='both', expand=True, pady=5)
        
        self.total_label = ttk.Label(right_frame, text="Итого: 0.00 руб.", font=('Arial', 11, 'bold'))
        self.total_label.pack(pady=5)
        
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
            date_to = datetime.strptime(self.date_to_entry.get(), '%d.%m.%Y')
            
            transactions = self.service.get_salary_report(emp_id, date_from, date_to)
            
            for item in self.salary_tree.get_children():
                self.salary_tree.delete(item)
            
            total = 0
            for trans in transactions:
                self.salary_tree.insert('', 'end', values=(
                    trans.transaction_date.strftime('%d.%m.%Y %H:%M'),
                    trans.work_order_id,
                    f"{trans.amount:.2f}"
                ))
                total += trans.amount
            
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
