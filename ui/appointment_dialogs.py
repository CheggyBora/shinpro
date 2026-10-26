"""
Окна раздела «Запись»: заведение записи и её подробности.

Форма записи намеренно короткая. Приёмщик заполняет её, пока клиент
ждёт на телефоне, поэтому полей ровно четыре: номер машины, имя,
телефон и колёса в сборе или россыпью. Всё остальное — время работ,
услуги, клиентская карточка — программа достаёт или заводит сама.
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

from tkcalendar import DateEntry

from models import Appointment
from services.booking_api import SlotTaken
from services.booking_gateway import get_booking
from services import ClientService
from utils import format_phone, normalize_plate
import styles

# Шаг сетки времени в форме: четверти часа хватает, а список
# из 96 значений листается быстрее, чем набирается руками
TIME_STEP_MINUTES = 15

WHEELS_ASSEMBLED = 'assembled'
WHEELS_TIRES = 'tires'
WHEELS_UNKNOWN = 'unknown'

WHEELS_TITLES = {
    WHEELS_ASSEMBLED: 'Колёса в сборе',
    WHEELS_TIRES: 'Только шины',
    WHEELS_UNKNOWN: 'Не выяснили',
}


def wheels_to_flag(choice):
    if choice == WHEELS_ASSEMBLED:
        return True
    if choice == WHEELS_TIRES:
        return False
    return None


def flag_to_wheels(flag):
    if flag is True:
        return WHEELS_ASSEMBLED
    if flag is False:
        return WHEELS_TIRES
    return WHEELS_UNKNOWN


def time_values():
    """Все моменты суток с шагом в четверть часа."""
    return [f"{minutes // 60:02d}:{minutes % 60:02d}"
            for minutes in range(0, 24 * 60, TIME_STEP_MINUTES)]


def round_to_step(moment):
    """Округлить время вверх до шага сетки — записывают не на 14:07."""
    extra = moment.minute % TIME_STEP_MINUTES
    if extra:
        moment += timedelta(minutes=TIME_STEP_MINUTES - extra)
    return moment.replace(second=0, microsecond=0)


class AppointmentDialog:
    """Заведение и правка записи."""

    def __init__(self, parent, db, when=None, appointment=None, on_saved=None):
        self.db = db
        self.service = get_booking(db)
        self.clients = ClientService(db)
        self.appointment = appointment
        self.on_saved = on_saved
        self.saved = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Запись клиента" if appointment is None else "Изменить запись")
        self.dialog.geometry("460x480")
        self.dialog.configure(bg=styles.COLORS['bg'])
        self.dialog.transient(parent.winfo_toplevel())
        self.dialog.grab_set()
        styles.center_window(self.dialog, parent.winfo_toplevel())

        content = ttk.Frame(self.dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=22, pady=20)

        styles.create_label(content,
                            "Запись клиента" if appointment is None else "Изменить запись",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 14))

        moment = when or (appointment.scheduled_at if appointment else None)
        moment = round_to_step(moment or datetime.now())

        # --- Когда ------------------------------------------------------
        when_row = ttk.Frame(content, style='White.TFrame')
        when_row.pack(fill='x', pady=(0, 12))

        styles.create_label(when_row, "Когда:", 'Card.TLabel').pack(side='left', padx=(0, 10))
        self.date_entry = DateEntry(when_row, width=13, locale='ru_RU',
                                    date_pattern='dd.mm.yyyy',
                                    font=styles.FONTS['normal'])
        self.date_entry.set_date(moment.date())
        self.date_entry.pack(side='left', padx=(0, 10))

        self.time_var = tk.StringVar(value=moment.strftime('%H:%M'))
        ttk.Combobox(when_row, textvariable=self.time_var, width=7,
                     values=time_values(),
                     font=styles.FONTS['normal']).pack(side='left')

        # --- Номер машины ------------------------------------------------
        styles.create_label(content, "Номер автомобиля:",
                            'Card.TLabel').pack(anchor='w', pady=(0, 4))
        self.plate_entry = styles.create_entry(content, width=24)
        self.plate_entry.pack(fill='x', pady=(0, 4))
        if appointment and appointment.license_plate:
            self.plate_entry.insert(0, appointment.license_plate)

        # Клиента подтягиваем по номеру: приёмщику достаточно спросить
        # «ваш номер?» и остальное появится само
        self.plate_entry.bind('<FocusOut>', lambda e: self.lookup_by_plate())
        self.plate_entry.bind('<Return>', lambda e: self.lookup_by_plate())

        self.found_label = ttk.Label(content, text="",
                                     font=(styles.DEFAULT_FONT, 9),
                                     background=styles.COLORS['bg_card'],
                                     foreground=styles.COLORS['text_secondary'],
                                     wraplength=400, justify='left')
        self.found_label.pack(anchor='w', pady=(0, 10))

        # --- Клиент -------------------------------------------------------
        styles.create_label(content, "Имя клиента:",
                            'Card.TLabel').pack(anchor='w', pady=(0, 4))
        self.name_entry = styles.create_entry(content, width=30)
        self.name_entry.pack(fill='x', pady=(0, 10))
        if appointment and appointment.client_name:
            self.name_entry.insert(0, appointment.client_name)

        styles.create_label(content, "Телефон:",
                            'Card.TLabel').pack(anchor='w', pady=(0, 4))
        self.phone_entry = styles.create_entry(content, width=24)
        self.phone_entry.pack(fill='x', pady=(0, 12))
        if appointment and appointment.client_phone:
            self.phone_entry.insert(0, format_phone(appointment.client_phone))

        # Шиномонтаж или мойка: у записи на мойку — класс машины, а не колёса
        self.direction = (appointment.direction if appointment is not None
                          else getattr(self.service, 'direction', 'tire')) or 'tire'
        self.wash_class_var = tk.StringVar()
        if self.direction == 'wash':
            from services import directions as _directions
            self.dialog.title("Запись на мойку" if appointment is None else "Изменить запись на мойку")
            known = appointment.wash_class if appointment is not None else None
            if not known and appointment and appointment.license_plate:
                car = self.clients.get_car(appointment.license_plate)
                known = car.wash_class if car is not None else None
            self.wash_class_var.set(_directions.class_title(known) if known else '')
            styles.create_label(content, "Класс машины (мойка)*:", 'Card.TLabel').pack(anchor='w', pady=(0, 4))
            ttk.Combobox(content, textvariable=self.wash_class_var, state='readonly',
                         values=[_directions.WASH_CLASS_TITLES[k] for k in _directions.WASH_CLASSES],
                         font=styles.FONTS['normal']).pack(fill='x', pady=(0, 4))

        # --- Колёса --------------------------------------------------------
        wheels_title = styles.create_label(content, "Колёса:", 'Card.TLabel')
        if self.direction != 'wash':
            wheels_title.pack(anchor='w', pady=(0, 4))

        current = WHEELS_UNKNOWN
        if appointment and appointment.license_plate:
            car = self.clients.get_car(appointment.license_plate)
            if car is not None:
                current = flag_to_wheels(car.wheels_assembled)
        self.wheels_var = tk.StringVar(value=current)

        wheels_row = ttk.Frame(content, style='White.TFrame')
        if self.direction != 'wash':
            wheels_row.pack(fill='x', pady=(0, 4))
        for value in (WHEELS_ASSEMBLED, WHEELS_TIRES, WHEELS_UNKNOWN):
            ttk.Radiobutton(wheels_row, text=WHEELS_TITLES[value],
                            value=value, variable=self.wheels_var,
                            command=self.show_duration).pack(side='left', padx=(0, 14))

        self.duration_label = ttk.Label(content, text="",
                                        font=(styles.DEFAULT_FONT, 9),
                                        background=styles.COLORS['bg_card'],
                                        foreground=styles.COLORS['text_secondary'])
        self.duration_label.pack(anchor='w', pady=(0, 12))
        self.show_duration()

        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x', pady=(6, 0))
        styles.create_button(buttons, "Записать" if appointment is None else "Сохранить",
                             self.save, 'Primary.TButton').pack(
            side='left', fill='x', expand=True, padx=(0, 6))
        styles.create_button(buttons, "Отмена", self.dialog.destroy,
                             'Secondary.TButton').pack(
            side='left', fill='x', expand=True, padx=(6, 0))

        if appointment is None:
            self.plate_entry.focus_set()

    # ------------------------------------------------------------------

    def _duration(self):
        if getattr(self, 'direction', 'tire') == 'wash':
            from services.booking_gateway import wash_duration
            return wash_duration(self.db)
        return self.service.duration_for_wheels(wheels_to_flag(self.wheels_var.get()))

    def show_duration(self):
        self.duration_label.config(text=f"Заложим {self._duration()} мин")

    def lookup_by_plate(self):
        """Подтянуть клиента по номеру машины."""
        plate = normalize_plate(self.plate_entry.get())
        if not plate:
            self.found_label.config(text="")
            return

        # Показываем номер в нормальном виде: ввели латиницей —
        # увидели, как он ляжет в базу
        if self.plate_entry.get().strip() != plate:
            self.plate_entry.delete(0, tk.END)
            self.plate_entry.insert(0, plate)

        car = self.clients.get_car(plate)
        if car is None:
            self.found_label.config(
                text="Такой машины ещё нет — заведём вместе с записью",
                foreground=styles.COLORS['text_secondary'])
            return

        client = car.client
        if client is None:
            self.found_label.config(text="Машина есть, владелец не указан",
                                    foreground=styles.COLORS['text_secondary'])
        else:
            parts = [client.name or 'без имени']
            if client.phone:
                parts.append(format_phone(client.phone))
            self.found_label.config(text="Клиент: " + ', '.join(parts),
                                    foreground=styles.COLORS['success'])

            if not self.name_entry.get().strip() and client.name:
                self.name_entry.insert(0, client.name)
            if not self.phone_entry.get().strip() and client.phone:
                self.phone_entry.insert(0, format_phone(client.phone))

        # Класс для мойки машина уже может знать — не переспрашиваем
        if getattr(self, 'direction', 'tire') == 'wash' and car.wash_class \
                and not self.wash_class_var.get():
            from services import directions as _directions
            self.wash_class_var.set(_directions.class_title(car.wash_class))

        # Про колёса машина уже может знать — не переспрашиваем
        if car.wheels_assembled is not None:
            self.wheels_var.set(flag_to_wheels(car.wheels_assembled))
            self.show_duration()

    def _scheduled_at(self):
        raw = self.time_var.get().strip()
        try:
            hours, minutes = [int(part) for part in raw.split(':')]
            if not (0 <= hours <= 23 and 0 <= minutes <= 59):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError(f"Время «{raw}» непонятно, нужно как 14:30")

        day = self.date_entry.get_date()
        return datetime(day.year, day.month, day.day, hours, minutes)

    def _refresh_behind(self):
        """
        Перечитать ленту позади формы.

        Нужно после отказа: приёмщик должен увидеть, кто занял время, а
        не то же пустое место, в которое он только что тыкал. Своя
        ошибка здесь ничего не решает — сообщение человек получит всё
        равно, и падать из-за неудачного обновления незачем.
        """
        if not self.on_saved:
            return
        try:
            self.on_saved()
        except Exception:
            pass

    def save(self):
        try:
            scheduled_at = self._scheduled_at()
        except ValueError as e:
            messagebox.showerror("Время", str(e), parent=self.dialog)
            return

        plate = normalize_plate(self.plate_entry.get())
        name = self.name_entry.get().strip()
        phone = self.phone_entry.get().strip()

        if not plate and not phone and not name:
            messagebox.showerror(
                "Запись", "Нужен хотя бы номер машины или телефон",
                parent=self.dialog)
            return

        wheels = wheels_to_flag(self.wheels_var.get())
        duration = self._duration()
        wash_class = None
        if self.direction == 'wash':
            from services import directions as _directions
            wash_class = _directions.class_by_title(self.wash_class_var.get())
            if not wash_class:
                messagebox.showerror("Запись", "Выберите класс машины для мойки",
                                     parent=self.dialog)
                return
            wheels = None

        exclude = self.appointment.id if self.appointment else None
        free, busy, posts = self.service.check_capacity(
            scheduled_at, duration, exclude_id=exclude)
        if not free:
            # Отказ, а не вопрос. Двух машин на один пост в одно время
            # не бывает, и «записать всё равно» кончалось бы тем, что
            # на это время приедут двое
            messagebox.showerror(
                "Время занято",
                f"На {scheduled_at.strftime('%d.%m %H:%M')} уже записано "
                f"{busy} при {posts} постах.\nВыберите другое время.",
                parent=self.dialog)
            return

        def write():
            if self.appointment is None:
                self.service.create(
                    scheduled_at=scheduled_at,
                    duration_minutes=duration,
                    client_name=name,
                    client_phone=phone,
                    license_plate=plate,
                    wheels_assembled=wheels,
                    direction=self.direction,
                    wash_class=wash_class)
                if wash_class and plate:
                    car = self.clients.get_car(plate)
                    if car is not None and not car.wash_class:
                        car.wash_class = wash_class
                        self.db.commit()
            else:
                self.service.update(
                    self.service.key_of(self.appointment),
                    scheduled_at=scheduled_at,
                    duration_minutes=duration,
                    client_name=name or None,
                    client_phone=phone or None,
                    license_plate=plate or None)
                if plate:
                    car = self.clients.get_car(plate)
                    if car is not None and wheels is not None \
                            and car.wheels_assembled is None:
                        car.wheels_assembled = wheels
                        self.db.commit()

        try:
            write()
        except SlotTaken as e:
            self.db.rollback()

            # Пока приёмщик заполнял форму, окно заняли — скорее всего
            # записались через интернет. Обновляем ленту позади, чтобы,
            # закрыв сообщение, он увидел, кто там стоит, а не то же
            # пустое место, и сразу назвал клиенту другое время
            self._refresh_behind()

            messagebox.showerror("Время занято", str(e), parent=self.dialog)
            return
        except Exception as e:
            self.db.rollback()
            self._refresh_behind()
            messagebox.showerror("Ошибка", f"Не удалось сохранить запись:\n{e}",
                                 parent=self.dialog)
            return

        self.saved = True
        self.dialog.destroy()
        if self.on_saved:
            self.on_saved()


class AppointmentDetailsDialog:
    """Подробности записи и действия по ней."""

    def __init__(self, parent, db, appointment_id, on_changed=None,
                 orders_tab=None):
        self.db = db
        self.service = get_booking(db)
        self.appointment_id = appointment_id
        self.on_changed = on_changed
        self.orders_tab = orders_tab

        appointment = self.service.get(appointment_id)
        if appointment is None:
            messagebox.showinfo("Запись", "Запись не найдена", parent=parent)
            self.dialog = None
            return

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"Запись № {appointment.id}")
        self.dialog.geometry("420x420")
        self.dialog.configure(bg=styles.COLORS['bg'])
        self.dialog.transient(parent.winfo_toplevel())
        self.dialog.grab_set()
        styles.center_window(self.dialog, parent.winfo_toplevel())

        content = ttk.Frame(self.dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=22, pady=20)

        plate = appointment.license_plate or 'без номера'
        styles.create_label(content, plate, 'CardHeading.TLabel').pack(anchor='w')

        moment = appointment.scheduled_at
        end = moment + timedelta(minutes=appointment.duration_minutes or 0)

        wheels = 'не выяснили'
        if appointment.license_plate:
            from services import ClientService

            car = ClientService(db).get_car(appointment.license_plate)
            if car is not None and car.wheels_assembled is not None:
                wheels = ('колёса в сборе' if car.wheels_assembled
                          else 'только шины')

        rows = [
            ("Когда", f"{moment.strftime('%d.%m.%Y')}, "
                      f"{moment.strftime('%H:%M')}–{end.strftime('%H:%M')}"),
            ("Клиент", appointment.client_name or '—'),
            ("Телефон", format_phone(appointment.client_phone)
                        if appointment.client_phone else '—'),
            ("Колёса", wheels),
            ("Состояние", appointment.status_title),
            ("Откуда", appointment.source_title),
        ]
        if appointment.comment:
            rows.append(("Комментарий", appointment.comment))

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(12, 16))
        grid.columnconfigure(1, weight=1)
        for row, (title, value) in enumerate(rows):
            ttk.Label(grid, text=title, font=(styles.DEFAULT_FONT, 9),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text_secondary']).grid(
                row=row, column=0, sticky='nw', pady=3, padx=(0, 14))
            ttk.Label(grid, text=value, font=styles.FONTS['normal'],
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text'],
                      wraplength=250, justify='left').grid(
                row=row, column=1, sticky='w', pady=3)

        actions = ttk.Frame(content, style='White.TFrame')
        actions.pack(fill='x')

        if appointment.status == Appointment.STATUS_SCHEDULED:
            styles.create_button(actions, "Приехал", self.mark_arrived,
                                 'Success.TButton').pack(fill='x', pady=(0, 6))

            second = ttk.Frame(content, style='White.TFrame')
            second.pack(fill='x', pady=(0, 6))
            styles.create_button(second, "Изменить", self.edit,
                                 'Secondary.TButton').pack(
                side='left', fill='x', expand=True, padx=(0, 5))
            styles.create_button(second, "Не приехал", self.mark_no_show,
                                 'Secondary.TButton').pack(
                side='left', fill='x', expand=True, padx=(5, 0))

            styles.create_button(content, "Отменить запись", self.cancel,
                                 'Danger.TButton').pack(fill='x', pady=(0, 6))

        styles.create_button(content, "Закрыть", self.dialog.destroy,
                             'Secondary.TButton').pack(fill='x')

    # ------------------------------------------------------------------

    def _done(self):
        if self.dialog is not None:
            self.dialog.destroy()
        if self.on_changed:
            self.on_changed()

    def edit(self):
        appointment = self.service.get(self.appointment_id)
        parent = self.dialog
        AppointmentDialog(parent, self.db, appointment=appointment,
                          on_saved=self._done)

    def mark_arrived(self):
        appointment = self.service.get(self.appointment_id)
        if (getattr(appointment, 'direction', None) or 'tire') == 'wash':
            return self._arrived_for_wash(appointment)

        # Приехал, а свободного поста нет: не открываем наряд «в никуда»,
        # а отмечаем «на месте» — программа позовёт его первым на
        # ближайший освободившийся пост (docs/live_queue.md)
        from services.live_queue_service import LiveQueueService
        queue = LiveQueueService(self.db)
        if queue.enabled() and queue.first_free_post() is None:
            try:
                self._mark_on_site(appointment)
            except Exception as e:
                self.db.rollback()
                messagebox.showerror("Ошибка", f"Не удалось отметить: {e}",
                                     parent=self.dialog)
                return
            self._done()
            messagebox.showinfo(
                "Свободных постов нет",
                f"{appointment.license_plate or 'Клиент'} отмечен «на месте». "
                f"Он первый на ближайший пост — программа позовёт его сама.")
            return

        try:
            self.service.mark_arrived(self.appointment_id)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось отметить приезд: {e}",
                                 parent=self.dialog)
            return

        plate = appointment.license_plate
        self._done()

        # Приёмщику дальше нужен наряд, а не список записей
        if self.orders_tab and plate:
            if messagebox.askyesno("Создать наряд",
                                   f"Отмечено. Создать наряд на {plate}?"):
                try:
                    self._open_order(appointment, plate)
                except Exception as e:
                    self.db.rollback()
                    messagebox.showerror("Ошибка", f"Не удалось открыть наряд: {e}")

    def _arrived_for_wash(self, appointment):
        """Мойка: живой очереди нет — отмечаем приезд и открываем наряд мойки."""
        try:
            self.service.mark_arrived(self.appointment_id)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось отметить приезд: {e}",
                                 parent=self.dialog)
            return
        plate = appointment.license_plate
        wash_class = appointment.wash_class
        name, phone = appointment.client_name, appointment.client_phone
        self._done()
        if not (self.orders_tab and plate):
            return
        try:
            order = self.orders_tab.order_service.create_order(
                plate, '', None, client_name=name, client_phone=phone,
                directions=['wash'], wash_class=wash_class)
            self.orders_tab.open_order_tab(order)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось открыть наряд мойки: {e}")

    def _mark_on_site(self, appointment):
        appointment.on_site = True
        self.db.commit()
        if getattr(self.service, 'is_remote', False) and appointment.server_id:
            # Нет связи — отметка остаётся в цеху и уйдёт при обмене
            try:
                self.service.update(appointment.server_id, on_site=True)
            except Exception:
                from services.booking_api import BookingApi
                BookingApi(self.db).remember(appointment, on_site=True)

    def _open_order(self, appointment, plate):
        """
        Наряд по записи — так же, как из живой очереди: пост, клиент,
        диаметр и услуги пакета (docs/live_queue.md). Нет диаметра —
        прежний путь: приёмщик укажет его сам.
        """
        from services.live_queue_service import LiveQueueService

        queue = LiveQueueService(self.db)
        if queue.booking_diameter(appointment):
            order = queue.open_booking_order(appointment)
            self.orders_tab.open_order_tab(order)
            return order

        self.orders_tab.license_entry.delete(0, tk.END)
        self.orders_tab.license_entry.insert(0, plate)
        self.orders_tab.prefilled_data = None
        self.orders_tab.create_new_order()
        return None

    def mark_no_show(self):
        if not messagebox.askyesno("Не приехал", "Отметить, что клиент не приехал?",
                                   parent=self.dialog):
            return
        try:
            self.service.mark_no_show(self.appointment_id)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", str(e), parent=self.dialog)
            return
        self._done()

    def cancel(self):
        if not messagebox.askyesno("Отмена записи", "Отменить эту запись?",
                                   parent=self.dialog):
            return
        try:
            self.service.cancel(self.appointment_id)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", str(e), parent=self.dialog)
            return
        self._done()
