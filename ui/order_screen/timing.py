"""
Учёт времени работы и автосохранение состава наряда.

Плановое время, отсчёт фактического, автосохранение состава и
показ мастеров, занятых на наряде.
"""
from tkinter import messagebox

from utils import retry_after_rollback
from logger import log

class OrderTimingMixin:
    """Время наряда и сохранение его состава."""

    def refresh_time_display(self):
        """
        Показать плановое время и, если состав менялся, каким оно станет.

        Мастер должен видеть, что его правки ещё не учтены в очереди —
        иначе он решит, что программа сломалась, или уйдёт, не сохранив.
        """
        try:
            saved = self.order.planned_minutes or 0
            current = self.order_service.calculate_planned_minutes(self.order.id)
        except Exception as e:
            log.error(f"Не удалось посчитать время наряда: {e}")
            return

        self.time_label.config(text=f"Время: {saved} мин" if saved else "Время: не сохранено")

        if current != saved:
            self.unsaved_label.config(
                text=f"⚠ не сохранено — станет {current} мин")
            self.schedule_autosave()
        else:
            self.unsaved_label.config(text="")
            self.cancel_autosave()

    def schedule_autosave(self):
        """
        Отложенное сохранение состава: мастер обязательно когда-нибудь
        забудет нажать кнопку, а тогда очередь занизит время для ВСЕХ
        ожидающих, а не только для этого наряда.

        Срабатывает только когда правки прекратились, поэтому скачков
        не создаёт: состав к этому моменту уже устоялся.
        """
        from services.settings_service import SettingsService

        self.cancel_autosave()
        try:
            minutes = SettingsService(self.db).get_int('order_autosave_minutes')
        except Exception:
            minutes = 3

        if minutes <= 0:
            return  # автосохранение выключено настройкой

        self._autosave_job = self.frame.after(
            minutes * 60 * 1000, lambda: self.save_composition(silent=True))

    def cancel_autosave(self):
        if self._autosave_job is not None:
            try:
                self.frame.after_cancel(self._autosave_job)
            except Exception:
                pass
            self._autosave_job = None

    def save_composition(self, silent=False):
        """
        Зафиксировать состав наряда и пересчитать плановое время.

        Позиции в базу пишутся сразу при добавлении — кнопка на это не влияет.
        Она означает «состав согласован с клиентом, можно менять время».
        """
        self.cancel_autosave()
        try:
            minutes = self.order_service.save_order_composition(self.order.id)
            self.db.refresh(self.order)
            self.refresh_time_display()
            if not silent:
                messagebox.showinfo("Наряд сохранён",
                                    f"Состав согласован.\nПлановое время: {minutes} мин")
        except Exception as e:
            self.db.rollback()
            if not silent:
                messagebox.showerror("Ошибка", f"Не удалось сохранить наряд: {e}")
            else:
                log.error(f"Автосохранение наряда не удалось: {e}")

    def update_employees_display(self):
        """Обновляет отображение сотрудников, работающих над нарядом"""
        from models import SalaryTransaction

        def collect():
            """
            Вернуть (текст, цвет) для строки мастеров.

            Подпись «Мастера:» обязательна: без неё в наряде висели голые
            «№1, №2», и понять, что это номера работающих сотрудников,
            было невозможно.
            """
            if self.order.status == 'paid':
                # По оплаченному наряду мастера известны из начислений
                transactions = self.db.query(SalaryTransaction).filter(
                    SalaryTransaction.work_order_id == self.order.id
                ).all()
                if not transactions:
                    return '', '#64748b'
                ids = [str(t.employee_id) for t in transactions]
                return "Мастера: №" + ", №".join(ids), '#64748b'

            # По неоплаченному — из тех, кто был на смене при создании
            if self.order.employee_ids:
                ids = self.order.employee_ids.split(',')
                return "Мастера: №" + ", №".join(ids), '#059669'

            return "Мастера не назначены", '#dc2626'

        try:
            text, colour = retry_after_rollback(self.db, collect)
        except Exception as e:
            log.error(f"Не удалось показать сотрудников наряда: {e}")
            text, colour = '', '#64748b'

        self.employees_label.config(text=text, foreground=colour)
