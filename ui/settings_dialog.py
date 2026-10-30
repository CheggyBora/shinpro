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


def _minutes_of(value):
    """«07:00» в минуты от полуночи. «24:00» — конец суток, 1440."""
    hours, minutes = [int(part) for part in str(value).split(':')]
    return hours * 60 + minutes


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


def _no_posts(db):
    from services.live_queue_service import LiveQueueService
    return LiveQueueService(db).no_posts()


def open_settings(parent, db):
    """Открыть окно настроек. Возвращает окно."""
    return SettingsDialog(parent, db).dialog


class SettingsDialog:
    def __init__(self, parent, db, host=None, on_lock=None):
        """
        Настройки программы.

        host — рамка, в которую встроиться. Без него открывается своим
        окном, как раньше. Встроенные настройки нужны разделу в главном
        меню: окно поверх окна читается хуже, а настроек стало много.
        """
        self.db = db
        self.settings = SettingsService(db)
        self.telegram = TelegramService(db)
        self.embedded = host is not None

        # Поля собираются из разных разделов в общие словари: сохранение
        # читает их все сразу. Заводим здесь, а не в том разделе, который
        # строится первым, — порядок разделов менялся уже дважды
        self.numeric_fields = {}
        self.time_fields = {}
        self.text_fields = {}

        if self.embedded:
            # Окно верхнего уровня всё равно нужно: к нему привязываются
            # вложенные диалоги — выбор папки, ввод числа, вопросы
            self.dialog = host.winfo_toplevel()
            outer = ttk.Frame(host, style='White.TFrame')
            outer.pack(fill='both', expand=True)
        else:
            self.dialog = tk.Toplevel(parent)
            self.dialog.title("Настройки")
            self.dialog.geometry("860x760")
            self.dialog.configure(bg=styles.COLORS['bg'])
            self.dialog.transient(parent.winfo_toplevel())
            self.dialog.grab_set()
            styles.center_window(self.dialog, parent.winfo_toplevel())

            outer = ttk.Frame(self.dialog, style='White.TFrame')
            outer.pack(fill='both', expand=True)

        heading = ttk.Frame(outer, style='White.TFrame')
        heading.pack(fill='x', padx=22, pady=(14, 4))
        styles.create_label(heading, "Настройки", 'CardHeading.TLabel').pack(side='left')
        if on_lock is not None:
            styles.create_button(heading, "Закрыть доступ", on_lock,
                                 'Secondary.TButton').pack(side='right')

        # Две группы: как работает эта точка — и программа со связью
        # (решение владельца 29.10.2026). Восемнадцать кнопок в столбик не
        # влезали в экран 1366×768: нижние — «SMS и звонки», «Telegram»,
        # «Связь» — уходили за край, и прокрутить их было нельзя
        self._build_sections(outer, [
            ('Эта точка', [
                ('Что работает', 'Шиномонтаж и мойка, склад, наряд по фото',
                 [self._build_what_works]),
                ('Приём машин', 'Посты и очередь, запись через интернет, мойка',
                 [self._build_live_queue, self._build_booking, self._build_wash]),
                ('Наряды', 'Как ведётся наряд, кнопки услуг, выбор колеса',
                 [self._build_orders, self._build_service_buttons,
                  self._build_wheel_services]),
                ('Мастера и зарплата', 'Кто делит наряд, от чего считается, категории',
                 [self._build_masters, self._build_employee_roles]),
                ('Смена и касса', 'Закрытие смены, посты, статьи ордеров',
                 [self._build_shift, self._build_cash]),
                ('Клиенты и хранение', 'Группы клиентов, хранение шин и сезон',
                 [self._build_client_groups, self._build_storage]),
                ('Контрагенты', 'Поставщики и с кем работаете по задачам',
                 [self._build_counterparties]),
                ('Реквизиты и печать', 'Реквизиты, печать, папка для отчётов',
                 [self._build_company, self._build_printing, self._build_export_folder]),
            ]),
            ('Программа и связь', [
                ('Связь с сервером', 'Подключение по коду, дашборд и сайт записи',
                 [self._build_sync]),
                ('Telegram', 'Бот, кому какие сообщения',
                 [self._build_telegram]),
                ('Вход по звонку', 'Подтверждение номера в дашборде и на сайте записи',
                 [self._build_verify]),
            ]),
        ])

        # --- Кнопки: закреплены снизу, не уезжают вместе с содержимым ---
        buttons = ttk.Frame(outer, style='White.TFrame')
        buttons.pack(fill='x', padx=22, pady=(10, 18))
        styles.create_button(buttons, "Сохранить", self.save,
                             'Primary.TButton').pack(
            side='left', fill='x', expand=True, padx=(0, 6))

        # Встроенным настройкам закрываться некуда — это целый раздел,
        # а не окно поверх работы
        if not self.embedded:
            styles.create_button(buttons, "Закрыть", self.dialog.destroy,
                                 'Secondary.TButton').pack(
                side='left', fill='x', expand=True, padx=(6, 0))

    # ------------------------------------------------------------------
    # Каркас
    # ------------------------------------------------------------------

    def _build_sections(self, parent, groups):
        """
        Слева — список разделов по группам, справа — выбранный раздел.

        Список сам прокручивается: на маленьком экране он не должен уходить
        за край. Все разделы строятся сразу, а не по нажатию: в них лежат
        поля, которые читает сохранение, и строить их лениво значило бы
        сохранять только то, куда человек успел заглянуть.
        """
        body = ttk.Frame(parent, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=22, pady=(4, 0))

        side_holder = tk.Frame(body, bg=styles.COLORS['bg'], width=230)
        side_holder.pack(side='left', fill='y')
        side_holder.pack_propagate(False)
        side_canvas = tk.Canvas(side_holder, bg=styles.COLORS['bg'], highlightthickness=0, bd=0)
        side_canvas.pack(fill='both', expand=True)
        side = tk.Frame(side_canvas, bg=styles.COLORS['bg'])
        side_window = side_canvas.create_window((0, 0), window=side, anchor='nw')
        side.bind('<Configure>', lambda e: side_canvas.configure(
            scrollregion=side_canvas.bbox('all')))
        side_canvas.bind('<Configure>', lambda e: side_canvas.itemconfigure(
            side_window, width=e.width))

        def side_wheel(event):
            if side.winfo_height() > side_canvas.winfo_height():
                side_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        side_holder.bind('<Enter>', lambda e: self.dialog.bind_all('<MouseWheel>', side_wheel))
        side_holder.bind('<Leave>', lambda e: self.dialog.unbind_all('<MouseWheel>'))

        holder = ttk.Frame(body, style='White.TFrame')
        holder.pack(side='left', fill='both', expand=True, padx=(16, 0))

        self._pages = {}
        self._buttons = {}

        def paint(title, chosen):
            item, mark, label = self._buttons[title]
            bg = styles.COLORS['bg_card'] if chosen else styles.COLORS['bg']
            for widget in (item, label):
                widget.configure(bg=bg)
            mark.configure(bg=styles.COLORS['primary'] if chosen else bg)
            label.configure(fg=styles.COLORS['primary'] if chosen else styles.COLORS['text'],
                            font=(styles.DEFAULT_FONT, 10, 'bold' if chosen else 'normal'))

        def open_section(title):
            for name, page in self._pages.items():
                page.pack_forget()
                paint(name, name == title)
            self._pages[title].pack(fill='both', expand=True)

        self.open_section = open_section
        first = None
        for group, sections in groups:
            tk.Label(side, text=group.upper(), bg=styles.COLORS['bg'], anchor='w',
                     fg=styles.COLORS['text_secondary'],
                     font=(styles.DEFAULT_FONT, 8, 'bold')).pack(
                fill='x', padx=(10, 0), pady=(10 if first else 2, 4))
            for title, about, builders in sections:
                page = self._scrollable_body(holder)
                self._pages[title] = page.master.master
                # Заголовок раздела и одна строка — что здесь лежит
                tk.Label(page, text=title, bg=styles.COLORS['bg_card'], fg=styles.COLORS['text'],
                         font=(styles.DEFAULT_FONT, 15, 'bold')).pack(anchor='w', pady=(4, 0))
                ttk.Label(page, text=about, font=(styles.DEFAULT_FONT, 9),
                          background=styles.COLORS['bg_card'],
                          foreground=styles.COLORS['text_secondary']).pack(anchor='w', pady=(0, 2))
                for build in builders:
                    build(page)

                item = tk.Frame(side, bg=styles.COLORS['bg'], cursor='hand2')
                item.pack(fill='x', pady=1)
                mark = tk.Frame(item, width=4, bg=styles.COLORS['bg'])
                mark.pack(side='left', fill='y')
                # Пояснение — в заголовке раздела, а в списке только имя:
                # с подписями список снова не влезал в экран
                label = tk.Label(item, text=title, anchor='w', bg=styles.COLORS['bg'],
                                 fg=styles.COLORS['text'], font=(styles.DEFAULT_FONT, 10),
                                 padx=10, pady=6)
                label.pack(fill='x')
                for widget in (item, label):
                    widget.bind('<Button-1>', lambda e, t=title: open_section(t))
                self._buttons[title] = (item, mark, label)
                first = first or title

        open_section(first)

    def _scrollable_body(self, parent):
        """Прокручиваемая область: разделов больше, чем влезает в окно."""
        holder = tk.Frame(parent, bg=styles.COLORS['bg_card'])
        holder.pack(fill='both', expand=True)

        canvas = tk.Canvas(holder, bg=styles.COLORS['bg_card'],
                           highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True, padx=(0, 8))

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

        # Колесо привязываем на время, пока мышь над этим разделом.
        # Привязка ко всему окну работала, пока раздел был один; теперь
        # их десять, и колесо крутило бы все сразу — включая невидимые
        def grab_wheel(event):
            self.dialog.bind_all('<MouseWheel>', on_wheel)

        def release_wheel(event):
            self.dialog.unbind_all('<MouseWheel>')

        holder.bind('<Enter>', grab_wheel)
        holder.bind('<Leave>', release_wheel)
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
        # Код из 8 цифр вместо адреса с ключом: его выдают в дашборде,
        # ключ программа получает сама
        styles.create_button(sync_row, "Подключить по коду…", self.connect_by_code,
                             'Primary.TButton').pack(side='left', padx=(0, 8))
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

    def _build_verify(self, content):
        """
        Чем клиент подтверждает номер при первом входе в кабинет.

        Ключи здесь, а не на сервере, по одной причине: менять их
        должен владелец, а не тот, у кого есть доступ к серверу по
        SSH. Уезжают обменом вместе с остальными настройками.
        """
        self._section(content, "Подтверждение номера звонком")
        self._hint(content,
                   "Человек видит номер и кнопку «Позвонить». Вызов "
                   "сбрасывается до соединения, номер подтверждается сам — "
                   "вводить нечего, и для клиента звонок бесплатный.\n"
                   "Ключ берётся в личном кабинете flashcall.ru.\n"
                   "SMS мы не используем: пока ключ sms.ru ниже пуст, номер "
                   "подтверждается только звонком — в дашборде, на сайте записи "
                   "и при «Забыли ПИН». Без ключа flashcall.ru войти будет нельзя.")

        self._secret_row(content, 'call_token', "Ключ flashcall.ru:")
        # Ключ раньше просто сохранялся — ошибку узнавали, когда не могли
        # войти. Проверяем пробным звонком (решение владельца 30.10.2026)
        styles.create_button(content, "Проверить ключ пробным звонком", self.check_call_key,
                             'Secondary.TButton').pack(anchor='w', pady=(0, 10))

        self._section(content, "Код в SMS — запасной путь")
        self._hint(content,
                   "Нужен тем, кто не может позвонить: скрытый номер, "
                   "корпоративный тариф с запретом исходящих, роуминг.\n"
                   "Ключ берётся в личном кабинете sms.ru, раздел «API». "
                   "Имя отправителя необязательно и согласовывается у "
                   "провайдера; пусто — придёт с его общего номера.")

        self._secret_row(content, 'sms_key', "Ключ sms.ru:")

        row = ttk.Frame(content, style='White.TFrame')
        row.pack(fill='x', pady=(0, 10))
        styles.create_label(row, "Имя отправителя:", 'Card.TLabel').pack(
            side='left', padx=(0, 10))
        entry = styles.create_entry(row, width=24)
        entry.insert(0, self.settings.get('sms_sender', '') or '')
        entry.pack(side='left')
        self.text_fields['sms_sender'] = entry

        self._hint(content,
                   "Ключи уезжают на сервер при ближайшем обмене. "
                   "Поменяли — через несколько секунд работает новый.")

    def check_call_key(self):
        """Пробный звонок с ключом из поля — даже если его ещё не сохранили."""
        from ui.call_key_check import CallKeyCheck
        token = self.text_fields['call_token'].get().strip()
        if not token:
            messagebox.showinfo("Вход по звонку", "Сначала вставьте ключ flashcall.ru",
                                parent=self.dialog)
            return
        CallKeyCheck(self.dialog, token, self.settings.get('company_phone', '') or '')

    def _secret_row(self, parent, key, title):
        """
        Поле для ключа: показано точками, с кнопкой «Показать».

        Прятать его нужно не от злоумышленника — раздел и так под ПИНом,
        а от случайного взгляда: настройки открывают при людях, а ключ
        это деньги на счету провайдера.
        """
        row = ttk.Frame(parent, style='White.TFrame')
        row.pack(fill='x', pady=(0, 10))

        styles.create_label(row, title, 'Card.TLabel').pack(
            anchor='w', pady=(0, 4))

        line = ttk.Frame(row, style='White.TFrame')
        line.pack(fill='x')

        entry = styles.create_entry(line, width=52)
        entry.insert(0, self.settings.get(key, '') or '')
        entry.configure(show='•')
        entry.pack(side='left', fill='x', expand=True)

        def flip():
            shown = entry.cget('show') == ''
            entry.configure(show='•' if shown else '')
            button.config(text="Показать" if shown else "Скрыть")

        button = styles.create_button(line, "Показать", flip,
                                      'Secondary.TButton')
        button.pack(side='left', padx=(8, 0))

        self.text_fields[key] = entry

    def _build_telegram(self, content):
        self._section(content, "Отправка отчётов в Telegram")
        self._hint(content,
                   "Создайте бота через @BotFather и вставьте его токен.\n"
                   "Дальше номера чатов вводить не надо: человек открывает "
                   "вашего бота, нажимает «Старт» — и появляется в списке "
                   "по кнопке «Кто написал боту». Останется поставить "
                   "галочку тем, кому слать сводку.")

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
        for title, command in (("Кто написал боту", self.fetch_recipients),
                               ("Вкл/выкл", self.toggle_recipient),
                               ("Ссылка на бота", self.show_bot_link),
                               ("Добавить вручную", self.add_recipient),
                               ("Изменить", self.edit_recipient),
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

        # Кому что: склад — водителю, покраска — маляру, сводка задач —
        # владельцу. Никого не отметили — тем же, кому сводка по смене
        self._section(content, "Кому что отправлять")
        self._hint(content,
                   "Отметьте получателей для каждого вида сообщений. Не "
                   "отмечено никого — получат все, кому идёт сводка по смене. "
                   "Сохраняется сразу.\n"
                   "Людям, заведённым в дашборде («Доступ»), отчёты можно "
                   "отметить там же — по нику в Telegram; придут вдобавок к этим.")
        from services import telegram_outbox
        self.route_vars = {}
        active = [r for r in self.recipients if r.enabled and r.chat_id]
        routes = ttk.Frame(content, style='White.TFrame')
        routes.pack(fill='x', pady=(0, 8))
        for row, (kind, title) in enumerate(telegram_outbox.KINDS.items()):
            styles.create_label(routes, title, 'Card.TLabel').grid(
                row=row, column=0, sticky='w', pady=3, padx=(0, 12))
            chosen = set(telegram_outbox.route(self.db, kind))
            for column, person in enumerate(active, start=1):
                var = tk.BooleanVar(value=person.chat_id in chosen)
                self.route_vars[(kind, person.chat_id)] = var
                ttk.Checkbutton(routes, text=person.title, variable=var,
                                command=lambda k=kind: self.save_route(k)).grid(
                    row=row, column=column, sticky='w', padx=(0, 10))
        if not active:
            self._hint(content, "Сначала добавьте получателей выше.")

        digest = ttk.Frame(content, style='White.TFrame')
        digest.pack(fill='x', pady=(4, 6))
        self.digest_var = tk.BooleanVar(value=self.settings.is_on('task_digest_enabled'))
        ttk.Checkbutton(digest, text="Сводка задач владельцу: утром в",
                        variable=self.digest_var,
                        command=lambda: self.settings.set(
                            'task_digest_enabled', '1' if self.digest_var.get() else '0')
                        ).pack(side='left')
        self.digest_times = {}
        for key, after in (('task_digest_morning', 'и вечером в'), ('task_digest_evening', '')):
            entry = styles.create_entry(digest, width=6)
            entry.insert(0, self.settings.get(key) or '')
            entry.pack(side='left', padx=(6, 6))
            entry.bind('<FocusOut>', lambda e, k=key, w=entry: self.save_digest_time(k, w))
            entry.bind('<Return>', lambda e, k=key, w=entry: self.save_digest_time(k, w))
            self.digest_times[key] = entry
            if after:
                styles.create_label(digest, after, 'Card.TLabel').pack(side='left')

    def save_route(self, kind):
        from services import telegram_outbox
        chosen = [chat for (k, chat), var in self.route_vars.items() if k == kind and var.get()]
        telegram_outbox.set_route(self.db, kind, chosen)

    def save_digest_time(self, key, entry):
        from services.calendar_service import clean_time, TaskError
        try:
            value = clean_time(entry.get())
        except TaskError as e:
            messagebox.showerror("Telegram", str(e), parent=self.dialog)
            return
        if value:
            self.settings.set(key, value)
            entry.delete(0, tk.END)
            entry.insert(0, value)

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

    def _build_cash(self, content):
        self._section(content, "Статьи кассовых ордеров")
        self._hint(content,
                   "Из этих списков выбирают статью в приходном и расходном ордере. "
                   "Убранная статья остаётся у уже проведённых ордеров. Выдача "
                   "зарплаты всегда идёт статьёй «Зарплата».")
        from ui.cash_tab import CategoriesEditor
        CategoriesEditor(content, self.db).frame.pack(anchor='w', pady=(4, 8))
        self._hint(content,
                   "При открытии смены вводят, сколько наличных в кассе, при закрытии — "
                   "пересчитывают. Без пересчёта смену из программы не закрыть.")

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
            value=self.settings.get('shift_autoclose_time', '09:05'))
        ttk.Combobox(time_row, textvariable=self.autoclose_time, width=8,
                     values=sorted([f"{h:02d}:00" for h in range(24)] + ['09:05']),
                     font=styles.FONTS['normal']).pack(side='left')

        self.report_var = tk.BooleanVar(
            value=self.settings.get('shift_report_to_telegram', '1') == '1')
        ttk.Checkbutton(content, text="Отправлять сводку по смене в Telegram",
                        variable=self.report_var).pack(anchor='w', pady=(0, 10))

        # Это про смену, а не про запись: сколько постов считается
        # работающими, когда смену открыли. Раньше поле стояло в
        # «Записи» и читалось как «постов под запись» — две разные вещи
        # с похожими названиями на одном экране
        self._section(content, "Посты при открытии смены")

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(0, 10))
        self._numeric_grid(grid, [
            ('default_posts', 'Постов открывается по умолчанию'),
        ])

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

    def _build_booking(self, content):
        """
        Запись через интернет: принимать ли её вообще, когда и сколько.

        Вынесено в свой раздел из «Нарядов»: это другая работа. Наряды
        и очередь — про то, что происходит в цеху прямо сейчас, а запись
        — про то, что видит клиент в телефоне, и выключать её приходится
        отдельно: на ремонт, на выходные, на время, пока не разобрались.
        """
        self._section(content, "Запись через интернет")

        self.booking_var = tk.BooleanVar(
            value=self.settings.is_on('booking_enabled'))
        ttk.Checkbutton(content, text="Принимать запись через интернет",
                        variable=self.booking_var).pack(anchor='w', pady=(0, 6))

        self._hint(content,
                   "Выключите, если точка закрыта, работает только по "
                   "звонку или вы ещё не готовы пускать клиентов. "
                   "Выключение доходит до приложения при ближайшем обмене, "
                   "в течение десяти минут.\n"
                   "Уже записанные при этом никуда не денутся — они "
                   "останутся в ленте, и их надо либо принять, либо "
                   "обзвонить.")

        # Часы работы — строками «07:00»
        for key, title in (('booking_opens_at', 'Записывать с'),
                           ('booking_closes_at', 'Записывать до (24:00 — полночь)')):
            row = ttk.Frame(content, style='White.TFrame')
            row.pack(fill='x', pady=(0, 6))
            styles.create_label(row, title, 'Card.TLabel').pack(
                side='left', padx=(0, 10))
            entry = styles.create_entry(row, width=8)
            entry.insert(0, self.settings.get(key) or '')
            entry.pack(side='left')
            self.time_fields[key] = entry

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(6, 10))

        self._numeric_grid(grid, [
            # Без постов — сколько машин в час принимаем по записи
            ('booking_posts', 'Машин в час под запись' if _no_posts(self.db)
             else 'Постов под запись'),
            ('booking_slot_step', 'Шаг окон, мин'),
            ('booking_minutes_assembled', 'На колёса в сборе, мин'),
            ('booking_minutes_tires', 'На шины россыпью, мин'),
            ('booking_minutes_unknown', 'Если не выяснили, мин'),
        ])

        self._hint(content,
                   "Это общие настройки — по ним считаются все дни. "
                   "Отдельный день правится в разделе «Запись», прямо в "
                   "ленте: настроенный день главнее общего числа, потому "
                   "что приёмщик знает, кто в тот день работает.\n"
                   "Приём записи, посты и часы владелец может поменять и "
                   "из дашборда. Если поменяли с двух сторон, останется "
                   "то, что поставили позже.")

    def _numeric_grid(self, grid, fields):
        """Числовые поля столбиком. Складываются в один словарь на всё окно."""
        for row, (key, title) in enumerate(fields):
            styles.create_label(grid, title, 'Card.TLabel').grid(
                row=row, column=0, sticky='w', pady=3)
            entry = styles.create_entry(grid, width=8)
            entry.insert(0, str(self.settings.get_int(key)))
            entry.grid(row=row, column=1, sticky='w', padx=(14, 0), pady=3)
            self.numeric_fields[key] = entry

    def _build_orders(self, content):
        self._section(content, "Наряды и очередь")

        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(0, 10))

        self._numeric_grid(grid, [
            ('order_base_minutes', 'Базовое время наряда, мин'),
            ('queue_buffer_percent', 'Запас к прогнозу очереди, %'),
            ('order_autosave_minutes',
             'Автосохранение наряда через, мин (0 — выкл.)'),
        ])

    def _build_what_works(self, content):
        """Что работает на точке: направления, склад, наряд по фото."""
        from services import directions
        self._section(content, "Что работает на этом объекте")
        self._hint(content,
                   "Шиномонтаж, мойка или оба. Когда работают оба, сверху в "
                   "программе появляется переключатель «Шиномонтаж | Мойка». "
                   "Сохраняется сразу.")
        self.tire_var = tk.BooleanVar(value=directions.tire_on(self.db))
        self.wash_var = tk.BooleanVar(value=directions.wash_on(self.db))
        for text, var in (("Шиномонтаж", self.tire_var), ("Мойка", self.wash_var)):
            ttk.Checkbutton(content, text=text, variable=var,
                            command=self.save_directions).pack(anchor='w', pady=2)

        self._build_stock_switch(content)
        self._build_photo_switch(content)

    def _build_masters(self, content):
        """Кто делит шиномонтаж и от чего считается зарплата."""
        from services import directions
        self._section(content, "Мастера шиномонтажа")
        self.tire_assign_var = tk.BooleanVar(value=directions.tire_assign(self.db))
        ttk.Checkbutton(content, text="Выбирать мастеров на каждый наряд",
                        variable=self.tire_assign_var,
                        command=lambda: directions.set_tire_assign(
                            self.db, self.tire_assign_var.get())).pack(anchor='w', pady=2)
        self._hint(content,
                   "Выключено — как всегда: шиномонтаж делят все, кто был на "
                   "смене при создании наряда. Включено — наряд ставят на пост, "
                   "а в наряд кнопкой «Мастера наряда» добавляют тех, кто на нём "
                   "работает: делят только они. Мойка всегда назначается на "
                   "сотрудника в строке.")

        self._build_salary_base(content)

    def _build_photo_switch(self, content):
        from services import directions
        self._section(content, "Наряд по фото машины")
        self.photo_vars = {}
        for direction, title in (('tire', 'Шиномонтаж'), ('wash', 'Мойка')):
            var = tk.BooleanVar(value=self.settings.get(f'arrival_photo_{direction}') == '1')
            self.photo_vars[direction] = var
            ttk.Checkbutton(content, text=f"{title}: QR, номер по фото и обложка наряда",
                            variable=var,
                            command=lambda d=direction, v=var: directions.set_photo_on(
                                self.db, d, v.get())).pack(anchor='w', pady=2)
        self._hint(content,
                   "Включено — рядом с «Создать наряд» кнопка «QR»: телефон снимает "
                   "машину, номер читается сам, наряд получает обложку. Выключено — "
                   "кнопки нет, телефон это направление не предлагает, обложка не видна.")

    def _build_salary_base(self, content):
        from services import directions
        self._section(content, "От чего считается зарплата")
        self.salary_base_vars = {}
        for direction, title in (('tire', 'Шиномонтаж'), ('wash', 'Мойка')):
            row = ttk.Frame(content, style='White.TFrame')
            row.pack(fill='x', pady=2)
            styles.create_label(row, f"{title}:", 'Card.TLabel').pack(side='left')
            var = tk.StringVar(value=directions.salary_base(self.db, direction))
            self.salary_base_vars[direction] = var
            for value, text in (('revenue', 'от выручки'),
                                ('minus', 'от выручки минус расходники')):
                ttk.Radiobutton(row, text=text, value=value, variable=var,
                                command=lambda d=direction, v=var: self.settings.set(
                                    f'salary_base_{d}', v.get())).pack(side='left', padx=(10, 0))
        self._hint(content,
                   "Выручка — сумма услуги после всех скидок. Минус расходники — "
                   "то же, но без стоимости материалов услуги. С товаров зарплата "
                   "не начисляется ни в одном варианте.")

    def _build_stock_switch(self, content):
        self._section(content, "Склад")
        self.stock_var = tk.BooleanVar(value=self.settings.get('stock_enabled') == '1')
        ttk.Checkbutton(content, text="Вести склад: остатки товаров и материалов",
                        variable=self.stock_var,
                        command=self.save_stock).pack(anchor='w', pady=2)
        self._hint(content,
                   "Включено — появляется раздел «Склад». При оплате наряда "
                   "списываются проданные товары и материалы по услугам, при "
                   "полном возврате — возвращаются. Остаток может уйти в минус: "
                   "главному придёт сообщение в Telegram.")

    def _build_wash(self, content):
        """Посты мойки и запись на мойку."""
        from services import directions
        self._section(content, "Мойка")
        row = ttk.Frame(content, style='White.TFrame')
        row.pack(fill='x', pady=(0, 6))
        styles.create_label(row, "Постов мойки:", 'Card.TLabel').pack(side='left')
        self.wash_posts_var = tk.StringVar(value=str(directions.wash_posts(self.db)))
        posts = ttk.Spinbox(row, from_=1, to=20, width=5, textvariable=self.wash_posts_var,
                            command=self.save_wash_posts)
        posts.pack(side='left', padx=(8, 0))
        posts.bind('<FocusOut>', lambda e: self.save_wash_posts())
        self._hint(content, "Прайс мойки — в разделе «Прайс-лист», кнопка «Мойка». "
                            "Ставки мойки — в «Сотрудниках», «Изменить ставку».")

        self._section(content, "Запись на мойку")
        self.wash_booking_var = tk.BooleanVar(value=self.settings.get('wash_booking_enabled') == '1')
        ttk.Checkbutton(content, text="Принимать запись на мойку через личный кабинет",
                        variable=self.wash_booking_var,
                        command=lambda: self.settings.set(
                            'wash_booking_enabled', '1' if self.wash_booking_var.get() else '0')
                        ).pack(anchor='w', pady=2)
        grid = ttk.Frame(content, style='White.TFrame')
        grid.pack(fill='x', pady=(4, 6))
        self.wash_booking_fields = {}
        for row, (key, title) in enumerate((
                ('wash_booking_posts', 'Постов мойки под запись'),
                ('wash_booking_opens_at', 'Запись с (ЧЧ:ММ)'),
                ('wash_booking_closes_at', 'Запись до (ЧЧ:ММ)'),
                ('wash_booking_slot_step', 'Шаг окон, мин'),
                ('wash_booking_minutes', 'Сколько занимает мойка, мин'))):
            styles.create_label(grid, title, 'Card.TLabel').grid(row=row, column=0, sticky='w', pady=2)
            entry = styles.create_entry(grid, width=8)
            entry.insert(0, self.settings.get(key) or '')
            entry.grid(row=row, column=1, sticky='w', padx=(10, 0), pady=2)
            entry.bind('<FocusOut>', lambda e, k=key, w=entry: self.save_wash_booking(k, w))
            entry.bind('<Return>', lambda e, k=key, w=entry: self.save_wash_booking(k, w))
            self.wash_booking_fields[key] = entry
        self._hint(content, "Живой очереди у мойки нет: клиент записывается на время, "
                            "«Я на месте» у мойки не показывается.")

    def save_stock(self):
        from services.stock_service import StockService
        StockService(self.db).set_enabled(self.stock_var.get())

    def save_wash_booking(self, key, entry):
        value = entry.get().strip()
        if key.endswith('_at'):
            from services.calendar_service import clean_time, TaskError
            try:
                value = clean_time(value)
            except TaskError as e:
                messagebox.showerror("Запись на мойку", str(e), parent=self.dialog)
                return
        else:
            try:
                value = str(max(1, int(value)))
            except ValueError:
                messagebox.showerror("Запись на мойку", "Нужно число", parent=self.dialog)
                return
        if value:
            self.settings.set(key, value)
            entry.delete(0, tk.END)
            entry.insert(0, value)

    def save_directions(self):
        from services import directions
        try:
            directions.set_enabled(self.db, self.tire_var.get(), self.wash_var.get())
        except ValueError as e:
            messagebox.showerror("Направления", str(e), parent=self.dialog)
            # Вернуть галочки к тому, что сохранено, а не включать шиномонтаж
            # наугад: у объекта «только мойка» экран и база расходились
            self.tire_var.set(directions.tire_on(self.db))
            self.wash_var.set(directions.wash_on(self.db))

    def save_wash_posts(self):
        from services import directions
        try:
            value = max(1, min(20, int(self.wash_posts_var.get())))
        except ValueError:
            return
        self.settings.set(directions.WASH_POSTS_KEY, str(value))

    def _build_counterparties(self, content):
        self._section(content, "Контрагенты")
        self._hint(content,
                   "Поставщики шин и расходников, правка дисков. В задаче "
                   "календаря контрагент выбирается из этого списка. "
                   "Правки здесь сохраняются сразу.")
        from ui.counterparties_editor import CounterpartiesEditor
        self.counterparties = CounterpartiesEditor(content, self.db, self.dialog)

    def _build_client_groups(self, content):
        self._section(content, "Группы клиентов")
        self._hint(content,
                   "Кому предлагать допы, а кому — только то, за чем "
                   "приехал. Группу ставят в наряде или в карточке клиента "
                   "кнопкой «⋯» рядом с именем: на экране видно только "
                   "значок, код и название — лишь когда нажмёшь. "
                   "Группы не уходят с этого компьютера: их нет ни на "
                   "сервере, ни в личном кабинете, ни на чеке.")
        self._hint(content, "Правки здесь сохраняются сразу.")

        from ui.client_groups_editor import ClientGroupsEditor
        self.client_groups = ClientGroupsEditor(content, self.db, self.dialog)

    def _build_employee_roles(self, content):
        self._section(content, "Категории мастеров")
        self._hint(content,
                   "Отмеченные услуги этой категории не начисляются. Их доля "
                   "делится только между теми в наряде, кому начисляется: "
                   "правку делал мастер — мастер и получает за неё полный "
                   "процент. Категорию сотруднику ставят на вкладке "
                   "«Сотрудники», кнопкой «Категория».")
        self._hint(content,
                   "Правки сохраняются сразу и действуют на следующие оплаты. "
                   "Уже начисленное не пересчитывается.")

        from ui.employee_roles_editor import EmployeeRolesEditor
        self.employee_roles = EmployeeRolesEditor(content, self.db, self.dialog)

    def _build_wheel_services(self, content):
        self._section(content, "Выбор колеса")
        self._hint(content,
                   "Когда в наряд пробивают услугу из списка, открывается "
                   "схема машины сверху: приёмщик отмечает колёса, на "
                   "которых делали работу. Количество в наряде встаёт по "
                   "числу колёс, а сами колёса видны в строке наряда, в чеке "
                   "и в истории машины — «Ремонт жгутом (ПЛ, ЗП)». "
                   "Не знают, какое колесо, — «Пропустить».")
        self._hint(content, "Правки здесь сохраняются сразу.")

        from ui.wheel_services_editor import WheelServicesEditor
        self.wheel_services = WheelServicesEditor(content, self.db, self.dialog)

    def _build_live_queue(self, content):
        self._section(content, "Живая очередь")
        self._hint(content,
                   "Освободившийся пост сначала идёт записанным. Машину из "
                   "очереди программа зовёт, только если ближайшая запись "
                   "останется обеспечена постами: её работа вместе с запасом "
                   "на допы закончится раньше, чем пост понадобится. Чем больше "
                   "запас, тем реже записанные ждут, но тем чаще посты "
                   "простаивают перед часом записи.")
        self._hint(content,
                   "Наряд из очереди открывается сразу с услугами за комплект — "
                   "по тому, что клиент выбрал: колёса в сборе или только шины. "
                   "Время пакетов (на дисках — 30 минут, только шины — час) "
                   "общее с записью и задаётся в разделе «Запись». "
                   "Правки здесь сохраняются сразу.")

        from ui.queue_settings_editor import QueueSettingsEditor
        self.queue_settings = QueueSettingsEditor(content, self.db, self.dialog)

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
            entry.insert(0, self.settings.get(key) or '')
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

    def fetch_recipients(self):
        """
        Спросить у бота, кто ему писал, и пополнить список.

        Новые появляются выключенными: нажал «Старт» — ещё не значит,
        что человеку нужна сводка по смене с выручкой.
        """
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showinfo("Получатели",
                                "Сначала вставьте токен бота",
                                parent=self.dialog)
            return

        # Токен мог быть только что вписан и ещё не сохранён
        self.telegram.save_token(token)

        try:
            added, seen = self.telegram.fetch_people()
        except Exception as e:
            messagebox.showerror("Получатели",
                                 f"Не удалось спросить у бота:\n{e}",
                                 parent=self.dialog)
            return

        self.recipients = self.telegram.get_recipients()
        self._refresh_recipients()

        if added:
            messagebox.showinfo(
                "Получатели",
                f"Добавлено: {added}.\n\nОтметьте галочкой тех, кому "
                f"слать сводку — кнопка «Вкл/выкл».",
                parent=self.dialog)
        elif seen:
            messagebox.showinfo("Получатели",
                                "Новых нет — все, кто писал, уже в списке.",
                                parent=self.dialog)
        else:
            messagebox.showinfo(
                "Получатели",
                "Боту никто не написал.\n\nДайте человеку ссылку "
                "(кнопка «Ссылка на бота») и попросите нажать «Старт».\n"
                "Телеграм хранит сообщения сутки: если нажали давно, "
                "пусть напишут боту ещё раз.",
                parent=self.dialog)

    def show_bot_link(self):
        """Ссылку даём человеку — по ней он откроет бота и нажмёт «Старт»."""
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showinfo("Бот", "Сначала вставьте токен бота",
                                parent=self.dialog)
            return

        self.telegram.save_token(token)

        try:
            link = self.telegram.bot_link()
        except Exception as e:
            messagebox.showerror("Бот", f"Не удалось узнать имя бота:\n{e}",
                                 parent=self.dialog)
            return

        try:
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(link)
            copied = "\n\nСсылка скопирована — можно вставить в переписку."
        except Exception:
            copied = ""

        messagebox.showinfo(
            "Ссылка на бота",
            f"{link}\n\nОткройте её и нажмите «Старт», потом вернитесь "
            f"сюда и нажмите «Кто написал боту».{copied}",
            parent=self.dialog)

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

    def connect_by_code(self):
        from tkinter import simpledialog
        code = simpledialog.askstring(
            "Подключить по коду",
            "Код подключения — 8 цифр.\n"
            "Его выдают в дашборде: «Точки» → «Переподключить»\n"
            "или «Заказчики» → «Код».",
            parent=self.dialog)
        if not code:
            return

        url = self.sync_url.get().strip()
        self.sync_status.config(text="Подключаемся…",
                                foreground=styles.COLORS['text_secondary'])

        def worker():
            from services.sync_service import SyncError
            try:
                answer = self.sync.connect_by_code(code, url or None)
            except SyncError as e:
                self._sync_answer(False, str(e))
                return
            except Exception as e:
                self._sync_answer(False, f"Не получилось подключиться: {e}")
                return
            self.dialog.after(0, lambda: self._connected(answer))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _connected(self, answer):
        """Код сработал: поля — как сохранил обмен, и куда идти дальше."""
        self.sync_url.delete(0, 'end')
        self.sync_url.insert(0, self.sync.get_url())
        self.sync_key.delete(0, 'end')
        self.sync_key.insert(0, self.sync.get_key())
        self.sync_var.set(True)
        self._sync_answer(True, f"Подключено: {answer.get('account')} — {answer.get('shop')}")

        lines = [f"Точка «{answer.get('shop')}» подключена к «{answer.get('account')}»."]
        if answer.get('admin_url'):
            line = f"\nДашборд: {answer['admin_url']}"
            if answer.get('owner_phone'):
                line += f"\nВход по номеру {answer['owner_phone']}, код придёт звонком."
            lines.append(line)
        if answer.get('lk_url'):
            lines.append(f"\nЗапись для клиентов: {answer['lk_url']}")
        messagebox.showinfo("Подключено", '\n'.join(lines), parent=self.dialog)

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

            hours = {}
            for key, entry in self.time_fields.items():
                value = entry.get().strip()
                if not _looks_like_time(value):
                    messagebox.showerror(
                        "Ошибка",
                        f"Время «{value}» непонятно, нужно как 07:00",
                        parent=self.dialog)
                    return
                hours[key] = value

            # Закрытие раньше открытия — окон в кабинете не будет вовсе,
            # и человек решит, что сломалась запись. Проверяем здесь, а
            # не при показе: отказ в момент сохранения понятен, а
            # пустой кабинет через неделю — нет
            opens = hours.get('booking_opens_at')
            closes = hours.get('booking_closes_at')
            if opens and closes and _minutes_of(opens) >= _minutes_of(closes):
                messagebox.showerror(
                    "Ошибка",
                    f"Записывать с {opens} до {closes} нельзя: закрытие "
                    f"раньше открытия.\nДля круглосуточной записи "
                    f"поставьте с 00:00 до 24:00.",
                    parent=self.dialog)
                return

            for key, value in hours.items():
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

            self.settings.set('booking_enabled',
                              '1' if self.booking_var.get() else '0',
                              commit=False)

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

            # Ключи от звонков и SMS. Провайдер включается сам, как
            # только появился ключ: держать отдельный переключатель
            # «включено» значит однажды вписать ключ и не понять,
            # почему ничего не работает
            for key, entry in self.text_fields.items():
                self.settings.set(key, entry.get().strip(), commit=False)

            self.settings.set(
                'call_provider',
                'flashcall' if self.text_fields['call_token'].get().strip()
                else 'off', commit=False)
            self.settings.set(
                'sms_provider',
                'smsru' if self.text_fields['sms_key'].get().strip()
                else 'off', commit=False)
            self.telegram.save_recipients(self.recipients)
            self._save_sync_settings()

            # Часы записи, число постов и приём записи клиент видит
            # сразу. Особенно выключатель: пока он едет десять минут,
            # люди продолжают записываться на закрытую точку
            from services import sync_nudge

            sync_nudge.request('изменены настройки')

            messagebox.showinfo(
                "Готово",
                "Настройки сохранены.\nНазвание в шапке окна обновится "
                "после перезапуска программы.",
                parent=self.dialog)

            # Встроенные настройки — это раздел программы, закрывать его
            # после сохранения нельзя: человеку некуда деться
            if not self.embedded:
                self.dialog.destroy()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить настройки:\n{e}",
                                 parent=self.dialog)
