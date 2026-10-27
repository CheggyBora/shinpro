import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from ui.employees_tab import EmployeesTab
from ui.orders_tab import OrdersTab
from ui.clients_tab import ClientsTab
from ui.appointments_tab import AppointmentsTab
from ui.tire_storage_tab import TireStorageTab
from ui.paint_tab import PaintTab
from ui.settings_tab import SettingsTab
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

        # Вставка и копирование при русской раскладке. Без этого Ctrl+V
        # в полях не работает: Tkinter ждёт латинскую V, а система при
        # русской раскладке сообщает ему про Ctrl+М
        from ui.clipboard import enable as enable_clipboard

        enable_clipboard(self.root)

        # Регистрируем DejaVu Sans шрифт для кириллицы на Linux
        styles.register_dejavu_font()

        self.db = get_db()

        # Название берём из реквизитов: переименовались — переименовалось
        # и окно, без пересборки программы
        from services.company_service import get_company
        company_name = get_company(self.db).name or 'Шиномонтаж'
        from config import offline_test_mode
        self.root.title(f"{company_name} — учёт работ"
                        + (" — ТЕСТ БЕЗ СВЯЗИ" if offline_test_mode() else ""))

        # Верхняя полоса с названием
        self.app_bar = styles.create_app_bar(self.root, company_name.upper())
        self.app_bar.pack(fill='x')
        # Переключатель «Шиномонтаж | Мойка» — когда работают оба направления
        self.mode_switch = tk.Frame(self.app_bar.winfo_children()[0], bg=styles.COLORS['primary_dark'])
        self.mode_switch.pack(side='left', padx=(24, 0))

        # Навигация вместо стандартных вкладок: выбранный раздел
        # отмечается цветом и полоской, а не приподнятой коробкой
        self.nav = styles.NavBar(self.root, on_select=self.on_section_change)
        self.nav.pack(fill='x')

        self.content = tk.Frame(self.root, bg=styles.COLORS['bg'])
        self.content.pack(fill='both', expand=True)

        self.employees_tab = EmployeesTab(self.content, self.db)
        self.orders_tab = OrdersTab(self.content, self.db, self.employees_tab)
        self.appointments_tab = AppointmentsTab(self.content, self.db, self.orders_tab)
        from ui.calendar_tab import CalendarTab
        self.calendar_tab = CalendarTab(self.content, self.db)
        self.calendar_tab.on_changed = lambda: self._calendar_refresh()
        self.orders_tab.app = self
        self.clients_tab = ClientsTab(self.content, self.db)
        # История нарядов теперь подраздел внутри «Клиентов»
        self.history_tab = self.clients_tab.history_tab
        # Гарантийная переделка открывается в «Нарядах»
        self.history_tab.on_open_order = self._open_warranty
        self.tire_storage_tab = TireStorageTab(self.content, self.db)
        self.paint_tab = PaintTab(self.content, self.db)
        self.statistics_tab = StatisticsTab(self.content, self.db)
        self.price_list_tab = PriceListTab(self.content, self.db)
        self.settings_tab = SettingsTab(self.content, self.db)
        from ui.stock_tab import StockTab
        self.stock_tab = StockTab(self.content, self.db)
        from ui.cash_tab import CashTab
        self.cash_tab = CashTab(self.content, self.db)
        self.stock_tab.on_changed = lambda: self._calendar_badge()

        self.nav.add('Сотрудники', self.employees_tab.frame)
        self.nav.add('Наряды', self.orders_tab.frame)
        self.nav.add('Запись', self.appointments_tab.frame)
        self.nav.add('Календарь', self.calendar_tab.frame)
        self.nav.add('Клиенты', self.clients_tab.frame)
        self.nav.add('Хранение шин', self.tire_storage_tab.frame)
        self.nav.add('Покраска', self.paint_tab.frame)
        self.nav.add('Склад', self.stock_tab.frame)
        self.nav.add('Касса', self.cash_tab.frame)
        self.nav.add('Отчёты', self.statistics_tab.frame)
        self.nav.add('Прайс-лист', self.price_list_tab.frame)
        self.nav.add('Настройки', self.settings_tab.frame)

        # Наряд из живой очереди открылся — показываем «Наряды»
        self.appointments_tab.queue.on_order_opened = lambda: self.nav.select(1)
        # Приёмщик позвал, открыл наряд, убрал — сервер узнаёт сразу:
        # человек у въезда смотрит на свою страницу
        self.appointments_tab.queue.on_changed =             lambda: self.root.after(1500, self._start_live_sync)
        self.live_running = None
        self.live_result = 0
        self.root.after(5 * 1000, self._live_tick)

        self.draw_mode_switch()
        if self.orders_tab.mode != 'tire':
            self.appointments_tab.set_direction(self.orders_tab.mode)
        self.apply_mode()
        from services import directions as _directions
        _directions.ON_CHANGE = self.directions_changed

        # «Всё по машине» → «Создать наряд»
        import ui.car_info
        ui.car_info.ON_NEW_ORDER = self.orders_tab.open_plate
        self._calendar_badge()

        # Неоплаченные наряды прошлых смен — снова на экран: их пробьют
        # в той смене, когда закроют машину
        try:
            for order in self.orders_tab.order_service.unpaid_orders():
                self.orders_tab.open_order_tab(order)
        except Exception as e:
            self.db.rollback()
            log.error(f"Не удалось открыть неоплаченные наряды: {e}")

        self.nav.select(1)  # открываем сразу на нарядах — основная работа
        self.refresh_shift_status()

        # Забытую смену закрываем сразу при запуске и потом раз в 10 минут:
        # программу могут не выключать сутками
        self.check_overdue_shift()
        self.schedule_shift_check()

        # Обмен с сервером приложения. Выключен, пока сервера нет,
        # и никак не мешает работе цеха, если связь пропала
        self.sync_failures = 0
        self.sync_running = False
        self.sync_soon = None
        self.schedule_sync(first=True)

        # Срочная досылка: после важных изменений цех выходит на связь
        # сам, не дожидаясь расписания
        from services import sync_nudge

        sync_nudge.set_runner(self.sync_soon_after)

        # Календарь и Telegram: правка в цеху уходит сразу, без ожидания
        from services import calendar_service, telegram_outbox
        self.telegram_running = None
        calendar_service.ON_CHANGE = lambda: self.root.after(1500, self._start_live_sync)
        telegram_outbox.ON_QUEUED = lambda: self.root.after(300, self._start_telegram)

    # ------------------------------------------------------------------
    # Живая очередь: места по QR (docs/live_queue.md)
    # ------------------------------------------------------------------

    LIVE_SECONDS = 20

    def _live_tick(self):
        if not self._start_live_sync():
            # Обмена нет (не настроен или идёт) — очередь всё равно
            # живёт: без интернета она тоже должна звать и снимать вызовы
            if self.live_running is None:
                self._queue_housekeeping()
                self._calendar_refresh()
        self._start_telegram()
        self._start_arrivals()
        self.root.after(self.LIVE_SECONDS * 1000, self._live_tick)

    # ------------------------------------------------------------------
    # Машина с телефона (docs/order_photo.md)
    # ------------------------------------------------------------------

    def _start_arrivals(self):
        """Спросить сервер, не сняли ли машину на телефон, — в своём потоке."""
        running = getattr(self, 'arrivals_running', None)
        if running is not None and running.is_alive():
            return False
        try:
            from services.sync_service import SyncService
            if not SyncService(self.db).is_enabled() or self.orders_tab.shift_service.get_current_shift() is None:
                return False
        except Exception:
            self.db.rollback()
            return False

        import threading

        def worker():
            from config import SessionLocal
            from services.arrival_service import ArrivalService
            db = SessionLocal()
            try:
                found = ArrivalService(db).pending()
            except Exception as e:
                log.warning(f"Машины с телефона не получены: {e}")
                found = []
            finally:
                db.close()
            if found:
                self.root.after(0, lambda: self._show_arrivals(found))

        self.arrivals_running = threading.Thread(target=worker, daemon=True)
        self.arrivals_running.start()
        return True

    def _show_arrivals(self, found):
        """Открыть окно создания для первой новой машины; остальные — следом."""
        seen = self.__dict__.setdefault('arrivals_seen', set())
        fresh = [a for a in found if a['id'] not in seen]
        if not fresh:
            return
        # Окно создания уже открыто — не мешаем, следующая машина
        # покажется при следующем обмене
        open_dialog = getattr(self.orders_tab, 'create_dialog', None)
        if open_dialog is not None and open_dialog.winfo_exists():
            return
        arrival = fresh[0]
        seen.add(arrival['id'])
        try:
            self.orders_tab.open_arrival(arrival)
        except Exception as e:
            self.db.rollback()
            log.error(f"Окно наряда для машины с телефона не открылось: {e}")

    def _start_telegram(self):
        """Дослать сообщения о складе и покраске — в своём потоке."""
        if self.telegram_running is not None and self.telegram_running.is_alive():
            return False
        try:
            from services import telegram_outbox
            if not telegram_outbox.pending(self.db):
                return False
        except Exception:
            self.db.rollback()
            return False

        import threading

        def worker():
            from config import SessionLocal
            from services import telegram_outbox
            db = SessionLocal()
            try:
                telegram_outbox.flush(db)
            except Exception as e:
                log.warning(f"Сообщения в Telegram не дослались: {e}")
            finally:
                db.close()

        self.telegram_running = threading.Thread(target=worker, daemon=True)
        self.telegram_running.start()
        return True

    def _master_refresh(self):
        """
        Мастер нажал «Начал» / «Готово» или клиент согласился на работу —
        обновить открытые вкладки этих нарядов и сказать приёмщику.
        """
        result = getattr(self, 'master_result', None)
        self.master_result = None
        if not result:
            return
        try:
            for order_id in result.get('orders') or ():
                widget = self.orders_tab.active_orders.get(order_id)
                if widget is None:
                    continue
                self.db.refresh(widget.order)
                for name in ('refresh_items', 'refresh_time_display', 'refresh_told'):
                    method = getattr(widget, name, None)
                    if method is not None:
                        method()
        except Exception as e:
            self.db.rollback()
            log.warning(f"Наряд после нажатия мастера не обновился: {e}")
        for title, text in result.get('notes') or ():
            self._master_note(title, text)

    def _master_note(self, title, text):
        """
        Окно поверх программы, но не блокирующее: приёмщик может дописать
        наряд и закрыть его, когда прочтёт. Звонок клиенту — его дело.
        """
        window = tk.Toplevel(self.root)
        window.title(title)
        window.configure(bg=styles.COLORS['bg_card'])
        window.attributes('-topmost', True)
        body = ttk.Frame(window, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=20, pady=16)
        styles.create_label(body, title, 'CardHeading.TLabel').pack(anchor='w', pady=(0, 8))
        tk.Label(body, text=text, justify='left', wraplength=440,
                 font=(styles.DEFAULT_FONT, 11), bg=styles.COLORS['bg_card'],
                 fg=styles.COLORS['text']).pack(anchor='w')
        styles.create_button(body, "Понятно", window.destroy,
                             'Primary.TButton').pack(anchor='e', pady=(14, 0))
        window.bind('<Escape>', lambda e: window.destroy())
        try:
            window.bell()
        except Exception:
            pass

    def _calendar_refresh(self):
        """Лента задач над нарядами, календарь и счётчик в меню."""
        try:
            from models import CalendarTask
            for obj in list(self.db.identity_map.values()):
                if isinstance(obj, CalendarTask):
                    self.db.expire(obj)
            self.orders_tab.refresh_tasks()
            if self.calendar_tab.frame.winfo_ismapped():
                self.calendar_tab.load()
            self._calendar_badge()
        except Exception as e:
            self.db.rollback()
            log.warning(f"Календарь не обновился: {e}")

    # ------------------------------------------------------------------
    # Направления: шиномонтаж и мойка (services/directions.py)
    # ------------------------------------------------------------------

    def draw_mode_switch(self):
        from services import directions
        for child in self.mode_switch.winfo_children():
            child.destroy()
        enabled = directions.enabled(self.db)
        if self.orders_tab.mode not in enabled:
            self.orders_tab.mode = enabled[0]
        if len(enabled) < 2:
            return
        for direction in enabled:
            on = direction == self.orders_tab.mode
            label = tk.Label(self.mode_switch, text=directions.TITLES[direction], cursor='hand2',
                             font=(styles.DEFAULT_FONT, 11, 'bold' if on else 'normal'),
                             bg='#ffffff' if on else styles.COLORS['primary_dark'],
                             fg=styles.COLORS['primary_dark'] if on else '#bfdbfe',
                             padx=14, pady=4)
            label.pack(side='left', pady=12)
            label.bind('<Button-1>', lambda e, d=direction: self.set_mode(d))

    def set_mode(self, mode):
        if mode == self.orders_tab.mode:
            return
        self.orders_tab.set_mode(mode)
        self.appointments_tab.set_direction(mode)
        self.draw_mode_switch()
        self.apply_mode()
        self._calendar_badge()

    def apply_mode(self):
        """Хранение шин и покраска — дела шиномонтажа: в мойке их нет."""
        from services import directions
        tire = self.orders_tab.mode == directions.TIRE
        self.nav.set_visible(self.tire_storage_tab.frame, tire)
        self.nav.set_visible(self.paint_tab.frame, tire)
        # Склад — только когда его ведут (docs/stock.md)
        from services.stock_service import stock_on
        self.nav.set_visible(self.stock_tab.frame, stock_on(self.db))
        self._calendar_badge()
        self.refresh_shift_status()

    def directions_changed(self):
        """В настройках включили или выключили направление."""
        self.draw_mode_switch()
        self.orders_tab.set_mode(self.orders_tab.mode)
        if self.appointments_tab.direction != self.orders_tab.mode:
            self.appointments_tab.set_direction(self.orders_tab.mode)
        self.apply_mode()

    def _open_warranty(self, order):
        self.orders_tab.open_order_tab(order)
        self.show_orders()

    def show_orders(self):
        self.nav.select_frame(self.orders_tab.frame)

    def show_calendar(self):
        self.nav.select_frame(self.calendar_tab.frame)
        self.calendar_tab.go_today()

    def storage_from_order(self, order, release=False):
        """
        Хранение из наряда: открыть вкладку «Хранение шин» с формой,
        заполненной из наряда и карточки клиента (docs/calendar.md).
        """
        self.nav.select_frame(self.tire_storage_tab.frame)
        if release:
            self.tire_storage_tab.prefill_release(order)
        else:
            self.tire_storage_tab.prefill_accept(order)

    def _calendar_badge(self):
        from services.calendar_service import CalendarService
        count = CalendarService(self.db).overdue_count()
        self.nav.set_title(self.calendar_tab.frame,
                           f'Календарь ({count})' if count else 'Календарь')
        # «Склад (N)» — сколько позиций мало или в минусе
        from services.stock_service import StockService
        stock = StockService(self.db)
        problems = stock.problems_count() if stock.enabled() else 0
        self.nav.set_title(self.stock_tab.frame, f'Склад ({problems})' if problems else 'Склад')
        if self.stock_tab.frame.winfo_ismapped():
            self.stock_tab.load()
        # Касса: оплатили наряд наличными — остаток вырос
        if self.cash_tab.frame.winfo_ismapped():
            self.cash_tab.load(keep=True)

    def _queue_housekeeping(self, refresh=False):
        """
        Следить за постами некому: сгоревшие вызовы снимаем и
        следующего зовём сами, даже если раздел очереди закрыт.
        Возвращает, изменилось ли что-нибудь.
        """
        try:
            from services.live_queue_service import LiveQueueService
            queue = LiveQueueService(self.db)
            changed = len(queue.expire_calls()) + queue.auto_call()
            panel = self.appointments_tab.queue
            if refresh or changed or panel.frame.winfo_ismapped():
                panel.load()
            return bool(changed)
        except Exception as e:
            self.db.rollback()
            log.warning(f"Очередь не обслужилась: {e}")
            return False

    def _start_live_sync(self):
        """
        Обмен очередью — часто и в своём потоке со своей сессией базы:
        вызов на пост не должен ждать большого обмена раз в 10 минут,
        а окно — замирать, пока сервер отвечает.
        """
        if self.live_running is not None:
            return False
        try:
            from services.sync_service import SyncService
            if not SyncService(self.db).is_enabled():
                return False
        except Exception:
            # Без отката сессия после сбоя чтения так и осталась бы
            # «сломанной», и падали бы все следующие запросы (ревью 26.10.2026)
            self.db.rollback()
            return False

        import threading

        def worker():
            from config import SessionLocal
            from services.sync_service import SyncService
            db = SessionLocal()
            try:
                self.live_result = SyncService(db).live_exchange()
            except Exception as e:
                log.warning(f"Обмен очередью не удался: {e}")
                self.live_result = 0
            try:
                SyncService(db).tasks_exchange()
            except Exception as e:
                log.warning(f"Задачи календаря не обменялись: {e}")
            try:
                # Кабинет мастера: «Начал» / «Готово» с телефона и ответы
                # клиентов на предложения мастеров
                self.master_result = SyncService(db).master_exchange()
            except Exception as e:
                db.rollback()
                log.warning(f"Нажатия мастеров и ответы клиентов не получены: {e}")
            try:
                SyncService(db).stock_exchange()
            except Exception as e:
                log.warning(f"Остатки склада не отправлены: {e}")
            try:
                # Записи на сегодня: «Я на месте» с телефона должно
                # появиться в цеху сразу, а не при следующем открытии ленты
                from datetime import date
                from services.booking_api import BookingApi
                BookingApi(db).get_day(date.today())
                from services import directions as _directions
                if _directions.wash_on(db):
                    BookingApi(db).get_day(date.today(), 'wash')
            except Exception as e:
                log.warning(f"Записи на сегодня не обновились: {e}")
            finally:
                db.close()

        self.live_running = threading.Thread(target=worker, daemon=True)
        self.live_running.start()
        self.root.after(500, self._live_poll)
        return True

    def _live_poll(self):
        # Ждём поток здесь, в главном: окна трогать можно только отсюда
        if self.live_running is not None and self.live_running.is_alive():
            self.root.after(500, self._live_poll)
            return
        self.live_running = None
        try:
            from models import LiveQueueEntry, Appointment
            for obj in list(self.db.identity_map.values()):
                if isinstance(obj, Appointment):
                    # Копию дня перезаписали целиком — старые строки
                    # отпускаем, иначе сессия держала бы удалённые
                    self.db.expunge(obj)
                elif isinstance(obj, LiveQueueEntry):
                    self.db.expire(obj)

            self._calendar_refresh()
            self._master_refresh()
            changed = self._queue_housekeeping(refresh=bool(self.live_result))
            if changed:
                # Позванные должны узнать сразу, а не через 20 секунд
                self.root.after(1000, self._start_live_sync)
        except Exception as e:
            self.db.rollback()
            log.warning(f"Не удалось обновить очередь после обмена: {e}")

    def schedule_shift_check(self):
        # Раз в минуту: смена закрывается в 9:05, а не «где-то до 9:15»
        self.root.after(60 * 1000, self._periodic_shift_check)

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

    def sync_soon_after(self, delay_ms, reason):
        """
        Выйти на связь через delay_ms, если не вышли только что.

        Пачкой, а не по событию: приёмщик закрывает наряд, следом
        второй, следом двигает машину — это три события за десять
        секунд, а отправка нужна одна. Пока досылка отложена, новые
        просьбы к ней присоединяются.
        """
        try:
            from services.sync_service import SyncService

            if not SyncService(self.db).is_enabled():
                return False
        except Exception:
            # Без отката сессия после сбоя чтения так и осталась бы
            # «сломанной», и падали бы все следующие запросы (ревью 26.10.2026)
            self.db.rollback()
            return False

        if self.sync_soon is not None or self.sync_running:
            return False

        log.info(f"Срочный обмен: {reason}")
        self.sync_soon = self.root.after(delay_ms, self._nudged_sync)
        return True

    def _nudged_sync(self):
        self.sync_soon = None
        self._start_sync()

    def _start_sync(self):
        """Запустить обмен, если он уже не идёт."""
        if self.sync_running:
            return

        try:
            from services.sync_service import SyncService

            service = SyncService(self.db)
            if not service.is_enabled():
                return

            self.sync_running = True
            service.run_in_background(on_done=self._sync_done)
        except Exception as e:
            self.sync_running = False
            log.error(f"Не удалось запустить обмен: {e}")

    def _periodic_sync(self):
        self._start_sync()
        self.schedule_sync()

    def _sync_done(self, success, result):
        """
        Итог обмена. Вызывается из другого потока — только через after.

        Ругаться на каждый неудачный обмен нельзя: у цеха может просто
        не быть интернета, и всплывающее окно раз в две минуты сведёт
        приёмщика с ума. Поэтому молчим, пока сбои не станут упорными.
        """
        def show():
            self.sync_running = False

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
            self.sync_running = False

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
                # В мойке — посты мойки: у неё свои
                from services import directions
                if getattr(self, 'orders_tab', None) is not None and \
                        self.orders_tab.mode == directions.WASH:
                    text = f"Смена открыта  ·  постов мойки: {directions.wash_posts(self.db)}"
            else:
                text = "Смена не открыта"
            self.app_bar.subtitle_label.config(text=text)
        except Exception as e:
            log.error(f"Не удалось показать состояние смены: {e}")
