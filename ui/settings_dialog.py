"""
Окно настроек программы.

Открывается из прайс-листа, то есть уже под PIN-кодом: здесь задаются
вещи, влияющие на деньги, на печатные документы и на то, куда уходят
отчёты.

Разделов стало много, поэтому содержимое прокручивается, а кнопки
«Сохранить» и «Закрыть» закреплены снизу и всегда на виду.
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from services import TelegramService, TelegramError, Recipient
from services.settings_service import SettingsService
from services.export_service import get_default_exports_dir
from services.label_service import LABEL_SIZES
from services.company_service import COMPANY_FIELDS
import styles


def _looks_like_time(value):
    """«07:00» или «24:00». Полночь пишем как 24:00 — так понятнее, что
    это конец дня, а не его начало."""
    try:
        hours, minutes = [int(part) for part in str(value).split(':')]
    except (ValueError, AttributeError):
        return False
    if hours == 24:
        return minutes == 0
    return 0 <= hours <= 23 and 0 <= minutes <= 59


def _looks_like_day_month(value):
    """
    «01.10» — день и месяц без года.

    Год не спрашиваем: напоминание о перекидке повторяется каждый год, и
    заставлять приёмщика раз в год лезть в настройки — верный способ
    получить сезон без напоминаний.
    """
    try:
        day, month = [int(part) for part in str(value).split('.')]
    except (ValueError, AttributeError):
        return False

    if not 1 <= month <= 12:
        return False

    # 31 число есть не в каждом месяце, но тридцатое — везде, кроме
    # февраля. Для напоминания о сезоне такая точность излишня:
    # проверяем грубо, а невозможную дату просто пропустим при рассылке
    return 1 <= day <= 31


def open_settings(parent, db):
    """Открыть окно настроек. Возвращает окно."""
    return SettingsDialog(parent, db).dialog


class SettingsDialog:
    def __init__(self, parent, db):
        self.db = db
        self.settings = SettingsService(db)
        self.telegram = TelegramService(db)

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Настройки")
        self.dialog.geometry("700x760")
        self.dialog.configure(bg=styles.COLORS['bg'])
        self.dialog.transient(parent.winfo_toplevel())
        self.dialog.grab_set()
        styles.center_window(self.dialog, parent.winfo_toplevel())

        outer = ttk.Frame(self.dialog, style='White.TFrame')
        outer.pack(fill='both', expand=True)

        heading = ttk.Frame(outer, style='White.TFrame')
        heading.pack(fill='x', padx=22, pady=(20, 6))
        styles.create_label(heading, "Настройки", 'CardHeading.TLabel').pack(anchor='w')

        content = self._scrollable_body(outer)

        self._build_company(content)
        self._build_sync(content)
        self._build_telegram(content)
        self._build_export_folder(content)
        self._build_shift(content)
        self._build_printing(content)
        self._build_service_buttons(content)
        self._build_orders(content)
        self._build_storage(content)

        # --- Кнопки: закреплены снизу, не уезжают вместе с содержимым ---
        buttons = ttk.Frame(outer, style='White.TFrame')
        buttons.pack(fill='x', padx=22, pady=(10, 18))
        styles.create_button(buttons, "Сохранить", self.save,
                             'Primary.TButton').pack(side='left', fill='x', expand=True, padx=(0, 6))
        styles.create_button(buttons, "Закрыть", self.dialog.destroy,
                             'Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(6, 0))

    # ------------------------------------------------------------------
    # Каркас
    # ------------------------------------------------------------------

    def _scrollable_body(self, parent):
        """Прокручиваемая область: разделов больше, чем влезает в окно."""
        holder = tk.Frame(parent, bg=styles.COLORS['bg_card'])
        holder.pack(fill='both', expand=True)

        canvas = tk.Canvas(holder, bg=styles.COLORS['bg_card'],
                           highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True, padx=(22, 8))

        body = ttk.Frame(canvas, style='White.TFrame')
        window = canvas.create_window((0, 0), window=body, anchor='nw')

        def on_body_resize(event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def on_canvas_resize(event):
            # Содержимое тянем по ширине окна, иначе поля обрезаются
            canvas.itemconfigure(window, width=event.width)

        body.bind('<Configure>', on_body_resize)
        canvas.bind('<Configure>', on_canvas_resize)

        def on_wheel(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')

        # Колесо привязываем к окну, а не к канве: иначе прокрутка
        # работает только когда мышь ровно над пустым местом
        self.dialog.bind_all('<MouseWheel>', on_wheel)
        self.dialog.bind('<Destroy>',
                         lambda e: self.dialog.unbind_all('<MouseWheel>'))

        return body

    def _section(self, parent, title):
        ttk.Separator(parent, orient='horizontal').pack(fill='x', pady=(10, 10))
        styles.create_label(parent, title, 'CardHeading.TLabel').pack(anchor='w', pady=(0, 8))

    def _hint(self, parent, text):
        ttk.Label(parent, text=text,
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary'],
                  wraplength=600, justify='left').pack(anchor='w', pady=(0, 10))

    # ------------------------------------------------------------------
    # Разделы
    # ------------------------------------------------------------------

    def _build_company(self, content):
        self._section(content, "Реквизиты")
        self._hint(content,
                   "Печатаются в шапке чека и акта хранения. Переехали или "
                   "сменили телефон — поправьте здесь, программу пересобирать "
                   "не нужно. Пустое поле просто не печатается.")

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(0, 10))
        grid.columnconfigure(1, weight=1)

        self.company_fields = {}
        for row, (key, title) in enumerate(COMPANY_FIELDS):
            styles.create_label(grid, title, 'Card.TLabel').grid(
                row=row, column=0, sticky='w', pady=3, padx=(0, 12))
            entry = styles.create_entry(grid, width=46)
            value = self.settings.get_raw(key)
            if value is None:
                value = self.settings.get(key, '') or ''
            entry.insert(0, value)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.company_fields[key] = entry

    def _build_sync(self, content):
        self._section(content, "Приложение для клиентов")
        self._hint(content,
                   "Пока выключено, программа работает сама по себе — как "
                   "и раньше, интернет ей не нужен.\n\n"
                   "После включения записи переезжают на сервер: их меняют "
                   "и приёмщик, и клиент из приложения, поэтому храниться "
                   "они должны в одном месте. Без интернета записать будет "
                   "нельзя — только посмотреть уже записанных. Наряды, "
                   "оплата, зарплата и печать чеков интернета не касаются "
                   "никогда.")

        from services.sync_service import SyncService
        self.sync = SyncService(self.db)

        self.sync_var = tk.BooleanVar(value=self.settings.get('sync_enabled', '0') == '1')
        ttk.Checkbutton(content, text="Обмениваться с сервером приложения",
                        variable=self.sync_var).pack(anchor='w', pady=(0, 8))

        styles.create_label(content, "Адрес сервера:",
                            'Card.TLabel').pack(anchor='w', pady=(0, 4))
        self.sync_url = styles.create_entry(content, width=52)
        self.sync_url.insert(0, self.sync.get_url())
        self.sync_url.pack(fill='x', pady=(0, 8))

        styles.create_label(content, "Ключ обмена:",
                            'Card.TLabel').pack(anchor='w', pady=(0, 4))
        self.sync_key = styles.create_entry(content, width=52)
        self.sync_key.insert(0, self.sync.get_key())
        self.sync_key.pack(fill='x', pady=(0, 8))

        sync_row = ttk.Frame(content, style='White.TFrame')
        sync_row.pack(fill='x', pady=(0, 6))
        styles.create_button(sync_row, "Проверить связь", self.test_sync,
                             'Secondary.TButton').pack(side='left')
        styles.create_button(sync_row, "Обменяться сейчас", self.run_sync,
                             'Secondary.TButton').pack(side='left', padx=(8, 0))

        self.sync_status = ttk.Label(sync_row, text="",
                                     font=(styles.DEFAULT_FONT, 9),
                                     background=styles.COLORS['bg_card'],
                                     foreground=styles.COLORS['text_secondary'],
                                     wraplength=380, justify='left')
        self.sync_status.pack(side='left', padx=(12, 0))

        last = self.sync.last_success()
        if last:
            self.sync_status.config(
                text=f"Последний обмен: {last:%d.%m.%Y %H:%M}")

    def _build_telegram(self, content):
        self._section(content, "Отправка отчётов в Telegram")
        self._hint(content,
                   "Создайте бота через @BotFather и вставьте его токен. "
                   "Получателей может быть несколько — владелец, бухгалтер, "
                   "управляющий. Свой номер чата человек узнаёт у бота "
                   "@userinfobot, а боту нужно один раз нажать «Старт».")

        styles.create_label(content, "Токен бота:", 'Card.TLabel').pack(anchor='w', pady=(0, 4))
        self.token_entry = styles.create_entry(content, width=60)
        self.token_entry.insert(0, self.telegram.get_token())
        self.token_entry.pack(fill='x', pady=(0, 10))

        styles.create_label(content, "Получатели:", 'Card.TLabel').pack(anchor='w', pady=(0, 4))

        self.recipients_tree = ttk.Treeview(
            content, columns=('name', 'chat', 'enabled'),
            show='headings', height=4)
        self.recipients_tree.heading('name', text='Имя')
        self.recipients_tree.heading('chat', text='Номер чата')
        self.recipients_tree.heading('enabled', text='Отправлять')
        self.recipients_tree.column('name', width=220)
        self.recipients_tree.column('chat', width=150)
        self.recipients_tree.column('enabled', width=100, anchor='center')
        self.recipients_tree.pack(fill='x', pady=(0, 6))
        self.recipients_tree.bind('<Double-1>', lambda e: self.toggle_recipient())

        self.recipients = self.telegram.get_recipients()
        self._refresh_recipients()

        recipient_buttons = ttk.Frame(content, style='White.TFrame')
        recipient_buttons.pack(fill='x', pady=(0, 8))
        for title, command in (("Добавить", self.add_recipient),
                               ("Изменить", self.edit_recipient),
                               ("Вкл/выкл", self.toggle_recipient),
                               ("Удалить", self.remove_recipient)):
            styles.create_button(recipient_buttons, title, command,
                                 'Secondary.TButton').pack(side='left', padx=(0, 6))

        telegram_row = ttk.Frame(content, style='White.TFrame')
        telegram_row.pack(fill='x', pady=(0, 6))
        styles.create_button(telegram_row, "Проверить связь", self.test_telegram,
                             'Secondary.TButton').pack(side='left')

        self.telegram_status = ttk.Label(telegram_row, text="",
                                         font=(styles.DEFAULT_FONT, 9),
                                         background=styles.COLORS['bg_card'],
                                         foreground=styles.COLORS['text_secondary'],
                                         wraplength=420, justify='left')
        self.telegram_status.pack(side='left', padx=(12, 0))

    def _build_export_folder(self, content):
        self._section(content, "Папка для сохранения отчётов")

        folder_row = ttk.Frame(content, style='White.TFrame')
        folder_row.pack(fill='x', pady=(0, 6))

        self.folder_entry = styles.create_entry(folder_row, width=48)
        self.folder_entry.insert(0, self.settings.get('export_folder', '') or '')
        self.folder_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))

        styles.create_button(folder_row, "Выбрать", self.choose_folder,
                             'Secondary.TButton').pack(side='left')

        self._hint(content,
                   f"Если не заполнено, отчёты сохраняются в папку рядом "
                   f"с программой:\n{get_default_exports_dir()}")

    def _build_shift(self, content):
        self._section(content, "Автоматическое закрытие смены")

        self.autoclose_var = tk.BooleanVar(
            value=self.settings.get('shift_autoclose_enabled', '1') == '1')
        ttk.Checkbutton(content, text="Закрывать забытую смену автоматически",
                        variable=self.autoclose_var).pack(anchor='w', pady=(0, 8))

        time_row = ttk.Frame(content, style='White.TFrame')
        time_row.pack(fill='x', pady=(0, 8))
        styles.create_label(time_row, "Время закрытия:", 'Card.TLabel').pack(side='left', padx=(0, 10))

        self.autoclose_time = tk.StringVar(
            value=self.settings.get('shift_autoclose_time', '09:00'))
        ttk.Combobox(time_row, textvariable=self.autoclose_time, width=8,
                     values=[f"{h:02d}:00" for h in range(24)],
                     font=styles.FONTS['normal']).pack(side='left')

        self.report_var = tk.BooleanVar(
            value=self.settings.get('shift_report_to_telegram', '1') == '1')
        ttk.Checkbutton(content, text="Отправлять сводку по смене в Telegram",
                        variable=self.report_var).pack(anchor='w', pady=(0, 10))

    def _build_printing(self, content):
        self._section(content, "Печать")

        self.label_var = tk.BooleanVar(
            value=self.settings.get('label_printing_enabled', '0') == '1')
        ttk.Checkbutton(content, text="Печатать наклейки на комплекты шин",
                        variable=self.label_var).pack(anchor='w', pady=(0, 6))

        label_row = ttk.Frame(content, style='White.TFrame')
        label_row.pack(fill='x', pady=(0, 10))
        styles.create_label(label_row, "Размер наклейки, мм:",
                            'Card.TLabel').pack(side='left', padx=(0, 10))
        self.label_size = tk.StringVar(value=self.settings.get('label_size', '58x40'))
        ttk.Combobox(label_row, textvariable=self.label_size, width=10,
                     values=LABEL_SIZES, font=styles.FONTS['normal']).pack(side='left')

        self.thermal_var = tk.BooleanVar(
            value=self.settings.get('thermal_receipt_enabled', '0') == '1')
        ttk.Checkbutton(content, text="Печатать чек на термопринтер вместо листа A4",
                        variable=self.thermal_var).pack(anchor='w', pady=(0, 6))

        thermal_row = ttk.Frame(content, style='White.TFrame')
        thermal_row.pack(fill='x', pady=(0, 6))
        styles.create_label(thermal_row, "Ширина ленты, мм:",
                            'Card.TLabel').pack(side='left', padx=(0, 10))
        self.thermal_width = tk.StringVar(
            value=self.settings.get('thermal_receipt_width', '58'))
        ttk.Combobox(thermal_row, textvariable=self.thermal_width, width=10,
                     values=['58', '80'], font=styles.FONTS['normal']).pack(side='left')

        self._hint(content,
                   "Печать идёт на принтер, назначенный в Windows основным. "
                   "Если принтеров два, выбор конкретного добавим, когда будет "
                   "известна модель.")

    def _build_service_buttons(self, content):
        self._section(content, "Кнопки услуг в наряде")
        self._hint(content,
                   "Кнопки берутся из прайс-листа: новая услуга получает кнопку "
                   "сама. Здесь задаётся только порядок — что в какой колонке "
                   "и на каком месте.")

        styles.create_button(content, "Настроить порядок кнопок",
                             self.open_service_layout,
                             'Secondary.TButton').pack(anchor='w', pady=(0, 10))

    def _build_orders(self, content):
        self._section(content, "Наряды и очередь")

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(0, 10))

        # Часы работы — строками «07:00», рядом с числовыми полями
        self.time_fields = {}
        for key, title in (('booking_opens_at', 'Запись с (часы работы)'),
                           ('booking_closes_at', 'Запись до (24:00 — полночь)')):
            row = ttk.Frame(content, style='White.TFrame')
            row.pack(fill='x', pady=(0, 6))
            styles.create_label(row, title, 'Card.TLabel').pack(
                side='left', padx=(0, 10))
            entry = styles.create_entry(row, width=8)
            entry.insert(0, self.settings.get(key, ''))
            entry.pack(side='left')
            self.time_fields[key] = entry

        self.numeric_fields = {}
        for row, (key, title) in enumerate([
            ('order_base_minutes', 'Базовое время наряда, мин'),
            ('default_posts', 'Постов по умолчанию'),
            ('queue_buffer_percent', 'Запас к прогнозу очереди, %'),
            ('order_autosave_minutes', 'Автосохранение наряда через, мин (0 — выкл.)'),
            ('booking_minutes_assembled', 'Запись: колёса в сборе, мин'),
            ('booking_minutes_tires', 'Запись: только шины, мин'),
            ('booking_minutes_unknown', 'Запись: колёса не выяснены, мин'),
            ('booking_slot_step', 'Шаг окон записи, мин'),
        ]):
            styles.create_label(grid, title, 'Card.TLabel').grid(
                row=row, column=0, sticky='w', pady=3)
            entry = styles.create_entry(grid, width=8)
            entry.insert(0, str(self.settings.get_int(key)))
            entry.grid(row=row, column=1, sticky='w', padx=(14, 0), pady=3)
            self.numeric_fields[key] = entry

    def _build_storage(self, content):
        self._section(content, "Хранение и сезон")
        self._hint(content,
                   "По этим числам приложение само пишет владельцам: что "
                   "заканчивается хранение и что пора переобуваться. Пишет "
                   "только тем, кто подключил напоминания в кабинете.\n"
                   "Срок выдачи со склада — за сколько дней клиент должен "
                   "записаться, если просит привезти свой комплект. "
                   "Ближайшие дни в приложении при этом закрыты. 0 — выдавать "
                   "в любой день.")

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(0, 10))

        for row, (key, title) in enumerate([
            ('storage_months', 'Срок хранения, месяцев (0 — без срока)'),
            ('storage_warn_days', 'Предупредить за, дней'),
            ('storage_lead_days',
             'Выдача со склада: записывать не раньше чем через, дней'),
        ]):
            styles.create_label(grid, title, 'Card.TLabel').grid(
                row=row, column=0, sticky='w', pady=3)
            entry = styles.create_entry(grid, width=8)
            entry.insert(0, str(self.settings.get_int(key)))
            entry.grid(row=row, column=1, sticky='w', padx=(14, 0), pady=3)
            self.numeric_fields[key] = entry

        self.season_var = tk.BooleanVar(
            value=self.settings.get('season_reminders_enabled', '1') == '1')
        ttk.Checkbutton(content, text="Звать на сезонную перекидку",
                        variable=self.season_var).pack(anchor='w', pady=(6, 6))

        # Осенью зовём заранее, весной позже — и это не прихоть:
        # осенью снег ложится внезапно и запись забивается на неделю,
        # а весной переобувшийся в марте попадёт под заморозки
        self.season_fields = {}
        for key, title in (('season_autumn_at', 'Осенью напомнить (дд.мм)'),
                           ('season_spring_at', 'Весной напомнить (дд.мм)')):
            row = ttk.Frame(content, style='White.TFrame')
            row.pack(fill='x', pady=(0, 6))
            styles.create_label(row, title, 'Card.TLabel').pack(
                side='left', padx=(0, 10))
            entry = styles.create_entry(row, width=8)
            entry.insert(0, self.settings.get(key, ''))
            entry.pack(side='left')
            self.season_fields[key] = entry

    # ------------------------------------------------------------------
    # Получатели Telegram
    # ------------------------------------------------------------------

    def _refresh_recipients(self):
        self.recipients_tree.delete(*self.recipients_tree.get_children())
        for index, recipient in enumerate(self.recipients):
            self.recipients_tree.insert(
                '', 'end', iid=str(index),
                values=(recipient.name or '—', recipient.chat_id,
                        'да' if recipient.enabled else 'нет'))

    def _selected_recipient_index(self):
        selection = self.recipients_tree.selection()
        if not selection:
            messagebox.showinfo("Получатели", "Сначала выберите получателя в списке",
                                parent=self.dialog)
            return None
        return int(selection[0])

    def _ask_recipient(self, recipient=None):
        """Спросить имя и номер чата. Возвращает Recipient или None."""
        window = tk.Toplevel(self.dialog)
        window.title("Получатель отчётов")
        window.configure(bg=styles.COLORS['bg_card'])
        window.transient(self.dialog)
        window.grab_set()

        frame = ttk.Frame(window, style='White.TFrame')
        frame.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(frame, "Имя (для себя):", 'Card.TLabel').pack(anchor='w')
        name_entry = styles.create_entry(frame, width=34)
        name_entry.pack(fill='x', pady=(4, 10))

        styles.create_label(frame, "Номер чата:", 'Card.TLabel').pack(anchor='w')
        chat_entry = styles.create_entry(frame, width=34)
        chat_entry.pack(fill='x', pady=(4, 10))

        if recipient:
            name_entry.insert(0, recipient.name)
            chat_entry.insert(0, recipient.chat_id)

        result = {}

        def confirm():
            chat_id = chat_entry.get().strip()
            if not chat_id:
                messagebox.showerror("Получатель", "Номер чата обязателен",
                                     parent=window)
                return
            result['recipient'] = Recipient(
                chat_id, name_entry.get().strip(),
                recipient.enabled if recipient else True)
            window.destroy()

        row = ttk.Frame(frame, style='White.TFrame')
        row.pack(fill='x', pady=(6, 0))
        styles.create_button(row, "Сохранить", confirm,
                             'Primary.TButton').pack(side='left', fill='x', expand=True, padx=(0, 5))
        styles.create_button(row, "Отмена", window.destroy,
                             'Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(5, 0))

        styles.center_window(window, self.dialog)
        name_entry.focus_set()
        self.dialog.wait_window(window)
        return result.get('recipient')

    def add_recipient(self):
        recipient = self._ask_recipient()
        if not recipient:
            return
        if any(r.chat_id == recipient.chat_id for r in self.recipients):
            messagebox.showinfo("Получатели", "Такой номер чата уже в списке",
                                parent=self.dialog)
            return
        self.recipients.append(recipient)
        self._refresh_recipients()

    def edit_recipient(self):
        index = self._selected_recipient_index()
        if index is None:
            return
        recipient = self._ask_recipient(self.recipients[index])
        if recipient:
            self.recipients[index] = recipient
            self._refresh_recipients()

    def toggle_recipient(self):
        index = self._selected_recipient_index()
        if index is None:
            return
        self.recipients[index].enabled = not self.recipients[index].enabled
        self._refresh_recipients()
        self.recipients_tree.selection_set(str(index))

    def remove_recipient(self):
        index = self._selected_recipient_index()
        if index is None:
            return
        recipient = self.recipients[index]
        if messagebox.askyesno("Получатели",
                               f"Убрать получателя «{recipient.title}»?",
                               parent=self.dialog):
            del self.recipients[index]
            self._refresh_recipients()

    # ------------------------------------------------------------------

    def _sync_answer(self, success, message):
        """Ответ обмена — из потока в интерфейс только через after."""
        self.dialog.after(0, lambda: self.sync_status.config(
            text=message,
            foreground=styles.COLORS['success'] if success
            else styles.COLORS['danger']))

    def _save_sync_settings(self):
        self.sync.save_settings(self.sync_url.get(), self.sync_key.get(),
                                self.sync_var.get())

    def test_sync(self):
        if not self.sync_url.get().strip() or not self.sync_key.get().strip():
            self.sync_status.config(text="Заполните адрес и ключ",
                                    foreground=styles.COLORS['danger'])
            return

        # Проверка идёт по сохранённым значениям
        self._save_sync_settings()
        self.sync_status.config(text="Проверяем связь…",
                                foreground=styles.COLORS['text_secondary'])

        def worker():
            from services.sync_service import SyncError
            try:
                state = self.sync.test_connection()
                self._sync_answer(
                    True,
                    f"Связь есть. На сервере клиентов: {state.get('clients', 0)}, "
                    f"ждут заявок: {state.get('pending_appointments', 0)}")
            except SyncError as e:
                self._sync_answer(False, str(e))
            except Exception as e:
                self._sync_answer(False, f"Не удалось проверить: {e}")

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def run_sync(self):
        self._save_sync_settings()
        if not self.sync.is_enabled():
            self.sync_status.config(
                text="Сначала включите обмен и заполните адрес с ключом",
                foreground=styles.COLORS['danger'])
            return

        self.sync_status.config(text="Обмениваемся…",
                                foreground=styles.COLORS['text_secondary'])

        def done(success, result):
            if not success:
                self._sync_answer(False, str(result))
                return
            self._sync_answer(
                True,
                f"Готово. Заявок на комплекты: "
                f"{result.get('new_storage_requests', 0)}")

        self.sync.run_in_background(on_done=done)

    def open_service_layout(self):
        from ui.service_buttons_dialog import open_service_buttons
        open_service_buttons(self.dialog, self.db)

    def choose_folder(self):
        current = self.folder_entry.get().strip() or get_default_exports_dir()
        chosen = filedialog.askdirectory(
            title="Куда сохранять отчёты", initialdir=current, parent=self.dialog)
        if chosen:
            self.folder_entry.delete(0, tk.END)
            self.folder_entry.insert(0, chosen)

    def test_telegram(self):
        """Проверить связь, не блокируя окно."""
        token = self.token_entry.get().strip()
        active = [r for r in self.recipients if r.enabled and r.chat_id]

        if not token or not active:
            self.telegram_status.config(
                text="Заполните токен и добавьте хотя бы одного получателя",
                foreground=styles.COLORS['danger'])
            return

        # Сохраняем сразу: проверка идёт по сохранённым значениям
        self.telegram.save_token(token)
        self.telegram.save_recipients(self.recipients)
        self.telegram_status.config(text="Проверяем связь…",
                                    foreground=styles.COLORS['text_secondary'])

        def done(success, message):
            # Из потока в интерфейс — только через after
            self.dialog.after(0, lambda: self.telegram_status.config(
                text=message,
                foreground=styles.COLORS['success'] if success else styles.COLORS['danger']))

        def worker():
            try:
                name, result = self.telegram.test_connection()
                done(result.all_delivered, f"Бот @{name}. {result.summary()}")
            except TelegramError as e:
                done(False, str(e))
            except Exception as e:
                done(False, f"Не удалось проверить: {e}")

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def save(self):
        folder = self.folder_entry.get().strip()
        if folder and not os.path.isdir(folder):
            if not messagebox.askyesno(
                    "Папка не найдена",
                    f"Папки «{folder}» нет. Создать её?", parent=self.dialog):
                return
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Ошибка", f"Не удалось создать папку:\n{e}",
                                     parent=self.dialog)
                return

        try:
            for key, entry in self.numeric_fields.items():
                value = entry.get().strip()
                if not value.isdigit():
                    messagebox.showerror(
                        "Ошибка", f"Значение «{value}» должно быть целым числом",
                        parent=self.dialog)
                    return
                self.settings.set(key, int(value), commit=False)

            for key, entry in self.time_fields.items():
                value = entry.get().strip()
                if not _looks_like_time(value):
                    messagebox.showerror(
                        "Ошибка",
                        f"Время «{value}» непонятно, нужно как 07:00",
                        parent=self.dialog)
                    return
                self.settings.set(key, value, commit=False)

            for key, entry in self.season_fields.items():
                value = entry.get().strip()
                if not _looks_like_day_month(value):
                    messagebox.showerror(
                        "Ошибка",
                        f"Дату «{value}» не разобрать, нужно как 01.10",
                        parent=self.dialog)
                    return
                self.settings.set(key, value, commit=False)

            self.settings.set('season_reminders_enabled',
                              '1' if self.season_var.get() else '0',
                              commit=False)

            for key, entry in self.company_fields.items():
                self.settings.set(key, entry.get().strip(), commit=False)

            self.settings.set('export_folder', folder, commit=False)
            self.settings.set('shift_autoclose_enabled',
                              '1' if self.autoclose_var.get() else '0', commit=False)
            self.settings.set('shift_autoclose_time', self.autoclose_time.get(), commit=False)
            self.settings.set('shift_report_to_telegram',
                              '1' if self.report_var.get() else '0', commit=False)

            self.settings.set('label_printing_enabled',
                              '1' if self.label_var.get() else '0', commit=False)
            self.settings.set('label_size', self.label_size.get(), commit=False)
            self.settings.set('thermal_receipt_enabled',
                              '1' if self.thermal_var.get() else '0', commit=False)
            self.settings.set('thermal_receipt_width', self.thermal_width.get(), commit=False)

            self.telegram.save_token(self.token_entry.get())
            self.telegram.save_recipients(self.recipients)
            self._save_sync_settings()

            messagebox.showinfo(
                "Готово",
                "Настройки сохранены.\nНазвание в шапке окна обновится "
                "после перезапуска программы.",
                parent=self.dialog)
            self.dialog.destroy()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить настройки:\n{e}",
                                 parent=self.dialog)
