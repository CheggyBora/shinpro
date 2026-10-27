"""
Экран одного наряда.

Раньше весь наряд — состав, оплата, время, печать — жил в одном файле
на полторы тысячи строк, где правка в одном месте задевала соседнее.
Теперь класс собран из частей: позиции, оплата, учёт времени. Здесь
осталась только сборка экрана и то, что не относится ни к одной части.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from utils import format_phone, get_moscow_time
from logger import log
import styles

from .items import OrderItemsMixin
from .payment import OrderPaymentMixin
from .timing import OrderTimingMixin
from .directions import OrderDirectionsMixin
from .blocks import OrderBlocksMixin
from ui.order_screen.shift_guard import needs_shift

class OrderWidget(OrderItemsMixin, OrderPaymentMixin, OrderTimingMixin, OrderBlocksMixin,
                  OrderDirectionsMixin):
    """Вкладка одного наряда: состав, оплата, время работы."""

    def __init__(self, frame, order, db, order_service, salary_service, print_service, close_callback, parent_orders_tab=None):
        self.frame = frame
        self.order = order
        self.db = db
        self.order_service = order_service
        self.salary_service = salary_service
        self.print_service = print_service
        self.close_callback = close_callback
        self.parent_orders_tab = parent_orders_tab
        
        # Содержимое наряда лежит на белой карточке: раньше оно висело
        # прямо на сером фоне и выглядело незаконченным
        card = styles.create_card_frame(frame)
        card.pack(fill='both', expand=True, padx=2, pady=(6, 2))

        main_container = ttk.Frame(card, style='White.TFrame')
        main_container.pack(fill='both', expand=True, padx=18, pady=(12, 10))

        # Верхняя строка: машина, скидки, цены
        top_frame = ttk.Frame(main_container, style='White.TFrame')
        top_frame.pack(fill='x', pady=(0, 8))

        # Машина и клиент (слева)
        info_frame = ttk.Frame(top_frame, style='White.TFrame')
        info_frame.pack(side='left')

        vehicle_type_map = {
            'car': 'Легковой',
            'suv': 'Джип/Кроссовер/Пикап',
            'truck': 'Категория С (коммерческий)'
        }
        vehicle_type_display = vehicle_type_map.get(order.vehicle_type, order.vehicle_type)
        
        # Заголовок наряда: номер крупно, характеристики машины —
        # отдельной приглушённой строкой, чтобы глаз не спотыкался
        # о частокол вертикальных чёрточек
        header_row = ttk.Frame(info_frame, style='White.TFrame')
        header_row.pack(anchor='w', fill='x')

        # Обложка — снимок машины с телефона: видно, та ли машина на посту.
        # Щелчок — на весь экран (docs/order_photo.md)
        from services.arrival_service import cover_file, load_image, show_full
        cover = cover_file(order, self.db)
        image = load_image(cover, 64, 48) if cover else None
        if image is not None:
            thumb = tk.Label(header_row, image=image, cursor='hand2', bd=0,
                             bg=styles.COLORS['bg_card'])
            thumb.image = image
            thumb.pack(side='left', padx=(0, 10))
            thumb.bind('<Button-1>', lambda e, p=cover: show_full(
                self.frame, p, f'Наряд №{order.id} · {order.car.license_plate}'))

        ttk.Label(header_row, text=f"Наряд №{order.id}",
                  font=(styles.DEFAULT_FONT, 15, 'bold'),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text']).pack(side='left')

        ttk.Label(header_row, text=order.car.license_plate,
                  font=(styles.DEFAULT_FONT, 13, 'bold'),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['primary']).pack(side='left', padx=(14, 0))

        # Гарантийная переделка — видно сразу, почему услуги по 0 ₽
        if getattr(order, 'is_warranty', False):
            tk.Label(header_row, text=f"гарантия · по наряду №{order.warranty_of_id}"
                     if order.warranty_of_id else "гарантия",
                     bg='#fef3c7', fg='#92400e', padx=8, pady=1,
                     font=(styles.DEFAULT_FONT, 10, 'bold')).pack(side='left', padx=(12, 0))

        # Редкое — в одном меню: хранение, фото, «готово», удалить
        # (макеты от 26.10.2026). Диаметр и пост — в шапке блока шиномонтажа
        self.build_more_menu(header_row)

        if order.client:
            client_row = ttk.Frame(info_frame, style='White.TFrame')
            client_row.pack(anchor='w', fill='x', pady=(6, 0))

            client_info = order.client.name or ""
            if order.client.phone:
                client_info += f" · {format_phone(order.client.phone)}"
            client_text = client_info
            if order.auto_discount:
                client_text += "  (автоскидка 5%)"
            ttk.Label(client_row, text=client_text, font=(styles.DEFAULT_FONT, 10),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['success'] if order.auto_discount
                      else styles.COLORS['text']).pack(side='left')

            # Группа клиента — кому предлагать допы. Значок одинаковый
            # у всех, пока не нажмёшь: клиент у стойки ничего не прочтёт
            from ui.client_group_badge import create_group_badge
            create_group_badge(client_row, self.db,
                               order.client_id).pack(side='left', padx=(8, 0))

            # Из наряда сразу в карточку: поправить телефон или добавить
            # ещё одну машину, не выходя из работы
            styles.create_button(client_row, "Клиент",
                                 self.open_client_card, 'Compact.Secondary.TButton').pack(
                                     side='left', padx=(10, 0))

            self.told_label = ttk.Label(
                client_row, text="", font=(styles.DEFAULT_FONT, 9),
                background=styles.COLORS['bg_card'],
                foreground=styles.COLORS['success'])
            self.told_label.pack(side='left', padx=(10, 0))
            self.refresh_told()

        # Задачи по этой машине из календаря: «шины приехали», «комплект
        # привезли» — приёмщик видит их ровно тогда, когда машина у него
        self.tasks_box = ttk.Frame(info_frame, style='White.TFrame')
        self.tasks_box.pack(anchor='w', fill='x')
        self.refresh_tasks()
        
        # Рекомендации (под сотрудниками)
        recommendations_frame = ttk.Frame(main_container, style='White.TFrame')
        recommendations_frame.pack(fill='x', pady=(2, 0))
        
        ttk.Label(recommendations_frame, text="Рекомендации:", background=styles.COLORS['bg_card'], foreground=styles.COLORS['text_secondary'], font=(styles.DEFAULT_FONT, 9, 'bold')).pack(anchor='w')
        
        self.recommendations_text = tk.Text(recommendations_frame, height=2, font=styles.FONTS['normal'], 
                                           bg=styles.COLORS['bg_card'], fg=styles.COLORS['text'],
                                           relief='solid', borderwidth=1, wrap='word')
        self.recommendations_text.pack(fill='x', pady=(2, 5))
        
        # Устанавливаем placeholder и загружаем существующие рекомендации
        if order.recommendations:
            self.recommendations_text.insert('1.0', order.recommendations)
            self.recommendations_text.tag_configure('placeholder', foreground='#94a3b8')
        else:
            self.recommendations_text.insert('1.0', 'Рекомендации для клиента...')
            self.recommendations_text.tag_add('placeholder', '1.0', 'end')
            self.recommendations_text.tag_configure('placeholder', foreground='#94a3b8')
        
        # Обработчики для placeholder и автосохранения
        self.recommendations_text.bind('<FocusIn>', self.on_recommendations_focus_in)
        self.recommendations_text.bind('<FocusOut>', self.on_recommendations_focus_out)
        
        # Скидки (левее)
        discount_frame = ttk.Frame(top_frame, style='White.TFrame')
        discount_frame.pack(side='left', padx=(15, 0))
        
        ttk.Label(discount_frame, text="Скидки:", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 11, 'bold')).pack(anchor='w')
        
        disc_row = ttk.Frame(discount_frame, style='White.TFrame')
        disc_row.pack()
        
        ttk.Label(disc_row, text="Диски:", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 10)).pack(side='left', padx=(0, 3))
        self.rim_discount_var = tk.StringVar(value='0')
        rim_combo = ttk.Combobox(disc_row, textvariable=self.rim_discount_var, values=['0', '10', '20'], 
                                 width=5, font=(styles.DEFAULT_FONT, 10), state='readonly')
        rim_combo.pack(side='left', padx=(0, 3))
        ttk.Button(disc_row, text="OK", command=self.apply_rim_discount, width=3).pack(side='left', padx=(0, 10))
        
        ttk.Label(disc_row, text="Общ:", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 10)).pack(side='left', padx=(0, 3))
        self.general_discount_var = tk.StringVar(value='0')
        general_combo = ttk.Combobox(disc_row, textvariable=self.general_discount_var, values=['0', '10', '15'], 
                                      width=5, font=(styles.DEFAULT_FONT, 10), state='readonly')
        general_combo.pack(side='left', padx=(0, 3))
        ttk.Button(disc_row, text="OK", command=self.apply_general_discount, width=3).pack(side='left')
        
        # Цены (справа)
        price_frame = ttk.Frame(top_frame, style='White.TFrame')
        price_frame.pack(side='right')
        
        self.price_label = ttk.Label(price_frame, text="0.00 руб.", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 14, 'bold'), foreground='#2563eb')
        self.price_label.pack(anchor='e')
        
        self.discount_price_label = ttk.Label(price_frame, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 12, 'bold'), foreground='#059669')
        self.discount_price_label.pack(anchor='e')

        # Расходники и база для зарплаты: механик и кассир видят цифру сразу,
        # а не узнают её в конце месяца
        self.salary_base_label = ttk.Label(price_frame, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 9),
                                           foreground='#64748b')
        self.salary_base_label.pack(anchor='e')

        # Плановое время и его сохранение.
        # Время меняется только по кнопке: пока мастер прикидывает стоимость,
        # прогноз для очереди не должен прыгать туда-сюда.
        time_row = ttk.Frame(price_frame, style='White.TFrame')
        time_row.pack(anchor='e', pady=(4, 0))

        self.time_label = ttk.Label(time_row, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 10, 'bold'),
                                    foreground='#2563eb')
        self.time_label.pack(side='left', padx=(0, 8))

        self.save_order_button = styles.create_button(
        time_row, "Сохранить наряд", self.save_composition, 'Primary.TButton')
        self.save_order_button.pack(side='left')

        self.unsaved_label = ttk.Label(price_frame, text="", background=styles.COLORS['bg_card'], font=(styles.DEFAULT_FONT, 9),
                                       foreground='#d97706')
        self.unsaved_label.pack(anchor='e')

        # Идентификатор отложенного автосохранения, чтобы отменять предыдущее
        self._autosave_job = None

        # Услуги — блоками по направлениям: шиномонтаж, мойка
        # (ui/order_screen/blocks.py)
        self.build_blocks(main_container)

        # Загрузка данных
        self.refresh_items()

    # ------------------------------------------------------------------
    # «Машина готова»
    # ------------------------------------------------------------------

    def open_photos(self):
        """Фото по наряду: QR для телефона мастера и что уже прислали."""
        from ui.photo_dialog import open_photos

        open_photos(self.frame, self.db, self.order)

    def refresh_told(self):
        """Показать, звали ли уже клиента. Кнопка при этом не исчезает:
        бывает, что сообщение не заметили и зовут второй раз."""
        told = getattr(self.order, 'client_told_at', None)
        if told is None:
            self.told_label.config(text="")
            return

        self.told_label.config(text=f"сообщили в {told.strftime('%H:%M')}")

    def tell_ready(self):
        """
        Сказать клиенту, что машина готова.

        Уходит в Телеграм или уведомлением в браузере — туда, где
        клиент нас подключил. Не вышло — говорим честно и сразу: у
        приёмщика перед глазами телефон, он позвонит.
        """
        from services.sync_service import SyncService

        self.ready_button.config(state='disabled')
        try:
            ok, how = SyncService(self.db).tell_ready(self.order)
        except Exception as e:
            ok, how = False, str(e)
        finally:
            self.ready_button.config(state='normal')

        if not ok:
            phone = (format_phone(self.order.client.phone)
                     if self.order.client and self.order.client.phone else '—')
            messagebox.showwarning(
                "Не отправлено",
                f"{how}.\n\nПозвоните клиенту: {phone}")
            return

        where = {'telegram': 'в Телеграм',
                 'webpush': 'уведомлением в браузере'}.get(how, '')
        self.order.client_told_at = get_moscow_time()
        self.db.commit()
        self.refresh_told()

        messagebox.showinfo("Отправлено",
                            f"Клиенту сообщили {where}, что машина готова.")

    # ------------------------------------------------------------------
    # Хранение и задачи по машине
    # ------------------------------------------------------------------

    def _stored_sets(self):
        from models import TireStorage
        try:
            return self.db.query(TireStorage).filter(
                TireStorage.car_number == self.order.car.license_plate,
                TireStorage.status == 'stored').order_by(TireStorage.id).all()
        except Exception:
            self.db.rollback()
            return []

    def _app(self):
        return getattr(self.parent_orders_tab, 'app', None)

    def storage_accept(self):
        app = self._app()
        if app is not None:
            app.storage_from_order(self.order, release=False)

    def storage_release(self):
        app = self._app()
        if app is not None:
            app.storage_from_order(self.order, release=True)

    def storage_order(self):
        """Заказать комплект машины со склада к дате (docs/calendar.md)."""
        from ui.tire_storage_tab import WarehouseOrderDialog
        from services.calendar_service import storage_title
        stored = self._stored_sets()
        if not stored:
            messagebox.showinfo("Хранение", "У этой машины нет комплектов на хранении")
            return
        chosen = stored[0]
        if len(stored) > 1:
            from ui.order_screen.directions import ask_choice
            set_id = ask_choice(self.frame, "Заказать со склада", "Какой комплект:",
                                [(s.id, f"№{s.id} · {storage_title(s)}") for s in stored])
            if not set_id:
                return
            chosen = next(s for s in stored if s.id == set_id)
        WarehouseOrderDialog(self.frame, self.db, chosen)

    def open_car(self):
        from ui.car_info import open_car_info
        open_car_info(self.frame, self.db, self.order.car.license_plate)

    def refresh_tasks(self):
        from services.calendar_service import CalendarService
        from ui.task_dialog import CATEGORY_COLORS
        for child in self.tasks_box.winfo_children():
            child.destroy()
        try:
            tasks = CalendarService(self.db).for_plate(self.order.car.license_plate)
        except Exception:
            self.db.rollback()
            return
        for task in tasks:
            fg, bg = CATEGORY_COLORS.get(task.category, CATEGORY_COLORS['work'])
            row = tk.Frame(self.tasks_box, bg=bg)
            row.pack(anchor='w', fill='x', pady=(6, 0))
            when = f'{task.due_date:%d.%m}' + (f' {task.due_time}' if task.due_time else '')
            text = f'Задача · {when} · {task.title}'
            if task.note:
                text += f' — {task.note.splitlines()[0][:80]}'
            label = tk.Label(row, text=text, bg=bg, fg=fg, anchor='w', cursor='hand2',
                             font=(styles.DEFAULT_FONT, 10))
            label.pack(side='left', padx=8, pady=4)
            label.bind('<Button-1>', lambda e, t=task: self._edit_task(t))
            styles.create_button(row, "Сделано", lambda t=task: self._task_done(t),
                                 'Compact.Secondary.TButton').pack(side='right', padx=4, pady=2)

    def _edit_task(self, task):
        from ui.task_dialog import open_task
        open_task(self.frame, self.db, task, on_saved=self._tasks_changed)

    def _task_done(self, task):
        from services.calendar_service import CalendarService
        from ui.task_dialog import WHO
        CalendarService(self.db).set_done(task, True, by=WHO)
        self._tasks_changed()

    def _tasks_changed(self):
        self.refresh_tasks()
        if self.parent_orders_tab is not None:
            self.parent_orders_tab.refresh_tasks()

    def _post_text(self):
        post = getattr(self.order, 'post_number', None)
        return f"Пост {post}" if post else "Пост не выбран"

    @needs_shift
    def change_post(self):
        """Переставить машину на другой свободный пост."""
        from services.live_queue_service import LiveQueueService, QueueError
        from ui.live_queue_panel import ask_post

        queue = LiveQueueService(self.db)
        free = [s['post'] for s in queue.posts() if s['state'] == 'free']
        if not free:
            messagebox.showinfo("Пост", "Свободных постов нет", parent=self.frame)
            return
        post = ask_post(self.frame, free)
        if not post:
            return
        try:
            queue.set_order_post(self.order.id, post)
        except QueueError as e:
            messagebox.showwarning("Пост", str(e), parent=self.frame)
            return
        self.db.refresh(self.order)
        self.post_label.config(text=self._post_text() + ' ▾')

    def open_client_card(self):
        """Открыть карточку клиента этого наряда."""
        from ui.client_card import open_client_card

        if not self.order.client_id:
            messagebox.showinfo("Клиент не указан",
                                "В этом наряде клиент не заполнен.")
            return

        try:
            card = open_client_card(self.frame, self.db, self.order.client_id)
            # После закрытия карточки перечитываем наряд: имя и телефон
            # могли поменять
            self.frame.wait_window(card)
            self.db.refresh(self.order)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось открыть карточку: {e}")

    def on_recommendations_focus_in(self, event):
        """Убираем placeholder при получении фокуса"""
        content = self.recommendations_text.get('1.0', 'end-1c')
        if content == 'Рекомендации для клиента...':
            self.recommendations_text.delete('1.0', 'end')
            self.recommendations_text.tag_remove('placeholder', '1.0', 'end')

    def on_recommendations_focus_out(self, event):
        """Сохраняем рекомендации при потере фокуса"""
        content = self.recommendations_text.get('1.0', 'end-1c').strip()

        # Без открытой смены наряд не меняется: возвращаем, как было
        from ui.order_screen.shift_guard import shift_open, SHIFT_CLOSED
        if not shift_open(self.db):
            if content != (self.order.recommendations or '') and content != 'Рекомендации для клиента...':
                self.recommendations_text.delete('1.0', 'end')
                self.recommendations_text.insert('1.0', self.order.recommendations or '')
                messagebox.showwarning("Смена закрыта", SHIFT_CLOSED)
            return
        
        if not content:
            # Если пусто, показываем placeholder
            self.recommendations_text.delete('1.0', 'end')
            self.recommendations_text.insert('1.0', 'Рекомендации для клиента...')
            self.recommendations_text.tag_add('placeholder', '1.0', 'end')
            # Сохраняем пустое значение
            self.order.recommendations = None
        else:
            # Сохраняем введённый текст
            self.order.recommendations = content
        
        # Сохраняем в базу данных
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            log.error(f"Ошибка сохранения рекомендаций: {e}")

    @needs_shift
    def delete_order(self):
        """Удаляет непробитый наряд с подтверждением"""
        # Проверяем, что наряд - черновик (только черновики можно удалять)
        if self.order.status != 'draft':
            messagebox.showerror("Ошибка", "Нельзя удалить наряд в работе или оплаченный.\nМожно удалять только черновики.")
            return
        
        # Диалог подтверждения
        confirm = messagebox.askyesno(
            "Подтверждение удаления", 
            f"Вы действительно хотите удалить наряд №{self.order.id}?\n\n"
            f"Машина: {self.order.car.license_plate}\n"
            f"Этот наряд будет полностью удалён из базы данных.\n\n"
            f"Продолжить?",
            icon='warning'
        )
        
        if not confirm:
            return
        
        try:
            # Вызываем метод полного удаления
            success, message = self.order_service.hard_delete_unpaid_order(self.order.id)
            
            if success:
                messagebox.showinfo("Успех", message)
                # Закрываем вкладку с нарядом
                self.close_callback(self.order.id)
            else:
                messagebox.showerror("Ошибка", message)
        
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось удалить наряд:\n{str(e)}")
