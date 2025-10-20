import tkinter as tk
from tkinter import ttk, messagebox
from services.tire_storage_service import TireStorageService
from datetime import datetime
import styles
import os
import sys
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping

def register_dejavu_fonts():
    """Регистрирует шрифт DejaVu Sans для PDF документов с поддержкой кириллицы"""
    if getattr(sys, 'frozen', False):
        # PyInstaller создаёт временную папку sys._MEIPASS для упакованных ресурсов
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    fonts_dir = os.path.join(base_path, "fonts")
    font_path = os.path.join(fonts_dir, 'DejaVuSans.ttf')
    
    try:
        if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
            else:
                raise FileNotFoundError(f"Файл шрифта не найден: {font_path}")
        
        return 'DejaVuSans'
    except Exception as e:
        print(f"Ошибка регистрации шрифта DejaVu: {e}")
        return 'Helvetica'

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
        
        styles.create_label(row1, "Вод. удостоверение:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.driver_license_entry = styles.create_entry(row1, width=20)
        self.driver_license_entry.pack(side='left')
        
        row1a = ttk.Frame(form_frame, style='White.TFrame')
        row1a.pack(fill='x', pady=5)
        styles.create_label(row1a, "Тип хранения:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.storage_type_var = tk.StringVar(value='Шины')
        storage_combo = ttk.Combobox(row1a, textvariable=self.storage_type_var, 
                                     values=['Шины', 'Шины с дисками'], 
                                     state='readonly', width=18, font=styles.FONTS['normal'])
        storage_combo.pack(side='left')
        storage_combo.bind('<<ComboboxSelected>>', self.on_storage_type_change)
        
        self.wheel_type_row = ttk.Frame(form_frame, style='White.TFrame')
        styles.create_label(self.wheel_type_row, "Тип дисков:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.wheel_type_var = tk.StringVar(value='Литые')
        wheel_type_combo = ttk.Combobox(self.wheel_type_row, textvariable=self.wheel_type_var, 
                                        values=['Литые', 'Штампованные'], 
                                        state='readonly', width=18, font=styles.FONTS['normal'])
        wheel_type_combo.pack(side='left')
        
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
        
        row5 = ttk.Frame(form_frame, style='White.TFrame')
        row5.pack(fill='x', pady=5)
        styles.create_label(row5, "Комментарии:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.comments_entry = styles.create_entry(row5, width=70)
        self.comments_entry.pack(side='left')
        
        price_frame = ttk.Frame(card_inner, style='White.TFrame')
        price_frame.pack(fill='x', pady=15)
        styles.create_label(price_frame, "Цена хранения:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.price_label = styles.create_label(price_frame, "5000 ₽", 'CardHeading.TLabel')
        self.price_label.pack(side='left')
        
        btn_frame = ttk.Frame(card_inner, style='White.TFrame')
        btn_frame.pack(fill='x', pady=10)
        styles.create_button(btn_frame, "Оплатить", 
                           self.process_storage_payment, 'Success.TButton').pack(side='left')
    
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
    
    def on_storage_type_change(self, event=None):
        storage_type = self.storage_type_var.get()
        if storage_type == 'Шины с дисками':
            self.wheel_type_row.pack(fill='x', pady=5, after=self.wheel_type_row.master.winfo_children()[0])
        else:
            self.wheel_type_row.pack_forget()
    
    def process_storage_payment(self):
        """Показывает диалог оплаты для приёма на хранение"""
        import platform
        
        # Проверяем обязательные поля
        car_number = self.car_number_entry.get().strip()
        if not car_number:
            messagebox.showerror("Ошибка", "Введите номер автомобиля")
            return
        
        # Получаем цену
        diameter = self.diameter_var.get()
        price = self.service.calculate_price(diameter)
        
        # Создаём диалог оплаты
        dialog = tk.Toplevel(self.frame)
        dialog.title("Оплата хранения")
        dialog.geometry("400x300")
        dialog.configure(bg=styles.COLORS['bg'])
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        total_label = styles.create_label(content, f"Сумма к оплате: {int(price)} ₽", 'CardHeading.TLabel')
        total_label.pack(pady=(0, 20))
        total_label.configure(font=(styles.DEFAULT_FONT, 16, 'bold'), foreground=styles.COLORS['primary'])
        
        payment_var = tk.StringVar(value='cash')
        
        radio_frame = ttk.Frame(content, style='White.TFrame')
        radio_frame.pack(fill='x', pady=(0, 20))
        
        ttk.Radiobutton(radio_frame, text="Наличные", variable=payment_var, value='cash').pack(anchor='w', pady=5)
        ttk.Radiobutton(radio_frame, text="Безналичный расчёт", variable=payment_var, value='card').pack(anchor='w', pady=5)
        
        def pay_and_process():
            """Оплата и создание документов"""
            try:
                payment_method = payment_var.get()
                self.accept_storage_with_payment(payment_method, price)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        # Кнопка оплаты
        button_frame = ttk.Frame(content, style='White.TFrame')
        button_frame.pack(fill='x', pady=(10, 0))
        
        styles.create_button(button_frame, "💳 Оплатить", pay_and_process, 'Success.TButton').pack(fill='x')
    
    def accept_storage_with_payment(self, payment_method, price):
        """Принимает на хранение с оплатой и создаёт все документы"""
        import platform
        from services.order_service import OrderService
        from services.print_service import PrintService
        from datetime import datetime
        
        car_number = self.car_number_entry.get().strip()
        driver_license = self.driver_license_entry.get().strip()
        storage_type = self.storage_type_var.get()
        diameter = self.diameter_var.get()
        brand = self.brand_entry.get().strip()
        damage = self.damage_entry.get().strip()
        wear = self.wear_entry.get().strip()
        comments = self.comments_entry.get().strip()
        
        wheel_type = None
        if storage_type == 'Шины с дисками':
            wheel_type = self.wheel_type_var.get()
        
        try:
            # 1. Создаём наряд (WorkOrder) для статистики
            order_service = OrderService(self.db)
            work_order = order_service.create_order(
                license_plate=car_number,
                wheel_diameter=diameter,
                vehicle_type='car',
                client_name=f"Хранение ({storage_type})"
            )
            
            # 2. Создаём запись в хранилище с привязкой к наряду
            storage = self.service.accept_storage(
                car_number, driver_license, storage_type, diameter, brand, damage, wear, comments, wheel_type
            )
            
            # Привязываем наряд к записи хранилища
            storage.work_order_id = work_order.id
            self.db.commit()
            self.db.refresh(storage)
            
            # 3. Добавляем услугу "Хранение шин" в наряд
            from models import Service, WorkOrderItem
            storage_service = self.db.query(Service).filter(Service.name == 'Хранение шин').first()
            
            if storage_service:
                # Используем существующую услугу хранения
                storage_item = WorkOrderItem(
                    work_order_id=work_order.id,
                    service_id=storage_service.id,
                    quantity=1,
                    price=price,
                    discount_percent=0
                )
                self.db.add(storage_item)
                self.db.flush()
            else:
                raise ValueError("Услуга 'Хранение шин' не найдена в базе данных. Обратитесь к администратору.")
            
            # 4. Оплачиваем наряд БЕЗ начисления зарплаты
            work_order.paid_at = datetime.now()
            work_order.payment_method = payment_method
            work_order.total_amount = price
            work_order.status = 'paid'
            self.db.commit()
            self.db.refresh(work_order)
            
            # 5. Генерируем чек оплаты
            print_service = PrintService()
            items = order_service.get_order_items(work_order.id)
            receipt_file = print_service.generate_receipt(work_order, items, price)
            
            # 6. Показываем диалог с чеком
            self.show_receipt_dialog(receipt_file, storage, payment_method)
            
            # Очищаем поля
            self.car_number_entry.delete(0, tk.END)
            self.driver_license_entry.delete(0, tk.END)
            self.brand_entry.delete(0, tk.END)
            self.damage_entry.delete(0, tk.END)
            self.wear_entry.delete(0, tk.END)
            self.comments_entry.delete(0, tk.END)
            
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", str(e))
    
    def show_receipt_dialog(self, receipt_file, storage, payment_method):
        """Показывает диалог для печати/просмотра чека и актов"""
        import platform
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Документы готовы")
        dialog.geometry("450x250")
        dialog.configure(bg=styles.COLORS['bg'])
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        title_label = styles.create_label(content, f"Оплата хранения #{storage.id}", 'CardHeading.TLabel')
        title_label.pack(pady=(0, 10))
        
        payment_text = "Наличные" if payment_method == 'cash' else "Безналичный расчёт"
        info_label = styles.create_label(content, f"Способ оплаты: {payment_text}\nСумма: {int(storage.price)} ₽", 'Card.TLabel')
        info_label.pack(pady=(0, 20))
        
        def print_receipt():
            """Печать чека оплаты"""
            if platform.system() == 'Windows':
                os.startfile(os.path.abspath(receipt_file), "print")
            else:
                try:
                    import subprocess
                    subprocess.run(['lp', receipt_file], check=True)
                except:
                    pass
            
            # После печати чека печатаем 2 экземпляра акта приёма
            self.print_receipt(storage, copies=2)
            storage_act = f"receipts/storage_{storage.id}.pdf"
            
            if platform.system() == 'Windows':
                os.startfile(os.path.abspath(storage_act), "print")
                messagebox.showinfo("Успех", f"Комплект #{storage.id} принят на хранение!\n\nЧек оплаты и 2 экземпляра акта отправлены на печать")
            else:
                try:
                    import subprocess
                    subprocess.run(['lp', storage_act], check=True)
                    messagebox.showinfo("Успех", f"Комплект #{storage.id} принят на хранение!\n\nДокументы отправлены на печать")
                except:
                    messagebox.showinfo("Успех", f"Комплект #{storage.id} принят на хранение!\n\nДокументы сохранены")
            
            dialog.destroy()
        
        def preview_receipt():
            """Просмотр чека"""
            abs_path = os.path.abspath(receipt_file)
            if platform.system() == 'Windows':
                os.startfile(abs_path)
            elif platform.system() == 'Darwin':
                import subprocess
                subprocess.Popen(['open', abs_path])
            else:
                import subprocess
                try:
                    subprocess.Popen(['evince', abs_path])
                except:
                    pass
            messagebox.showinfo("Документы", f"Чек оплаты: {receipt_file}\nАкт приёма будет создан после печати")
            dialog.destroy()
        
        # Кнопки
        button_frame = ttk.Frame(content, style='White.TFrame')
        button_frame.pack(fill='x', pady=(10, 0))
        
        styles.create_button(button_frame, "🖨 Печать всех документов", print_receipt, 'Success.TButton').pack(side='left', fill='x', expand=True, padx=(0, 5))
        styles.create_button(button_frame, "👁 Просмотр чека", preview_receipt, 'Primary.TButton').pack(side='left', fill='x', expand=True, padx=(5, 0))
    
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
        import platform
        
        selected = self.storage_tree.selection()
        if not selected:
            messagebox.showerror("Ошибка", "Выберите комплект для выдачи")
            return
        
        storage_id = self.storage_tree.item(selected[0])['values'][0]
        
        try:
            # Выдаём комплект (обновляет status='released' и released_date)
            storage = self.service.release_storage(storage_id)
            
            # Наряд остаётся со статусом 'paid' - информация о выдаче хранится в TireStorage
            
            if storage:
                self.print_release_receipt(storage)
                filepath = f"receipts/release_{storage.id}.pdf"
                
                # Диалог выбора действия
                dialog = tk.Toplevel(self.frame)
                dialog.title("Документ готов")
                dialog.geometry("400x200")
                dialog.configure(bg=styles.COLORS['bg'])
                
                content = ttk.Frame(dialog, style='White.TFrame')
                content.pack(fill='both', expand=True, padx=20, pady=20)
                
                title_label = styles.create_label(content, f"Акт выдачи #{storage.id} создан", 'CardHeading.TLabel')
                title_label.pack(pady=(0, 20))
                
                def print_doc():
                    if platform.system() == 'Windows':
                        os.startfile(os.path.abspath(filepath), "print")
                        messagebox.showinfo("Успех", f"Комплект #{storage.id} выдан.\nДокумент отправлен на печать")
                    else:
                        try:
                            import subprocess
                            subprocess.run(['lp', filepath], check=True)
                            messagebox.showinfo("Успех", f"Комплект #{storage.id} выдан.\nДокумент отправлен на печать")
                        except:
                            messagebox.showinfo("Успех", f"Комплект #{storage.id} выдан.\nДокумент: {filepath}")
                    dialog.destroy()
                    self.search_storage()
                
                def preview_doc():
                    abs_path = os.path.abspath(filepath)
                    if platform.system() == 'Windows':
                        os.startfile(abs_path)
                        messagebox.showinfo("Просмотр", f"Акт открыт для просмотра:\n{filepath}")
                    elif platform.system() == 'Darwin':
                        import subprocess
                        subprocess.Popen(['open', filepath])
                        messagebox.showinfo("Просмотр", f"Акт открыт для просмотра:\n{filepath}")
                    else:
                        # Linux (Replit) - используем evince
                        import subprocess
                        try:
                            subprocess.Popen(['evince', abs_path])
                            messagebox.showinfo("Просмотр", f"Акт открыт для просмотра:\n{abs_path}")
                        except Exception as e:
                            messagebox.showwarning("Информация", f"Акт создан и сохранён:\n{abs_path}\n\nОткройте его вручную в файловом менеджере.")
                    dialog.destroy()
                    self.search_storage()
                
                button_frame = ttk.Frame(content, style='White.TFrame')
                button_frame.pack(fill='x')
                
                styles.create_button(button_frame, "🖨 Печать", print_doc, 'Success.TButton').pack(side='left', fill='x', expand=True, padx=(0, 5))
                styles.create_button(button_frame, "👁 Просмотр", preview_doc, 'Primary.TButton').pack(side='left', fill='x', expand=True, padx=(5, 0))
            else:
                messagebox.showerror("Ошибка", "Комплект не найден")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))
    
    def print_receipt(self, storage, copies=2):
        if not os.path.exists('receipts'):
            os.makedirs('receipts')
        
        # Регистрируем семейство шрифтов DejaVu Sans
        font_name = register_dejavu_fonts()
        
        filename = f'receipts/storage_{storage.id}.pdf'
        c = canvas.Canvas(filename, pagesize=letter)
        
        width, height = letter
        
        for copy in range(copies):
            if copy > 0:
                c.showPage()
            
            # Заголовок
            y = height - 50
            c.setFont(font_name, 24)
            c.drawCentredString(width/2, y, "Шиномонтаж РИФ")
            
            y -= 30
            c.setFont(font_name, 16)
            c.drawCentredString(width/2, y, "АКТ ПРИЁМА ШИН НА ХРАНЕНИЕ")
            
            y -= 25
            c.setFont(font_name, 12)
            c.drawCentredString(width/2, y, f"№ {storage.id} от {storage.accepted_date.strftime('%d.%m.%Y %H:%M')}")
            
            y -= 40
            c.line(50, y, width-50, y)
            
            # Информация об автомобиле
            y -= 30
            c.setFont(font_name, 12)
            c.drawString(50, y, f"Номер автомобиля:")
            c.setFont(font_name, 14)
            c.drawString(250, y, storage.car_number)
            
            if storage.driver_license:
                y -= 25
                c.setFont(font_name, 12)
                c.drawString(50, y, f"Водительское удостоверение:")
                c.setFont(font_name, 14)
                c.drawString(250, y, storage.driver_license)
            
            y -= 30
            c.line(50, y, width-50, y)
            
            # Информация о шинах
            y -= 30
            c.setFont(font_name, 12)
            c.drawString(50, y, "Информация о шинах:")
            
            y -= 25
            c.drawString(50, y, f"Тип хранения:")
            c.drawString(250, y, storage.storage_type)
            
            y -= 20
            c.drawString(50, y, f"Диаметр:")
            c.drawString(250, y, storage.diameter)
            
            if storage.wheel_type:
                y -= 20
                c.drawString(50, y, f"Тип дисков:")
                c.drawString(250, y, storage.wheel_type)
            
            y -= 20
            c.drawString(50, y, f"Марка шины:")
            c.drawString(250, y, storage.brand or '-')
            
            y -= 20
            c.drawString(50, y, f"Износ:")
            c.drawString(250, y, storage.wear or '-')
            
            y -= 20
            c.drawString(50, y, f"Повреждения:")
            c.drawString(250, y, storage.damage or 'нет')
            
            if storage.comments:
                y -= 25
                c.drawString(50, y, f"Комментарии:")
                c.setFont(font_name, 11)
                c.drawString(250, y, storage.comments[:50])
            
            y -= 30
            c.line(50, y, width-50, y)
            
            # Стоимость
            y -= 35
            c.setFont(font_name, 16)
            c.drawString(50, y, "СТОИМОСТЬ ХРАНЕНИЯ:")
            c.drawRightString(width-50, y, f"{int(storage.price)} ₽")
            
            y -= 10
            c.line(50, y, width-50, y)
            
            # Подпись и экземпляр
            y -= 50
            c.setFont(font_name, 11)
            c.drawString(50, y, "Принял: _________________")
            c.drawRightString(width-50, y, "Сдал: _________________")
            
            y = 80
            c.setFont(font_name, 10)
            c.drawCentredString(width/2, y, f"Экземпляр {copy + 1} из {copies}")
        
        c.save()
    
    def print_release_receipt(self, storage):
        if not os.path.exists('receipts'):
            os.makedirs('receipts')
        
        # Регистрируем семейство шрифтов DejaVu Sans
        font_name = register_dejavu_fonts()
        
        filename = f'receipts/release_{storage.id}.pdf'
        c = canvas.Canvas(filename, pagesize=letter)
        
        width, height = letter
        
        # Заголовок
        y = height - 50
        c.setFont(font_name, 24)
        c.drawCentredString(width/2, y, "Шиномонтаж РИФ")
        
        y -= 30
        c.setFont(font_name, 16)
        c.drawCentredString(width/2, y, "АКТ ВЫДАЧИ ШИН С ХРАНЕНИЯ")
        
        y -= 25
        c.setFont(font_name, 12)
        c.drawCentredString(width/2, y, f"№ {storage.id}")
        
        y -= 40
        c.line(50, y, width-50, y)
        
        # Даты
        y -= 30
        c.setFont(font_name, 12)
        c.drawString(50, y, f"Дата приёма:")
        c.drawString(250, y, storage.accepted_date.strftime('%d.%m.%Y %H:%M'))
        
        y -= 20
        c.drawString(50, y, f"Дата выдачи:")
        c.setFont(font_name, 14)
        c.drawString(250, y, storage.released_date.strftime('%d.%m.%Y %H:%M'))
        
        y -= 30
        c.line(50, y, width-50, y)
        
        # Информация об автомобиле
        y -= 30
        c.setFont(font_name, 12)
        c.drawString(50, y, f"Номер автомобиля:")
        c.setFont(font_name, 14)
        c.drawString(250, y, storage.car_number)
        
        if storage.driver_license:
            y -= 25
            c.setFont(font_name, 12)
            c.drawString(50, y, f"Водительское удостоверение:")
            c.setFont(font_name, 14)
            c.drawString(250, y, storage.driver_license)
        
        y -= 30
        c.line(50, y, width-50, y)
        
        # Информация о шинах
        y -= 30
        c.setFont(font_name, 12)
        c.drawString(50, y, "Информация о шинах:")
        
        y -= 25
        c.drawString(50, y, f"Тип хранения:")
        c.drawString(250, y, storage.storage_type)
        
        y -= 20
        c.drawString(50, y, f"Диаметр:")
        c.drawString(250, y, storage.diameter)
        
        if storage.wheel_type:
            y -= 20
            c.drawString(50, y, f"Тип дисков:")
            c.drawString(250, y, storage.wheel_type)
        
        y -= 20
        c.drawString(50, y, f"Марка шины:")
        c.drawString(250, y, storage.brand or '-')
        
        if storage.comments:
            y -= 25
            c.drawString(50, y, f"Комментарии:")
            c.setFont(font_name, 11)
            c.drawString(250, y, storage.comments[:50])
        
        y -= 30
        c.line(50, y, width-50, y)
        
        # Стоимость
        y -= 35
        c.setFont(font_name, 16)
        c.drawString(50, y, "СТОИМОСТЬ ХРАНЕНИЯ:")
        c.drawRightString(width-50, y, f"{int(storage.price)} ₽")
        
        y -= 10
        c.line(50, y, width-50, y)
        
        # Подпись
        y -= 50
        c.setFont(font_name, 11)
        c.drawString(50, y, "Выдал: _________________")
        c.drawRightString(width-50, y, "Получил: _________________")
        
        y = 80
        c.setFont(font_name, 12)
        c.drawCentredString(width/2, y, "Шины выданы владельцу")
        
        c.save()
