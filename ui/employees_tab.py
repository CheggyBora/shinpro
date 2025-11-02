import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from services import EmployeeService
from services.shift_service import ShiftService
from datetime import datetime, timedelta
import styles

class EmployeesTab:
    def __init__(self, parent, db):
        self.db = db
        self.service = EmployeeService(db)
        self.shift_service = ShiftService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        
        left_frame = ttk.Frame(self.frame, style='BG.TFrame')
        left_frame.pack(side='left', fill='both', expand=True, padx=15, pady=15)
        
        # ========== ПАНЕЛЬ УПРАВЛЕНИЯ СМЕНАМИ (САМАЯ ВЕРХНЯЯ) ==========
        shift_control_card = styles.create_card_frame(left_frame)
        shift_control_card.pack(fill='x', pady=(0, 15))
        
        shift_control_inner = ttk.Frame(shift_control_card, style='White.TFrame')
        shift_control_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        # Контейнер для индикатора и кнопок
        control_container = ttk.Frame(shift_control_inner, style='White.TFrame')
        control_container.pack(fill='x')
        
        # Индикатор статуса смены (обновляется динамически)
        self.shift_status_frame = tk.Frame(control_container, bg='#10b981', relief='solid', borderwidth=1)
        self.shift_status_label = tk.Label(self.shift_status_frame, text="", bg='#10b981', fg='white', 
                                          font=(styles.DEFAULT_FONT, 11, 'bold'), padx=15, pady=8)
        self.shift_status_label.pack()
        
        # Кнопки управления
        buttons_frame = ttk.Frame(control_container, style='White.TFrame')
        buttons_frame.pack(side='right')
        
        self.open_shift_btn = styles.create_button(buttons_frame, "Открыть смену", self.open_shift, 'Success.TButton')
        self.close_shift_btn = styles.create_button(buttons_frame, "Закрыть смену", self.close_shift, 'Danger.TButton')
        
        shift_card = styles.create_card_frame(left_frame)
        shift_card.pack(fill='x', pady=(0, 15))
        
        shift_inner = ttk.Frame(shift_card, style='White.TFrame')
        shift_inner.pack(fill='both', expand=True, padx=20, pady=20)
        
        styles.create_label(shift_inner, "Регистрация сотрудников", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))
        
        shift_frame = ttk.Frame(shift_inner, style='White.TFrame')
        shift_frame.pack(fill='x', pady=5)
        styles.create_label(shift_frame, "Номер сотрудника:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.shift_employee_entry = styles.create_entry(shift_frame, width=15)
        self.shift_employee_entry.pack(side='left', padx=(0, 10))
        self.start_shift_btn = styles.create_button(shift_frame, "Начать смену", self.start_shift, 'Success.TButton')
        self.start_shift_btn.pack(side='left', padx=(0, 5))
        self.end_shift_btn = styles.create_button(shift_frame, "Закончить смену", self.end_shift, 'Danger.TButton')
        self.end_shift_btn.pack(side='left')
        
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
        
        # Кнопка просмотра зарплаты за смену
        styles.create_button(shift_inner, "💰 Посмотреть зарплату за смену", self.view_shift_salaries, 'Primary.TButton').pack(anchor='w', pady=(10, 0))
        
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
        
        self.employees_tree = ttk.Treeview(tree_frame, columns=('ID', 'Ставка %', 'Дата регистрации'), show='headings', height=6)
        self.employees_tree.heading('ID', text='Номер')
        self.employees_tree.heading('Ставка %', text='Ставка %')
        self.employees_tree.heading('Дата регистрации', text='Дата регистрации')
        self.employees_tree.column('ID', width=120)
        self.employees_tree.column('Ставка %', width=120)
        self.employees_tree.column('Дата регистрации', width=180)
        self.employees_tree.pack(side='left', fill='both', expand=True)
        
        tree_scroll = ttk.Scrollbar(tree_frame, orient='vertical', command=self.employees_tree.yview)
        tree_scroll.pack(side='right', fill='y')
        self.employees_tree.config(yscrollcommand=tree_scroll.set)
        
        # СОЗДАТЬ НОВОГО СОТРУДНИКА (компактная версия внизу)
        reg_card = styles.create_card_frame(left_frame)
        reg_card.pack(fill='x', pady=(15, 0))
        
        card_inner = ttk.Frame(reg_card, style='White.TFrame')
        card_inner.pack(fill='both', expand=True, padx=20, pady=18)
        
        styles.create_label(card_inner, "Создать нового сотрудника", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 12))
        
        reg_frame = ttk.Frame(card_inner, style='White.TFrame')
        reg_frame.pack(fill='x', pady=(0, 5))
        styles.create_label(reg_frame, "Номер:", 'Card.TLabel').pack(side='left', padx=(0, 5))
        self.employee_id_entry = styles.create_entry(reg_frame, width=12)
        self.employee_id_entry.pack(side='left', padx=(0, 8))
        styles.create_button(reg_frame, "Зарегистрировать", self.register_employee, 'Primary.TButton').pack(side='left')
        
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
        
        # Обновляем отображение статуса смены (в конце после создания всех элементов)
        self.update_shift_status()
    
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
    
    def update_shift_status(self):
        """Обновляет отображение статуса смены"""
        current_shift = self.shift_service.get_current_shift()
        
        if current_shift:
            # Смена открыта
            start_time = current_shift.start_time
            # Используем тот же часовой пояс, что и start_time
            current_time = datetime.now(start_time.tzinfo) if start_time.tzinfo else datetime.now()
            duration = current_time - start_time
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            
            status_text = f"Смена открыта: {start_time.strftime('%d.%m.%Y %H:%M')} (работает {hours}ч {minutes}м)"
            
            self.shift_status_label.config(text=status_text)
            self.shift_status_frame.config(bg='#10b981')
            self.shift_status_label.config(bg='#10b981')
            self.shift_status_frame.pack(side='left', padx=(0, 10))
            
            # Показываем кнопку закрытия, скрываем кнопку открытия
            self.open_shift_btn.pack_forget()
            self.close_shift_btn.pack(side='left')
            
            # Разблокируем регистрацию сотрудников
            self.shift_employee_entry.config(state='normal')
            self.start_shift_btn.config(state='normal')
            self.end_shift_btn.config(state='normal')
        else:
            # Смена закрыта
            status_text = "Смена не открыта"
            
            self.shift_status_label.config(text=status_text)
            self.shift_status_frame.config(bg='#dc2626')
            self.shift_status_label.config(bg='#dc2626')
            self.shift_status_frame.pack(side='left', padx=(0, 10))
            
            # Показываем кнопку открытия, скрываем кнопку закрытия
            self.close_shift_btn.pack_forget()
            self.open_shift_btn.pack(side='left')
            
            # Блокируем регистрацию сотрудников
            self.shift_employee_entry.config(state='disabled')
            self.start_shift_btn.config(state='disabled')
            self.end_shift_btn.config(state='disabled')
    
    def open_shift(self):
        """Открывает новую смену"""
        try:
            shift = self.shift_service.open_shift()
            messagebox.showinfo("Успех", f"Смена #{shift.id} открыта\nВремя: {shift.start_time.strftime('%d.%m.%Y %H:%M')}")
            self.update_shift_status()
            self.refresh_employees()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть смену: {str(e)}")
    
    def view_shift_salaries(self):
        """Показывает зарплату всех сотрудников за текущую смену"""
        current_shift = self.shift_service.get_current_shift()
        
        if not current_shift:
            messagebox.showinfo("Информация", "Нет открытой смены")
            return
        
        # Получаем данные о зарплате сотрудников
        employees_salary = self.shift_service.get_all_employees_shift_salary(current_shift.id)
        total_salary = sum(data['salary'] for data in employees_salary.values())
        
        # Создаём диалог
        dialog = tk.Toplevel(self.frame)
        dialog.title("Зарплата за текущую смену")
        dialog.geometry("450x500")
        dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(dialog, self.frame.winfo_toplevel())
        dialog.transient(self.frame.winfo_toplevel())
        dialog.grab_set()
        
        # Основной контейнер
        main_frame = tk.Frame(dialog, bg='white', padx=30, pady=25)
        main_frame.pack(fill='both', expand=True, padx=2, pady=2)
        
        # Заголовок
        title = tk.Label(main_frame, text="💰 Зарплата за смену", 
                        font=(styles.DEFAULT_FONT, 14, 'bold'), 
                        fg='#1e293b', bg='white')
        title.pack(pady=(0, 20))
        
        # Разделитель
        separator1 = ttk.Separator(main_frame, orient='horizontal')
        separator1.pack(fill='x', pady=(0, 15))
        
        # Информация о смене
        start_time = current_shift.start_time
        current_time = datetime.now(start_time.tzinfo) if start_time.tzinfo else datetime.now()
        duration = current_time - start_time
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        
        shift_text = (f"Смена: {start_time.strftime('%d.%m.%Y %H:%M')}\n"
                     f"Работает: {hours}ч {minutes}м")
        
        shift_label = tk.Label(main_frame, text=shift_text, 
                              font=(styles.DEFAULT_FONT, 11), 
                              fg='#1e293b', bg='white', justify='left')
        shift_label.pack(anchor='w', pady=(0, 15))
        
        # Разделитель
        separator2 = ttk.Separator(main_frame, orient='horizontal')
        separator2.pack(fill='x', pady=(0, 15))
        
        # Начисления
        salaries_label = tk.Label(main_frame, text="Начислено по сотрудникам:", 
                                 font=(styles.DEFAULT_FONT, 11, 'bold'), 
                                 fg='#1e293b', bg='white')
        salaries_label.pack(anchor='w', pady=(0, 10))
        
        # Список сотрудников с зарплатой
        employees_frame = tk.Frame(main_frame, bg='white')
        employees_frame.pack(fill='both', expand=True, pady=(0, 15))
        
        if employees_salary:
            for emp_id, data in employees_salary.items():
                employee = data['employee']
                salary = data['salary']
                emp_text = f"• №{employee.id} - {salary:,.0f} руб.".replace(',', ' ')
                emp_label = tk.Label(employees_frame, text=emp_text, 
                                    font=(styles.DEFAULT_FONT, 10), 
                                    fg='#1e293b', bg='white', anchor='w')
                emp_label.pack(anchor='w', pady=2)
        else:
            no_emp_label = tk.Label(employees_frame, text="Пока нет начислений за эту смену", 
                                   font=(styles.DEFAULT_FONT, 10), 
                                   fg='#94a3b8', bg='white')
            no_emp_label.pack(anchor='w')
        
        # Разделитель
        separator3 = ttk.Separator(main_frame, orient='horizontal')
        separator3.pack(fill='x', pady=(0, 15))
        
        # Итого
        total_text = f"Всего начислено: {total_salary:,.0f} руб.".replace(',', ' ')
        total_label = tk.Label(main_frame, text=total_text, 
                              font=(styles.DEFAULT_FONT, 12, 'bold'), 
                              fg='#2563eb', bg='white')
        total_label.pack(pady=(0, 20))
        
        # Кнопка OK
        ok_btn = styles.create_button(main_frame, "Закрыть", dialog.destroy, 'Primary.TButton')
        ok_btn.pack()
    
    def close_shift(self):
        """Закрывает текущую смену и показывает информационное окно"""
        current_shift = self.shift_service.get_current_shift()
        
        if not current_shift:
            messagebox.showerror("Ошибка", "Нет открытой смены")
            return
        
        # Подтверждение
        confirm = messagebox.askyesno(
            "Подтверждение", 
            "Вы действительно хотите закрыть текущую смену?",
            icon='question'
        )
        
        if not confirm:
            return
        
        try:
            # Закрываем смену
            result = self.shift_service.close_shift(current_shift.id)
            
            # Формируем информационное окно
            dialog = tk.Toplevel(self.frame)
            dialog.title("Смена закрыта")
            dialog.geometry("450x400")
            dialog.configure(bg='white')
            styles.center_window(dialog, self.frame.winfo_toplevel())
            dialog.transient(self.frame.winfo_toplevel())
            dialog.grab_set()
            
            # Основной контейнер
            main_frame = ttk.Frame(dialog, style='White.TFrame')
            main_frame.pack(fill='both', expand=True, padx=30, pady=20)
            
            # Заголовок
            title_label = tk.Label(main_frame, text="✓ Смена закрыта успешно!", 
                                  font=(styles.DEFAULT_FONT, 14, 'bold'), 
                                  fg='#10b981', bg='white')
            title_label.pack(pady=(0, 20))
            
            # Разделитель
            separator1 = ttk.Separator(main_frame, orient='horizontal')
            separator1.pack(fill='x', pady=(0, 15))
            
            # Информация о периоде
            shift = result['shift']
            duration_hours = result['duration_hours']
            hours = int(duration_hours)
            minutes = int((duration_hours - hours) * 60)
            
            period_text = (f"Период: {shift.start_time.strftime('%d.%m.%Y %H:%M')} - \n"
                          f"{shift.end_time.strftime('%d.%m.%Y %H:%M')} ({hours}ч {minutes}м)")
            
            period_label = tk.Label(main_frame, text=period_text, 
                                   font=(styles.DEFAULT_FONT, 11), 
                                   fg='#1e293b', bg='white', justify='left')
            period_label.pack(anchor='w', pady=(0, 15))
            
            # Разделитель
            separator2 = ttk.Separator(main_frame, orient='horizontal')
            separator2.pack(fill='x', pady=(0, 15))
            
            # Начисления
            salaries_label = tk.Label(main_frame, text="Начислено зарплаты:", 
                                     font=(styles.DEFAULT_FONT, 11, 'bold'), 
                                     fg='#1e293b', bg='white')
            salaries_label.pack(anchor='w', pady=(0, 10))
            
            # Список сотрудников с зарплатой
            employees_frame = tk.Frame(main_frame, bg='white')
            employees_frame.pack(fill='both', expand=True, pady=(0, 15))
            
            employees_data = result['employees']
            for emp_id, data in employees_data.items():
                employee = data['employee']
                salary = data['salary']
                emp_text = f"• №{employee.id} - {salary:,.0f} руб.".replace(',', ' ')
                emp_label = tk.Label(employees_frame, text=emp_text, 
                                    font=(styles.DEFAULT_FONT, 10), 
                                    fg='#1e293b', bg='white', anchor='w')
                emp_label.pack(anchor='w', pady=2)
            
            if not employees_data:
                no_emp_label = tk.Label(employees_frame, text="Нет начислений", 
                                       font=(styles.DEFAULT_FONT, 10), 
                                       fg='#94a3b8', bg='white')
                no_emp_label.pack(anchor='w')
            
            # Разделитель
            separator3 = ttk.Separator(main_frame, orient='horizontal')
            separator3.pack(fill='x', pady=(0, 15))
            
            # Итого
            total_salary = result['total_salary']
            total_text = f"Всего начислено: {total_salary:,.0f} руб.".replace(',', ' ')
            total_label = tk.Label(main_frame, text=total_text, 
                                  font=(styles.DEFAULT_FONT, 12, 'bold'), 
                                  fg='#2563eb', bg='white')
            total_label.pack(pady=(0, 20))
            
            # Кнопка OK
            ok_btn = styles.create_button(main_frame, "OK", dialog.destroy, 'Primary.TButton')
            ok_btn.pack()
            
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось закрыть смену: {str(e)}")
        finally:
            # Всегда обновляем интерфейс, даже при ошибке
            self.update_shift_status()
            self.refresh_employees()
