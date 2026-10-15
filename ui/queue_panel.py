"""
Онлайн-очередь глазами приёмщика.

Люди заняли место из дома и едут. Приёмщику важно одно: **кто уже
здесь**. Звать можно только их — машины у ворот нет, и пост простоит,
пока человек в дороге.

Поэтому приехавшие идут сверху и отмечены цветом, а те, кто в пути, —
ниже и бледнее. Список короткий: дальше часа место занять нельзя.

Брать отсюда машину можно на любой свободный пост, не только на
выделенный под очередь: держать человека при пустом боксе незачем.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from logger import log

# Как часто перечитывать. Очередь живёт быстрее ленты записи: человек
# отмечается «я приехал» со своего телефона, и приёмщик должен увидеть
# это, не нажимая ничего
REFRESH_SECONDS = 15


class QueuePanel:
    def __init__(self, parent, db, orders_tab=None):
        self.db = db
        self.orders_tab = orders_tab
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.rows = []

        self._build()
        self.load()
        self._schedule()

    # ------------------------------------------------------------------
    # Каркас
    # ------------------------------------------------------------------

    def _build(self):
        card = styles.create_card_frame(self.frame)
        card.pack(fill='both', expand=True, padx=15, pady=15)

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=16, pady=14)

        top = ttk.Frame(inner, style='White.TFrame')
        top.pack(fill='x')

        styles.create_label(top, "Онлайн-очередь",
                            'CardHeading.TLabel').pack(side='left')

        self.state_label = ttk.Label(
            top, text="", font=(styles.DEFAULT_FONT, 10),
            background=styles.COLORS['bg_card'],
            foreground=styles.COLORS['text_secondary'])
        self.state_label.pack(side='left', padx=(14, 0))

        styles.create_button(top, "Обновить", self.load,
                             'Secondary.TButton').pack(side='right')

        ttk.Label(inner,
                  text="Звать можно только тех, кто отметился «приехал» — "
                       "они сверху. Брать машину можно на любой свободный "
                       "пост, не только на выделенный под очередь.",
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary'],
                  wraplength=820, justify='left').pack(anchor='w',
                                                       pady=(6, 10))

        columns = ('Кто', 'Машина', 'Приехал', 'Время', 'Телефон')
        self.tree = ttk.Treeview(inner, columns=columns, show='headings',
                                 height=12)
        for column, title, width in (('Кто', 'Клиент', 190),
                                     ('Машина', 'Машина', 130),
                                     ('Приехал', 'На месте', 110),
                                     ('Время', 'Подъехать к', 120),
                                     ('Телефон', 'Телефон', 150)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor='w')

        # Приехавших выделяем: именно их приёмщик ищет глазами
        self.tree.tag_configure('here', background='#dcfce7')
        self.tree.tag_configure('away', foreground=styles.COLORS['text_secondary'])

        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.take())

        buttons = ttk.Frame(inner, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))

        styles.create_button(buttons, "Взять на пост", self.take,
                             'Primary.TButton').pack(side='left',
                                                     padx=(0, 8))
        styles.create_button(buttons, "Отметить приезд", self.mark_arrived,
                             'Secondary.TButton').pack(side='left',
                                                       padx=(0, 8))
        styles.create_button(buttons, "Не приехал", self.move_back,
                             'Secondary.TButton').pack(side='left',
                                                       padx=(0, 8))
        styles.create_button(buttons, "Убрать", self.drop,
                             'Secondary.TButton').pack(side='left')

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------

    def _sync(self):
        from services.sync_service import SyncService

        return SyncService(self.db)

    def load(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        sync = self._sync()
        if not sync.is_enabled():
            self.state_label.config(
                text="Обмен с сервером не настроен — очереди нет")
            self.rows = []
            return

        try:
            answer = sync.queue_line()
        except Exception as e:
            self.state_label.config(text=f"Не удалось получить: {e}")
            self.rows = []
            return

        self.rows = answer.get('people', [])

        for row in self.rows:
            here = row.get('here')
            self.tree.insert('', 'end', values=(
                row.get('name') or '—',
                row.get('license_plate') or '—',
                'да' if here else 'в пути',
                (row.get('come_at') or '')[11:16],
                row.get('phone') or '',
            ), tags=('here' if here else 'away',))

        waiting = len(self.rows)
        here = sum(1 for row in self.rows if row.get('here'))

        if not waiting:
            self.state_label.config(text="Сейчас никого")
        else:
            self.state_label.config(
                text=f"в очереди {waiting}, из них на месте {here}")

    def _selected(self):
        chosen = self.tree.selection()
        if not chosen:
            messagebox.showinfo("Очередь", "Выберите машину в списке",
                                parent=self.frame)
            return None

        index = self.tree.index(chosen[0])
        if index >= len(self.rows):
            return None
        return self.rows[index]

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def take(self):
        """
        Взять машину на пост: позвать и завести наряд.

        Того, кого нет на месте, звать нельзя — пост простоит, пока он
        едет. Говорим об этом прямо, а не отказываем молча.
        """
        row = self._selected()
        if row is None:
            return

        if not row.get('here'):
            # Без рода: в списке и Пётр, и Ольга, а «ещё не отметился»
            # про Ольгу читается как опечатка
            messagebox.showinfo(
                "Ещё в пути",
                f"От клиента ещё нет отметки о приезде — "
                f"{row.get('name') or 'машина'} в пути.\n\n"
                f"Если машина уже здесь, нажмите «Отметить приезд».",
                parent=self.frame)
            return

        try:
            self._sync().queue_call(row['id'])
        except Exception as e:
            messagebox.showerror("Очередь", f"Не вышло: {e}",
                                 parent=self.frame)
            return

        plate = row.get('license_plate')
        self.load()

        # Дальше приёмщику нужен наряд, а не список очереди
        if self.orders_tab and plate:
            if messagebox.askyesno("Наряд",
                                   f"Создать наряд на {plate}?",
                                   parent=self.frame):
                try:
                    self.orders_tab.license_entry.delete(0, tk.END)
                    self.orders_tab.license_entry.insert(0, plate)
                    self.orders_tab.prefilled_data = None
                    self.orders_tab.create_new_order()
                    self._sync().queue_served(row['id'])
                except Exception as e:
                    messagebox.showerror("Наряд",
                                         f"Не удалось открыть наряд: {e}",
                                         parent=self.frame)

    def mark_arrived(self):
        """Человек подошёл и сказал, что он здесь, — отмечаем за него."""
        row = self._selected()
        if row is None:
            return

        try:
            self._sync().queue_arrived(row['id'])
        except Exception as e:
            messagebox.showerror("Очередь", f"Не вышло: {e}",
                                 parent=self.frame)
            return

        self.load()

    def move_back(self):
        """
        Не приехал — в конец очереди. Один раз.

        Второй перенос закрывает место: ходить по кругу до вечера
        нельзя, его держат те, кто стоит рядом.
        """
        row = self._selected()
        if row is None:
            return

        again = " Это второй перенос — место закроется." if row.get('moved') \
            else ""

        if not messagebox.askyesno(
                "Не приехал",
                f"Перенести {row.get('name') or 'клиента'} в конец "
                f"очереди?{again}\n\nЧужое время при этом не изменится.",
                parent=self.frame):
            return

        try:
            self._sync().queue_missed(row['id'])
        except Exception as e:
            messagebox.showerror("Очередь", f"Не вышло: {e}",
                                 parent=self.frame)
            return

        self.load()

    def drop(self):
        row = self._selected()
        if row is None:
            return

        if not messagebox.askyesno(
                "Убрать из очереди",
                f"Убрать {row.get('name') or 'клиента'} из очереди?",
                parent=self.frame):
            return

        try:
            self._sync().queue_drop(row['id'])
        except Exception as e:
            messagebox.showerror("Очередь", f"Не вышло: {e}",
                                 parent=self.frame)
            return

        self.load()

    # ------------------------------------------------------------------
    # Самообновление
    # ------------------------------------------------------------------

    def _schedule(self):
        try:
            self.frame.after(REFRESH_SECONDS * 1000, self._tick)
        except Exception:
            pass        # окно закрыли

    def _tick(self):
        try:
            # Только когда на вкладку смотрят и поверх неё нет окна:
            # перерисовывать из-под рук нельзя
            if (self.frame.winfo_ismapped()
                    and not self.frame.winfo_toplevel().grab_current()):
                self.load()
        except Exception as e:
            log.warning(f"Не удалось обновить очередь: {e}")

        self._schedule()
