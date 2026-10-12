"""
Фото по наряду: QR для телефона мастера и то, что он уже прислал.

Компьютера в пути фотографии нет. Мастер снимает на телефон и
отправляет прямо клиенту; здесь приёмщик только видит, что ушло, и
показывает QR тому, чей телефон ещё не подключён.

QR рисуем сами на холсте, из матрицы. Картинку для этого заводить не
надо: чёрные квадратики на белом — это ровно то, что читает камера.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from logger import log

# Сторона квадратика в пикселях. Семь — код читается с полуметра даже
# с заляпанного экрана, и целиком помещается в окно
MODULE = 7


def open_photos(parent, db, order):
    """Открыть окно фотографий наряда."""
    return PhotoDialog(parent, db, order).dialog


class PhotoDialog:
    def __init__(self, parent, db, order):
        self.db = db
        self.order = order

        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f"Фото по наряду №{order.id}")
        self.dialog.geometry("640x680")
        self.dialog.configure(bg=styles.COLORS['bg'])
        self.dialog.transient(parent.winfo_toplevel())
        styles.center_window(self.dialog, parent.winfo_toplevel())

        content = ttk.Frame(self.dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        plate = getattr(order.car, 'license_plate', '') if order.car else ''
        styles.create_label(content, f"Фото по машине {plate}",
                            'CardHeading.TLabel').pack(anchor='w')

        ttk.Label(content,
                  text="Мастер снимает на свой телефон и отправляет клиенту "
                       "сам — компьютер в этом не участвует.\n"
                       "Телефон подключается один раз: наведите камеру на "
                       "код ниже.",
                  font=(styles.DEFAULT_FONT, 9),
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card'],
                  wraplength=580, justify='left').pack(anchor='w', pady=(4, 12))

        # --- Код ------------------------------------------------------
        self.code_box = ttk.Frame(content, style='White.TFrame')
        self.code_box.pack(fill='x')

        self.canvas = tk.Canvas(self.code_box, width=260, height=260,
                                bg='white', highlightthickness=1,
                                highlightbackground=styles.COLORS['border'])
        self.canvas.pack(side='left')

        side = ttk.Frame(self.code_box, style='White.TFrame')
        side.pack(side='left', fill='both', expand=True, padx=(16, 0))

        self.code_hint = ttk.Label(
            side, text="", font=(styles.DEFAULT_FONT, 9),
            foreground=styles.COLORS['text_secondary'],
            background=styles.COLORS['bg_card'],
            wraplength=300, justify='left')
        self.code_hint.pack(anchor='w')

        styles.create_button(side, "Показать код", self.show_code,
                             'Primary.TButton').pack(fill='x', pady=(10, 0))

        # --- Что прислали ---------------------------------------------
        styles.create_label(content, "Что прислали",
                            'CardHeading.TLabel').pack(anchor='w', pady=(18, 6))

        tree_frame = ttk.Frame(content, style='White.TFrame')
        tree_frame.pack(fill='both', expand=True)

        self.tree = ttk.Treeview(
            tree_frame, columns=('Когда', 'Кто', 'Комментарий', 'Клиенту'),
            show='headings', height=8)
        for column, title, width in (('Когда', 'Когда', 110),
                                     ('Кто', 'Кто снял', 110),
                                     ('Комментарий', 'Комментарий', 230),
                                     ('Клиенту', 'Клиенту', 140)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor='w')
        self.tree.pack(side='left', fill='both', expand=True)

        scroll = ttk.Scrollbar(tree_frame, orient='vertical',
                               command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=scroll.set)

        self.state = ttk.Label(content, text="",
                               font=(styles.DEFAULT_FONT, 9),
                               foreground=styles.COLORS['text_secondary'],
                               background=styles.COLORS['bg_card'])
        self.state.pack(anchor='w', pady=(8, 0))

        buttons = ttk.Frame(content, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, "Обновить", self.load,
                             'Secondary.TButton').pack(
            side='left', fill='x', expand=True, padx=(0, 6))
        styles.create_button(buttons, "Закрыть", self.dialog.destroy,
                             'Secondary.TButton').pack(
            side='left', fill='x', expand=True, padx=(6, 0))

        self.load()

    # ------------------------------------------------------------------
    # Код для телефона
    # ------------------------------------------------------------------

    def show_code(self):
        """
        Спросить у сервера одноразовый ключ и нарисовать его кодом.

        Ключ живёт минуты: он показан на экране в цеху, и пропуск в
        чужой цех на сутки — не то, что стоит оставлять на виду.
        """
        from services.sync_service import SyncService

        sync = SyncService(self.db)
        if not sync.is_enabled():
            messagebox.showinfo(
                "Обмен не настроен",
                "Фото с телефонов работают через сервер приложения.\n"
                "Настройте обмен: Настройки → Связь с приложением.",
                parent=self.dialog)
            return

        try:
            answer = sync.master_link()
        except Exception as e:
            messagebox.showerror("Не вышло",
                                 f"Не удалось получить код:\n{e}",
                                 parent=self.dialog)
            return

        self.draw_code(answer['url'])
        self.code_hint.config(
            text=f"Наведите камеру телефона на код.\n\n"
                 f"Код действует {answer['minutes']} мин. "
                 f"Подключать телефон нужно один раз — дальше мастер "
                 f"открывает страницу с экрана.")

    def draw_code(self, url):
        """Нарисовать QR квадратиками. Картинка для этого не нужна."""
        self.canvas.delete('all')

        try:
            import qrcode
        except ImportError:
            self.canvas.create_text(
                130, 130, width=230, justify='center',
                text="Не хватает библиотеки qrcode.\n"
                     "Переустановите программу.")
            log.error("qrcode не установлен — QR для мастеров не нарисовать")
            return

        code = qrcode.QRCode(box_size=1, border=2)
        code.add_data(url)
        code.make(fit=True)
        matrix = code.get_matrix()

        side = len(matrix) * MODULE
        self.canvas.config(width=side, height=side)

        for y, row in enumerate(matrix):
            for x, dark in enumerate(row):
                if dark:
                    self.canvas.create_rectangle(
                        x * MODULE, y * MODULE,
                        (x + 1) * MODULE, (y + 1) * MODULE,
                        fill='black', outline='')

    # ------------------------------------------------------------------
    # Что прислали
    # ------------------------------------------------------------------

    def load(self):
        from services.sync_service import SyncService

        for row in self.tree.get_children():
            self.tree.delete(row)

        sync = SyncService(self.db)
        if not sync.is_enabled():
            self.state.config(text="Обмен с сервером не настроен")
            return

        try:
            rows = sync.order_photos(self.order.id)
        except Exception as e:
            self.state.config(text=f"Не удалось получить список: {e}")
            return

        for item in rows:
            when = (item.get('created_at') or '')[11:16]
            if item.get('sent_at'):
                where = {'telegram': 'в Телеграм',
                         'webpush': 'в браузер'}.get(item.get('channel'), 'да')
            else:
                where = item.get('error') or 'не отправлено'

            self.tree.insert('', 'end', values=(
                when, item.get('author') or '—',
                item.get('comment') or '', where))

        self.state.config(
            text=(f"Снимков: {len(rows)}" if rows
                  else "По этому наряду фотографий пока нет"))
