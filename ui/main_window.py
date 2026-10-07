import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from ui.employees_tab import EmployeesTab
from ui.orders_tab import OrdersTab
from ui.clients_tab import ClientsTab
from ui.appointments_tab import AppointmentsTab
from ui.tire_storage_tab import TireStorageTab
from ui.paint_tab import PaintTab
from ui.price_list_tab import PriceListTab
from ui.statistics_tab import StatisticsTab
from config import get_db
from models import Settings
import styles
from logger import log


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.root.geometry("1440x950")
        self.root.minsize(1180, 720)

        styles.apply_modern_styles(self.root)

        # Регистрируем DejaVu Sans шрифт для кириллицы на Linux
        styles.register_dejavu_font()

        self.db = get_db()

        # Название берём из реквизитов: переименовались — переименовалось
        # и окно, без пересборки программы
        from services.company_service import get_company
        company_name = get_company(self.db).name or 'Шиномонтаж'
        self.root.title(f"{company_name} — учёт работ")

        # Верхняя полоса с названием
        self.app_bar = styles.create_app_bar(self.root, company_name.upper())
        self.app_bar.pack(fill='x')

        # Навигация вместо стандартных вкладок: выбранный раздел
        # отмечается цветом и полоской, а не приподнятой коробкой
        self.nav = styles.NavBar(self.root, on_select=self.on_section_change)
        self.nav.pack(fill='x')

        self.content = tk.Frame(self.root, bg=styles.COLORS['bg'])
        self.content.pack(fill='both', expand=True)

        self.employees_tab = EmployeesTab(self.content, self.db)
        self.orders_tab = OrdersTab(self.content, self.db, self.employees_tab)
        self.appointments_tab = AppointmentsTab(self.content, self.db, self.orders_tab)
        self.clients_tab = ClientsTab(self.content, self.db)
        # История нарядов теперь подраздел внутри «Клиентов»
        self.history_tab = self.clients_tab.history_tab
        self.tire_storage_tab = TireStorageTab(self.content, self.db)
        self.paint_tab = PaintTab(self.content, self.db)
        self.statistics_tab = StatisticsTab(self.content, self.db)
        self.price_list_tab = PriceListTab(self.content, self.db)

        self.nav.add('Сотрудники', self.employees_tab.frame)
        self.nav.add('Наряды', self.orders_tab.frame)
        self.nav.add('Запись', self.appointments_tab.frame)
        self.nav.add('Клиенты', self.clients_tab.frame)
        self.nav.add('Хранение шин', self.tire_storage_tab.frame)
        self.nav.add('Покраска', self.paint_tab.frame)
        self.nav.add('Отчёты', self.statistics_tab.frame)
        self.nav.add('Прайс-лист', self.price_list_tab.frame)

        self.nav.select(1)  # открываем сразу на нарядах — основная работа
        self.refresh_shift_status()

        # Забытую смену закрываем сразу при запуске и потом раз в 10 минут:
        # программу могут не выключать сутками
        self.check_overdue_shift()
        self.schedule_shift_check()

        # Обмен с сервером приложения. Выключен, пока сервера нет,
        # и никак не мешает работе цеха, если связь пропала
        self.sync_failures = 0
        self.schedule_sync(first=True)

    def schedule_shift_check(self):
        self.root.after(10 * 60 * 1000, self._periodic_shift_check)

    # ------------------------------------------------------------------
    # Обмен с сервером приложения
    # ------------------------------------------------------------------

    def schedule_sync(self, first=False):
        """
        Запустить обмен по расписанию.

        Первый раз — через полминуты после запуска: сначала пусть
        откроется окно, а уже потом программа лезет в сеть.
        """
        from services.sync_service import INTERVAL_MINUTES

        delay = 30 * 1000 if first else INTERVAL_MINUTES * 60 * 1000
        self.root.after(delay, self._periodic_sync)

    def _periodic_sync(self):
        try:
            from services.sync_service import SyncService

            service = SyncService(self.db)
            if service.is_enabled():
                service.run_in_background(on_done=self._sync_done)
        except Exception as e:
            log.error(f"Не удалось запустить обмен: {e}")

        self.schedule_sync()

    def _sync_done(self, success, result):
        """
        Итог обмена. Вызывается из другого потока — только через after.

        Ругаться на каждый неудачный обмен нельзя: у цеха может просто
        не быть интернета, и всплывающее окно раз в две минуты сведёт
        приёмщика с ума. Поэтому молчим, пока сбои не станут упорными.
        """
        def show():
            if success:
                if self.sync_failures:
                    log.info("Связь с сервером восстановлена")
                self.sync_failures = 0
                new = result.get('new_storage_requests', 0)
                if new:
                    log.info(f"Из приложения пришло заявок на комплекты: {new}")
            else:
                self.sync_failures += 1
                if self.sync_failures == 5:
                    log.warning(f"Обмен не удаётся пятый раз подряд: {result}")

        try:
            self.root.after(0, show)
        except Exception:
            # Окно уже закрыли — обновлять нечего
            pass

    def _periodic_shift_check(self):
        self.check_overdue_shift()
        self.schedule_shift_check()

    def check_overdue_shift(self):
        """
        Закрыть смену, которую забыли закрыть накануне, и отправить сводку.

        Сбой здесь не должен мешать работе: если закрыть не удалось,
        смена просто останется открытой.
        """
        try:
            from services.shift_report_service import ShiftReportService

            closed = ShiftReportService(self.db).autoclose_if_needed()
            if closed:
                log.info(f"Смена №{closed.id} закрыта автоматически")
                self.refresh_shift_status()
                try:
                    self.employees_tab.update_shift_status()
                    self.employees_tab.refresh_active_shifts()
                except Exception as e:
                    log.error(f"Не удалось обновить экран сотрудников: {e}")
        except Exception as e:
            log.error(f"Проверка забытой смены не удалась: {e}")

    def on_section_change(self, index):
        """При переходе между разделами обновляем строку состояния смены."""
        self.refresh_shift_status()

        # Услугу могли только что добавить в прайс-лист — вернувшись
        # в наряды, мастер должен увидеть её кнопку сразу
        if self.nav.title_at(index) == 'Наряды':
            try:
                self.orders_tab.load_service_buttons()
            except Exception as e:
                log.warning(f"Не удалось обновить кнопки услуг: {e}")

    def refresh_shift_status(self):
        """Показать в верхней полосе, открыта ли смена и сколько постов."""
        try:
            from services.shift_service import ShiftService

            shift = ShiftService(self.db).get_current_shift()
            if shift:
                text = f"Смена открыта  ·  постов: {shift.open_posts}"
            else:
                text = "Смена не открыта"
            self.app_bar.subtitle_label.config(text=text)
        except Exception as e:
            log.error(f"Не удалось показать состояние смены: {e}")
