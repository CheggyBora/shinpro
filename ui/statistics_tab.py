"""
Раздел «Отчёты».

Четыре подраздела:
  - Сводка — итоги за период и детализация по услугам
  - По нарядам — каждый наряд с расходниками, зарплатой и маржой
  - По мастерам — сколько заработал каждый
  - Нормативы — плановое время услуг против фактического
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

from tkcalendar import DateEntry

from services.statistics_service import StatisticsService
from services.export_service import export_rows, open_file
from utils import get_moscow_time, format_phone
import styles


class StatisticsTab:
    def __init__(self, parent, db):
        self.db = db
        self.stats_service = StatisticsService(db)

        self.frame = ttk.Frame(parent, style='BG.TFrame')

        main = ttk.Frame(self.frame, style='BG.TFrame')
        main.pack(fill='both', expand=True, padx=24, pady=20)

        styles.create_label(main, "Отчёты", 'Heading.TLabel').pack(anchor='w', pady=(0, 16))

        # --- Период ---------------------------------------------------
        period_card = styles.create_card_frame(main)
        period_card.pack(fill='x', pady=(0, 16))

        period = ttk.Frame(period_card, style='White.TFrame')
        period.pack(fill='x', padx=20, pady=16)

        styles.create_label(period, "С:", 'Card.TLabel').pack(side='left', padx=(0, 8))
        self.date_from = DateEntry(period, width=12, date_pattern='dd.mm.yyyy',
                                   font=styles.FONTS['normal'])
        self.date_from.set_date(get_moscow_time() - timedelta(days=30))
        self.date_from.pack(side='left', padx=(0, 18))

        styles.create_label(period, "По:", 'Card.TLabel').pack(side='left', padx=(0, 8))
        self.date_to = DateEntry(period, width=12, date_pattern='dd.mm.yyyy',
                                 font=styles.FONTS['normal'])
        self.date_to.set_date(get_moscow_time())
        self.date_to.pack(side='left', padx=(0, 18))

        styles.create_button(period, "Показать", self.reload,
                             'Primary.TButton').pack(side='left', padx=(0, 8))
        styles.create_button(period, "Сохранить в Excel", self.export_current,
                             'Secondary.TButton').pack(side='left', padx=(0, 6))
        styles.create_button(period, "Отправить в Telegram", self.send_to_telegram,
                             'Secondary.TButton').pack(side='left')

        self.send_status = ttk.Label(period, text="", font=(styles.DEFAULT_FONT, 9),
                                     background=styles.COLORS['bg_card'],
                                     foreground=styles.COLORS['text_secondary'])
        self.send_status.pack(side='left', padx=(12, 0))

        # --- Подразделы -----------------------------------------------
        self.nav = styles.NavBar(main, compact=True, on_select=self.on_section)
        self.nav.pack(fill='x')

        content = tk.Frame(main, bg=styles.COLORS['bg'])
        content.pack(fill='both', expand=True)

        self.summary_frame = ttk.Frame(content, style='BG.TFrame')
        self.orders_frame = ttk.Frame(content, style='BG.TFrame')
        self.masters_frame = ttk.Frame(content, style='BG.TFrame')
        self.norms_frame = ttk.Frame(content, style='BG.TFrame')

        self._build_summary()
        self._build_orders()
        self._build_masters()
        self._build_norms()

        self.nav.add('Сводка', self.summary_frame)
        self.nav.add('По нарядам', self.orders_frame)
        self.nav.add('По мастерам', self.masters_frame)
        self.nav.add('Нормативы времени', self.norms_frame)

        self.reload()

    # ------------------------------------------------------------------
    # Построение подразделов
    # ------------------------------------------------------------------

    def _make_tree(self, parent, columns, widths, height=None):
        frame = ttk.Frame(parent, style='White.TFrame')
        frame.pack(fill='both', expand=True)

        options = {'columns': columns, 'show': 'headings'}
        if height:
            options['height'] = height
        tree = ttk.Treeview(frame, **options)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            anchor = 'w' if width > 150 else 'center'
            tree.column(column, width=width, anchor=anchor)
        tree.pack(side='left', fill='both', expand=True)

        scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        scroll.pack(side='right', fill='y')
        tree.config(yscrollcommand=scroll.set)
        return tree

    def _build_summary(self):
        cards = ttk.Frame(self.summary_frame, style='BG.TFrame')
        cards.pack(fill='x', pady=(16, 16))

        def stat_card(column, title):
            card = styles.create_card_frame(cards)
            card.grid(row=0, column=column, sticky='nsew',
                      padx=(0 if column == 0 else 12, 0))
            inner = ttk.Frame(card, style='White.TFrame')
            inner.pack(fill='both', expand=True, padx=20, pady=16)
            styles.create_label(inner, title, 'Muted.TLabel').pack(anchor='w')
            value = styles.create_label(inner, "0", 'CardValue.TLabel')
            value.pack(anchor='w', pady=(6, 0))
            return inner, value

        for column in range(5):
            cards.columnconfigure(column, weight=1, uniform='stat')

        _, self.cars_value = stat_card(0, "Обслужено машин")
        _, self.services_value = stat_card(1, "Всего услуг")
        _, self.avg_value = stat_card(2, "Средний чек")
        _, self.revenue_value = stat_card(3, "Выручка")
        margin_inner, self.margin_value = stat_card(4, "Маржа")

        self.margin_detail = styles.create_label(margin_inner, "", 'Muted.TLabel')
        self.margin_detail.pack(anchor='w', pady=(4, 0))

        table_card = styles.create_card_frame(self.summary_frame)
        table_card.pack(fill='both', expand=True)

        inner = ttk.Frame(table_card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=20, pady=18)

        styles.create_label(inner, "Детализация по услугам",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 12))

        self.services_tree = self._make_tree(
            inner,
            ('Услуга', 'Количество', 'Выручка', 'Расходники', 'Маржа'),
            (340, 120, 140, 140, 140))

    def _build_orders(self):
        card = styles.create_card_frame(self.orders_frame)
        card.pack(fill='both', expand=True, pady=(16, 0))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=20, pady=18)

        header = ttk.Frame(inner, style='White.TFrame')
        header.pack(fill='x', pady=(0, 12))
        styles.create_label(header, "Наряды за период",
                            'CardHeading.TLabel').pack(side='left')
        self.orders_total_label = ttk.Label(header, text="",
                                            font=(styles.DEFAULT_FONT, 9),
                                            background=styles.COLORS['bg_card'],
                                            foreground=styles.COLORS['text_secondary'])
        self.orders_total_label.pack(side='right')

        self.orders_tree = self._make_tree(
            inner,
            ('Дата', 'Наряд', 'Автомобиль', 'Клиент', 'Услуг',
             'Сумма', 'Скидка', 'Расходники', 'Зарплата', 'Маржа', 'Оплата'),
            (130, 70, 120, 170, 70, 100, 90, 110, 100, 100, 90))
        self.orders_tree.bind('<Double-1>', lambda e: self.show_order_details())

        ttk.Label(inner, text="Двойной клик по наряду — состав и разбивка зарплаты",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary']).pack(anchor='w', pady=(8, 0))

    def _build_masters(self):
        card = styles.create_card_frame(self.masters_frame)
        card.pack(fill='both', expand=True, pady=(16, 0))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=20, pady=18)

        styles.create_label(inner, "Заработок мастеров за период",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 12))

        self.masters_tree = self._make_tree(
            inner,
            ('Мастер', 'Нарядов', 'Выручка по нарядам', 'Начислено'),
            (200, 130, 200, 160))

    def _build_norms(self):
        card = styles.create_card_frame(self.norms_frame)
        card.pack(fill='both', expand=True, pady=(16, 0))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=20, pady=18)

        styles.create_label(inner, "Норматив времени против фактического",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))
        ttk.Label(inner,
                  text="Считается по нарядам из одной услуги — так видно чистое время работы. "
                       "Показаны услуги, по которым накопилось хотя бы 5 замеров.",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary'],
                  wraplength=900, justify='left').pack(anchor='w', pady=(0, 12))

        self.norms_tree = self._make_tree(
            inner,
            ('Услуга', 'Норматив, мин', 'Фактически, мин', 'Расхождение', 'Замеров'),
            (340, 140, 150, 140, 110))

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------

    def period(self):
        start = datetime.combine(self.date_from.get_date(), datetime.min.time())
        end = datetime.combine(self.date_to.get_date(), datetime.max.time())
        return start, end

    def on_section(self, index):
        # Отчёты считаются заново при переключении: период мог поменяться
        if hasattr(self, 'stats_service'):
            self.reload()

    def reload(self):
        try:
            self.load_summary()
            self.load_orders()
            self.load_masters()
            self.load_norms()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось построить отчёт:\n{e}")

    def load_summary(self):
        start, end = self.period()
        stats = self.stats_service.get_sales_statistics(start, end)
        self.summary_data = stats

        def money(value):
            return f"{value:,.0f} ₽".replace(',', ' ')

        self.cars_value.config(text=str(stats['total_cars']))
        self.services_value.config(text=str(stats['total_services']))
        self.avg_value.config(text=money(stats['average_check']))
        self.revenue_value.config(text=money(stats['total_revenue']))
        self.margin_value.config(text=money(stats['margin']))

        detail = (f"расходники {money(stats['total_consumables'])}  ·  "
                  f"зарплата {money(stats['total_salary'])}")
        # Возвраты и гарантию показываем только когда они есть,
        # чтобы не забивать карточку нулями
        if stats.get('total_refunds'):
            detail += f"\nвозвраты {money(stats['total_refunds'])}"
        if stats.get('warranty_count'):
            detail += f"  ·  гарантийных: {stats['warranty_count']}"
        self.margin_detail.config(text=detail)

        for row in self.services_tree.get_children():
            self.services_tree.delete(row)
        for service in stats['services']:
            self.services_tree.insert('', 'end', values=(
                service['name'], service['count'],
                f"{service['revenue']:.2f} ₽",
                f"{service['consumables']:.2f} ₽",
                f"{service['margin']:.2f} ₽",
            ))
        styles.stripe_rows(self.services_tree)

    def load_orders(self):
        start, end = self.period()
        self.orders_data = self.stats_service.get_orders_report(start, end)

        for row in self.orders_tree.get_children():
            self.orders_tree.delete(row)

        for item in self.orders_data:
            # Помечаем прямо в номере: возврат или гарантийная переделка
            marks = []
            if item['refunded']:
                marks.append('возврат' if item['refund_type'] != 'reversal' else 'сторно')
            if item['is_warranty']:
                marks.append('гарантия')
            label = f"{item['id']} ({', '.join(marks)})" if marks else str(item['id'])

            self.orders_tree.insert('', 'end', values=(
                item['paid_at'].strftime('%d.%m.%Y %H:%M') if item['paid_at'] else '—',
                label,
                item['license_plate'],
                item['client_name'] or '—',
                item['services_count'],
                f"{item['net']:.0f} ₽",
                f"{item['discount']:.0f} ₽" if item['discount'] > 0 else '—',
                f"{item['consumables']:.0f} ₽" if item['consumables'] else '—',
                f"{item['salary_total']:.0f} ₽",
                f"{item['margin']:.0f} ₽",
                item['payment_method'],
            ), tags=(str(item['id']),))
        styles.stripe_rows(self.orders_tree)

        total = sum(i['net'] for i in self.orders_data)
        margin = sum(i['margin'] for i in self.orders_data)
        self.orders_total_label.config(
            text=f"Нарядов: {len(self.orders_data)}  ·  "
                 f"Сумма: {total:,.0f} ₽".replace(',', ' ') +
                 f"  ·  Маржа: {margin:,.0f} ₽".replace(',', ' '))

    def load_masters(self):
        start, end = self.period()
        self.masters_data = self.stats_service.get_masters_report(start, end)

        for row in self.masters_tree.get_children():
            self.masters_tree.delete(row)
        for master in self.masters_data:
            self.masters_tree.insert('', 'end', values=(
                f"№{master['employee_id']}",
                master['orders'],
                f"{master['revenue']:.2f} ₽",
                f"{master['salary']:.2f} ₽",
            ))
        styles.stripe_rows(self.masters_tree)

    def load_norms(self):
        self.norms_data = self.stats_service.get_duration_accuracy(min_orders=5)

        for row in self.norms_tree.get_children():
            self.norms_tree.delete(row)
        for norm in self.norms_data:
            difference = norm['difference']
            self.norms_tree.insert('', 'end', values=(
                norm['service'],
                norm['planned_minutes'],
                norm['actual_minutes'],
                f"+{difference}" if difference > 0 else str(difference),
                norm['measurements'],
            ))
        styles.stripe_rows(self.norms_tree)

    # ------------------------------------------------------------------
    # Карточка наряда
    # ------------------------------------------------------------------

    def show_order_details(self):
        selection = self.orders_tree.selection()
        if not selection:
            return

        order_id = int(self.orders_tree.item(selection[0])['tags'][0])
        item = next((o for o in self.orders_data if o['id'] == order_id), None)
        if not item:
            return

        dialog = tk.Toplevel(self.frame)
        dialog.title(f"Наряд №{order_id}")
        dialog.geometry("720x600")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(self.frame.winfo_toplevel())
        styles.center_window(dialog, self.frame.winfo_toplevel())

        content = ttk.Frame(dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(content, f"Наряд №{order_id} · {item['license_plate']}",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 4))

        client = item['client_name'] or 'клиент не указан'
        if item['client_phone']:
            client += f" · {format_phone(item['client_phone'])}"
        when = item['paid_at'].strftime('%d.%m.%Y %H:%M') if item['paid_at'] else '—'
        ttk.Label(content, text=f"{client}\n{when} · {item['payment_method']}",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary'],
                  justify='left').pack(anchor='w', pady=(0, 14))

        # Состав наряда
        styles.create_label(content, "Услуги", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 8))

        services_tree = self._make_tree(
            content, ('Услуга', 'Кол-во', 'Цена', 'Скидка', 'Итого', 'Расходники'),
            (240, 70, 90, 80, 90, 110), height=8)

        from services.order_service import OrderService
        for line in item['items']:
            services_tree.insert('', 'end', values=(
                line.service.name,
                line.quantity,
                f"{line.price:.0f}",
                f"{line.discount_percent}%",
                f"{OrderService.item_total(line):.0f}",
                f"{OrderService.item_consumables(line):.0f}",
            ))
        styles.stripe_rows(services_tree)

        # Зарплата по мастерам
        styles.create_label(content, "Зарплата мастеров",
                            'CardHeading.TLabel').pack(anchor='w', pady=(14, 8))

        if item['salaries']:
            for entry in item['salaries']:
                ttk.Label(content,
                          text=f"Мастер №{entry['employee_id']}: {entry['amount']:.2f} ₽",
                          font=(styles.DEFAULT_FONT, 10),
                          background=styles.COLORS['bg_card'],
                          foreground=styles.COLORS['text']).pack(anchor='w')
        else:
            ttk.Label(content, text="Начислений нет",
                      font=(styles.DEFAULT_FONT, 10),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text_secondary']).pack(anchor='w')

        # Итоги
        summary = ttk.Frame(content, style='White.TFrame')
        summary.pack(fill='x', pady=(16, 0))

        rows = [
            ("Сумма без скидки", item['full_price']),
            ("Скидка", -item['discount']),
            ("К оплате", item['total']),
            ("Расходники", -item['consumables']),
            ("Зарплата", -item['salary_total']),
            ("Осталось шиномонтажу", item['margin']),
        ]
        for index, (title, value) in enumerate(rows):
            bold = title in ('К оплате', 'Осталось шиномонтажу')
            row = ttk.Frame(summary, style='White.TFrame')
            row.pack(fill='x', pady=1)
            ttk.Label(row, text=title,
                      font=(styles.DEFAULT_FONT, 10, 'bold') if bold else (styles.DEFAULT_FONT, 10),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text']).pack(side='left')
            ttk.Label(row, text=f"{value:,.2f} ₽".replace(',', ' '),
                      font=(styles.DEFAULT_FONT, 10, 'bold') if bold else (styles.DEFAULT_FONT, 10),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['primary'] if bold else styles.COLORS['text']
                      ).pack(side='right')

        styles.create_button(content, "Закрыть", dialog.destroy,
                             'Secondary.TButton').pack(fill='x', pady=(16, 0))

    # ------------------------------------------------------------------
    # Выгрузка
    # ------------------------------------------------------------------

    def _build_export(self):
        """
        Собрать файл с текущим отчётом.

        Возвращает (путь, название отчёта). Используется и для сохранения,
        и для отправки — чтобы обе кнопки давали ровно одно и то же.
        """
        section = self.nav.current()
        start, end = self.period()
        period_title = (f"Период: {start.strftime('%d.%m.%Y')} — "
                        f"{end.strftime('%d.%m.%Y')}")

        if section == 0:
            headers = ['Услуга', 'Количество', 'Выручка', 'Расходники', 'Маржа']
            rows = [[s['name'], s['count'], s['revenue'], s['consumables'], s['margin']]
                    for s in self.summary_data['services']]
            rows.append([])
            rows.append(['ИТОГО', self.summary_data['total_services'],
                         self.summary_data['total_revenue'],
                         self.summary_data['total_consumables'],
                         self.summary_data['margin']])
            name, title = 'отчёт_по_услугам', 'Отчёт по услугам'

        elif section == 1:
            headers = ['Дата', 'Наряд', 'Автомобиль', 'Клиент', 'Телефон', 'Услуг',
                       'Сумма без скидки', 'Скидка', 'К оплате', 'Расходники',
                       'Зарплата', 'Маржа', 'Оплата']
            rows = [[o['paid_at'], o['id'], o['license_plate'], o['client_name'],
                     format_phone(o['client_phone']) if o['client_phone'] else '',
                     o['services_count'], o['full_price'], o['discount'], o['total'],
                     o['consumables'], o['salary_total'], o['margin'],
                     o['payment_method']]
                    for o in self.orders_data]
            name, title = 'отчёт_по_нарядам', 'Отчёт по нарядам'

        elif section == 2:
            headers = ['Мастер', 'Нарядов', 'Выручка по нарядам', 'Начислено']
            rows = [[f"№{m['employee_id']}", m['orders'], m['revenue'], m['salary']]
                    for m in self.masters_data]
            name, title = 'отчёт_по_мастерам', 'Отчёт по мастерам'

        else:
            headers = ['Услуга', 'Норматив, мин', 'Фактически, мин',
                       'Расхождение', 'Замеров']
            rows = [[n['service'], n['planned_minutes'], n['actual_minutes'],
                     n['difference'], n['measurements']]
                    for n in self.norms_data]
            name, title = 'нормативы_времени', 'Нормативы времени'

        path = export_rows(name, headers, rows, period_title, db=self.db)
        return path, f"{title}. {period_title}"

    def send_to_telegram(self):
        """Отправить текущий отчёт файлом в Telegram."""
        from services import TelegramService

        service = TelegramService(self.db)
        if not service.is_configured():
            messagebox.showinfo(
                "Telegram не настроен",
                "Укажите токен бота и номер чата:\n"
                "Прайс-лист → Настройки → Отправка отчётов в Telegram")
            return

        try:
            path, caption = self._build_export()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось собрать отчёт:\n{e}")
            return

        self.send_status.config(text="Отправляем…",
                                foreground=styles.COLORS['text_secondary'])

        def done(success, message):
            # Ответ приходит из другого потока — в интерфейс только через after
            self.frame.after(0, lambda: self.send_status.config(
                text=message,
                foreground=styles.COLORS['success'] if success else styles.COLORS['danger']))

        service.send_async(lambda: service.send_document(path, caption), on_done=done)

    def export_current(self):
        """Сохранить в файл тот отчёт, который сейчас открыт."""
        try:
            path, _ = self._build_export()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось выгрузить отчёт:\n{e}")
            return

        if messagebox.askyesno("Готово",
                               f"Отчёт сохранён:\n{path}\n\nОткрыть его сейчас?"):
            open_file(path)

    # Совместимость с прежним названием метода
    def load_statistics(self):
        self.reload()
