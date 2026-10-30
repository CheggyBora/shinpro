"""
Оплата наряда и печать чека.

Здесь же выбор между чеком на A4 и чеком на термопринтере,
предпросмотр и разбор ошибок печати.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from logger import log
import styles

class OrderPaymentMixin:
    """Приём оплаты и выдача документов."""

    def process_payment(self):
        import os
        import platform
        
        # Пробить без открытой смены нельзя: непонятно, каким днём провести
        from services.shift_service import ShiftService
        if ShiftService(self.db).get_current_shift() is None:
            messagebox.showwarning("Смена закрыта",
                                   "Откройте смену: наряд проводится в той смене, "
                                   "в которой закрыли машину.")
            return

        # Мастеров выбирают на наряд, а их нет — делить шиномонтаж некому
        # Бывает и без тумблера: наряд создали, когда на смене ещё никто
        # не отметился, — раньше такой нельзя было пробить вовсе (ревью 26.10.2026)
        if not self.order.employee_ids and self.salary_service._work_of(self.order.id):
            messagebox.showwarning("Мастера наряда",
                                   "В наряде нет мастеров — отметьте, кто делал шиномонтаж, "
                                   "и нажмите «Пробить» ещё раз.")
            self.choose_masters()
            return

        missing = self.salary_service.unassigned_wash(self.order.id)
        if missing:
            messagebox.showwarning("Кто делал",
                                   "Выберите, кто делал: " + ", ".join(missing) +
                                   "\n(двойной щелчок по колонке «Кто делал» "
                                   "или «Всё на: … ▾» в блоке мойки)")
            return

        total = self.order_service.calculate_total(self.order.id)
        
        dialog = tk.Toplevel(self.frame)
        dialog.title("Оплата")
        dialog.geometry("440x420")
        dialog.configure(bg=styles.COLORS['bg'])
        styles.center_window(dialog, self.frame.winfo_toplevel())
        
        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        total_label = styles.create_label(content, f"Сумма к оплате: {total:.2f} руб.", 'CardHeading.TLabel')
        total_label.pack(pady=(0, 20))
        total_label.configure(font=(styles.DEFAULT_FONT, 16, 'bold'), foreground=styles.COLORS['primary'])
        
        payment_var = tk.StringVar(value='cash')
        
        radio_frame = ttk.Frame(content, style='White.TFrame')
        radio_frame.pack(fill='x', pady=(0, 20))
        
        for text, value in (("Наличные", 'cash'), ("Безналичный расчёт", 'card'),
                            ("Раздельно: часть наличными, часть картой", 'mixed')):
            ttk.Radiobutton(radio_frame, text=text, variable=payment_var, value=value,
                            command=lambda: show_split()).pack(anchor='w', pady=5)

        # Раздельно (решение владельца 30.10.2026): вписывают, сколько
        # наличными, — картой остаток, считается сам
        split_frame = ttk.Frame(content, style='White.TFrame')
        cash_row = ttk.Frame(split_frame, style='White.TFrame')
        cash_row.pack(fill='x', pady=3)
        styles.create_label(cash_row, "Наличными:", 'Card.TLabel').pack(side='left')
        cash_var = tk.StringVar()
        cash_entry = ttk.Entry(cash_row, textvariable=cash_var, width=12,
                               font=(styles.DEFAULT_FONT, 12))
        cash_entry.pack(side='left', padx=8)
        styles.create_label(cash_row, "руб.", 'Card.TLabel').pack(side='left')
        card_label = styles.create_label(split_frame, "", 'Card.TLabel')
        card_label.configure(font=(styles.DEFAULT_FONT, 11, 'bold'))
        card_label.pack(anchor='w', pady=(6, 0))
        split_hint = styles.create_label(split_frame, "", 'Card.TLabel')
        split_hint.configure(foreground=styles.COLORS['text_secondary'], wraplength=380, justify='left')
        split_hint.pack(anchor='w', pady=(4, 0))

        def cash_part():
            """Сколько наличными или None, если вписано не то."""
            try:
                value = round(float(cash_var.get().replace(',', '.').replace(' ', '')), 2)
            except ValueError:
                return None
            return value if 0 < value < round(total, 2) else None

        def update_split(*_):
            cash = cash_part()
            if cash is None:
                card_label.configure(text="Картой: —", foreground=styles.COLORS['text_secondary'])
                split_hint.configure(text=f"Впишите наличные: больше 0 и меньше {total:.2f}")
                return
            card_label.configure(text=f"Картой: {total - cash:.2f} руб.",
                                 foreground=styles.COLORS['primary'])
            split_hint.configure(text=f"Проведите {total - cash:.2f} на терминале. "
                                      f"В кассу смены — только {cash:.2f} наличными.")

        def show_split():
            if payment_var.get() == 'mixed':
                split_frame.pack(fill='x', pady=(0, 10), before=button_frame)
                update_split()
                cash_entry.focus_set()
            else:
                split_frame.pack_forget()

        cash_var.trace_add('write', update_split)
        
        def pay_and_print():
            cash_amount = None
            if payment_var.get() == 'mixed':
                cash_amount = cash_part()
                if cash_amount is None:
                    messagebox.showwarning(
                        "Раздельная оплата",
                        f"Впишите, сколько наличными: больше 0 и меньше {total:.2f} руб. "
                        f"Остаток пойдёт картой.", parent=dialog)
                    cash_entry.focus_set()
                    return

            # Блокируем кнопку, чтобы двойной клик не запустил оплату дважды
            pay_button.config(state='disabled')

            # ШАГ 1. Оплата. Если она не прошла — наряд не изменён,
            # диалог остаётся открытым, кассир может попробовать снова.
            try:
                # Оплата означает окончательно согласованный состав:
                # фиксируем время и завершаем работы, даже если мастер
                # не нажимал «Сохранить наряд»
                self.order_service.save_order_composition(self.order.id)
                # Пока окно было открыто, в наряд могли добавить услугу —
                # тогда клиент заплатил бы старую сумму за новый состав
                now = self.order_service.calculate_total(self.order.id)
                if abs(now - total) > 0.009:
                    pay_button.config(state='normal')
                    dialog.destroy()
                    messagebox.showwarning(
                        "Сумма изменилась",
                        f"Пока было открыто окно оплаты, наряд поменялся: было "
                        f"{total:.2f}, стало {now:.2f} руб. Откройте оплату заново.")
                    return
                self.order_service.finish_work(self.order.id)
                self.cancel_autosave()

                self.salary_service.process_payment(self.order.id, payment_var.get(), total,
                                                    cash_amount)
                self.db.refresh(self.order)
            except Exception as e:
                log.error(f"Ошибка оплаты: {e}")
                import traceback
                traceback.print_exc()
                pay_button.config(state='normal')
                messagebox.showerror("Ошибка оплаты", str(e))
                return

            # Оплата УЖЕ проведена и записана в базу. Дальше идут только
            # печать и оформление — их сбой не должен выглядеть как сбой
            # оплаты и не должен давать возможность нажать "Оплатить" ещё раз.
            dialog.destroy()

            # Обновляем таблицу сотрудников (зарплату за смену)
            try:
                if self.parent_orders_tab and self.parent_orders_tab.employees_tab:
                    self.parent_orders_tab.employees_tab.refresh_employees()
            except Exception as e:
                log.error(f"Не удалось обновить таблицу сотрудников: {e}")

            # ШАГ 2. Формируем чек
            receipt_file = None
            receipt_error = None
            try:
                items = self.order_service.get_order_items(self.order.id)

                # Если подключён термопринтер — печатаем узкий чек,
                # иначе обычный лист A4
                from services.settings_service import SettingsService
                settings = SettingsService(self.db)
                if settings.get('thermal_receipt_enabled', '0') == '1':
                    width = settings.get_int('thermal_receipt_width', 58)
                    receipt_file = self.print_service.generate_thermal_receipt(
                        self.order, items, total, width_mm=width)
                else:
                    receipt_file = self.print_service.generate_receipt(
                        self.order, items, total)
            except Exception as e:
                receipt_error = str(e)
                log.error(f"Не удалось сформировать чек: {e}")
                import traceback
                traceback.print_exc()

            # ШАГ 3. Пытаемся отправить на печать
            print_success = False
            print_error = None

            if receipt_file:
                if platform.system() == 'Windows':
                    try:
                        # Пытаемся отправить на принтер
                        os.startfile(receipt_file, "print")
                        print_success = True
                    except Exception as print_err:
                        # Если не удалось печатать, просто откроем PDF
                        print_error = str(print_err)
                        log.error(f"Не удалось отправить на печать: {print_err}")
                        try:
                            os.startfile(receipt_file)  # Открыть для просмотра
                            log.debug("PDF открыт для просмотра")
                        except Exception as open_err:
                            log.error(f"Не удалось открыть PDF: {open_err}")
                else:
                    # Для Linux/Mac используем lp
                    try:
                        import subprocess
                        subprocess.run(['lp', receipt_file], check=True)
                        print_success = True
                    except Exception as print_err:
                        print_error = str(print_err)

            # ШАГ 4. Закрываем вкладку наряда
            try:
                self.close_callback(self.order.id)
                log.debug(f"Вкладка наряда #{self.order.id} успешно закрыта")
            except Exception as e:
                log.error(f"Ошибка закрытия вкладки наряда #{self.order.id}: {e}")

            # ШАГ 5. Показываем результат (в самом конце!)
            if receipt_error:
                messagebox.showwarning(
                    "Оплата проведена, чек не создан",
                    f"Оплата наряда №{self.order.id} на {total:.2f} руб. проведена "
                    f"и сохранена в базе.\n\n"
                    f"НЕ удалось сформировать чек:\n{receipt_error}\n\n"
                    f"Повторно оплачивать наряд НЕ нужно. "
                    f"Чек можно распечатать из вкладки «История автомобиля»."
                )
            elif print_success:
                messagebox.showinfo("Успех", "Оплата проведена!\nЧек отправлен на печать")
            elif print_error:
                # Если была ошибка печати, но PDF открыт
                messagebox.showinfo("Успех",
                    f"Оплата проведена!\n\n"
                    f"PDF-чек открыт для просмотра.\n"
                    f"Распечатайте его через Ctrl+P\n\n"
                    f"Путь: {receipt_file}")
            else:
                messagebox.showinfo("Успех", f"Оплата проведена!\nЧек сохранён: {receipt_file}")
        
        def preview_only():
            try:
                items = self.order_service.get_order_items(self.order.id)
                receipt_file = self.print_service.generate_receipt(self.order, items, total)
                abs_path = os.path.abspath(receipt_file)
                
                # Просто открыть PDF для просмотра
                if platform.system() == 'Windows':
                    os.startfile(receipt_file)
                    messagebox.showinfo("Просмотр", f"Чек открыт для просмотра:\n{receipt_file}")
                elif platform.system() == 'Darwin':
                    # macOS
                    import subprocess
                    subprocess.Popen(['open', receipt_file])
                    messagebox.showinfo("Просмотр", f"Чек открыт для просмотра:\n{receipt_file}")
                else:
                    # Linux (Replit) - используем evince
                    import subprocess
                    try:
                        subprocess.Popen(['evince', abs_path])
                        messagebox.showinfo("Просмотр", f"Чек открыт для просмотра:\n{abs_path}")
                    except Exception as e:
                        messagebox.showwarning("Информация", f"Чек создан и сохранён:\n{abs_path}\n\nОткройте его вручную в файловом менеджере.")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))
        
        # Две кнопки: Оплатить (печать) и Просмотр
        button_frame = ttk.Frame(content, style='White.TFrame')
        button_frame.pack(fill='x', pady=(10, 0))
        
        pay_button = styles.create_button(button_frame, "Оплатить", pay_and_print, 'Success.TButton')
        pay_button.pack(side='left', fill='x', expand=True, padx=(0, 5))
        styles.create_button(button_frame, "Просмотр", preview_only, 'Primary.TButton').pack(side='left', fill='x', expand=True, padx=(5, 0))
