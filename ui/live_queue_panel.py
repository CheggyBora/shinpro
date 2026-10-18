"""
Живая очередь глазами цеха.

Сверху — посты: кто стоит и до скольки, кого позвали, какой свободен и
что с ним делать — позвать следующего или держать под запись. Ниже —
сама очередь. Встать в неё можно только на месте: по QR у въезда или
через приёмщика — кнопкой «Добавить».

Следить за постами физически некому, поэтому подсказку считает
программа: она знает, когда освободится каждый пост, и не предлагает
звать из очереди на пост, который понадобится записи.
Всё работает без интернета (docs/live_queue.md).
"""
import tkinter as tk
from tkinter import ttk, messagebox

from logger import log
from models.live_queue import CALLED
from services.live_queue_service import LiveQueueService, QueueError, DIAMETERS
from utils import as_naive, get_moscow_time, format_phone
import styles

REFRESH_SECONDS = 15

WHEELS_TITLES = {True: 'в сборе', False: 'только шины', None: '—'}


class LiveQueuePanel:
    def __init__(self, parent, db, orders_tab=None):
        self.db = db
        self.orders_tab = orders_tab
        self.service = LiveQueueService(db)
        self.frame = ttk.Frame(parent, style='BG.TFrame')
        self.entries = []
        self.plan = []
        # Вызывается после открытия наряда — главное окно переключает
        # на «Наряды»
        self.on_order_opened = None
        # Вызывается после любого изменения очереди — главное окно
        # отдаёт его серверу, чтобы человек у въезда увидел сразу
        self.on_changed = None

        self._build()
        self.load()
        self._schedule()

    # ------------------------------------------------------------------
    # Каркас
    # ------------------------------------------------------------------

    def _build(self):
        card = styles.create_card_frame(self.frame)
        card.pack(fill='both', expand=True, padx=15, pady=15)

        # Не сезон: очередь выключена, наряды открываются как обычно
        self.off = ttk.Frame(card, style='White.TFrame')
        styles.create_label(self.off, "Живая очередь выключена",
                            'CardHeading.TLabel').pack(anchor='w')
        styles.create_label(
            self.off,
            "Сейчас не сезон: наряды открываются как обычно, без постов, "
            "встать в очередь по QR нельзя.\n"
            "Включается в «Настройки» → «Живая очередь».",
            'Card.TLabel').pack(anchor='w', pady=(8, 0))

        inner = ttk.Frame(card, style='White.TFrame')
        inner.pack(fill='both', expand=True, padx=16, pady=14)
        self.inner = inner

        top = ttk.Frame(inner, style='White.TFrame')
        top.pack(fill='x')
        styles.create_label(top, "Живая очередь", 'CardHeading.TLabel').pack(side='left')
        self.state_label = ttk.Label(top, text="", font=(styles.DEFAULT_FONT, 10),
                                     background=styles.COLORS['bg_card'],
                                     foreground=styles.COLORS['text_secondary'])
        self.state_label.pack(side='left', padx=(14, 0))
        styles.create_button(top, "Обновить", self.load,
                             'Secondary.TButton').pack(side='right')
        styles.create_button(top, "Перевыпустить QR", self.reissue_qr,
                             'Secondary.TButton').pack(side='right', padx=(0, 8))
        styles.create_button(top, "Печать QR", self.print_qr,
                             'Secondary.TButton').pack(side='right', padx=(0, 8))

        # Посты
        self.posts_frame = ttk.Frame(inner, style='White.TFrame')
        self.posts_frame.pack(fill='x', pady=(12, 12))

        # Очередь
        columns = ('n', 'plate', 'phone', 'r', 'wheels', 'wait', 'eta', 'src', 'state')
        self.tree = ttk.Treeview(inner, columns=columns, show='headings', height=10)
        for column, title, width in (('n', '№', 40), ('plate', 'Машина', 120),
                                     ('phone', 'Телефон', 150), ('r', 'R', 50),
                                     ('wheels', 'Колёса', 100), ('wait', 'Ждёт', 70),
                                     ('eta', '≈ Подойдёт', 90), ('src', 'Встал', 90),
                                     ('state', 'Сейчас', 150)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor='w')
        self.tree.tag_configure('called', background='#fde2e2')
        self.tree.tag_configure('booking', background='#e0ecff')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.open_order())

        buttons = ttk.Frame(inner, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, "Добавить в очередь", self.add,
                             'Success.TButton').pack(side='left', padx=(0, 8))
        styles.create_button(buttons, "Позвать на пост…", self.call,
                             'Primary.TButton').pack(side='left', padx=(0, 8))
        styles.create_button(buttons, "Подъехал — открыть наряд", self.open_order,
                             'Primary.TButton').pack(side='left', padx=(0, 8))
        styles.create_button(buttons, "Не подъехал", self.missed,
                             'Secondary.TButton').pack(side='left', padx=(0, 8))
        styles.create_button(buttons, "Ушёл", self.leave,
                             'Secondary.TButton').pack(side='left')

    # ------------------------------------------------------------------
    # Данные
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Табличка с QR у въезда
    # ------------------------------------------------------------------

    def print_qr(self, reissue=False):
        from services.queue_poster_service import QueuePosterService, PosterError
        poster = QueuePosterService(self.db)
        try:
            url = poster.url(reissue=reissue)
            path = poster.make(url)
        except PosterError as e:
            messagebox.showerror("QR", str(e), parent=self.frame)
            return None
        except Exception as e:
            log.error(f"Табличка с QR не сделана: {e}")
            messagebox.showerror("QR", f"Не удалось сделать табличку: {e}", parent=self.frame)
            return None
        self._send_to_printer(path)
        return path

    def _send_to_printer(self, path):
        import os
        try:
            os.startfile(path, "print")
        except Exception:
            # Принтер не настроен — откроем, распечатают из просмотрщика
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showinfo("QR", f"Табличка сохранена: {path}\n({e})",
                                    parent=self.frame)

    def reissue_qr(self):
        if not messagebox.askyesno(
                "Перевыпустить QR",
                "Старая табличка перестанет ставить в очередь — "
                "её нужно будет заменить новой.\n"
                "Те, кто уже стоит, останутся на своих местах.\n\n"
                "Перевыпустить и напечатать?", parent=self.frame):
            return None
        return self.print_qr(reissue=True)

    def load(self):
        if not self.service.enabled():
            self.inner.pack_forget()
            self.off.pack(fill='both', expand=True, padx=16, pady=14)
            return
        if not self.inner.winfo_manager():
            self.off.pack_forget()
            self.inner.pack(fill='both', expand=True, padx=16, pady=14)
        try:
            self.service.expire_calls()
            posts = self.service.posts()
            self.plan = self.service.suggestion()
            self.entries = self.service.line()
            self.bookings = [a for a in self.service._today_bookings()
                             if a.status == 'scheduled' and (a.on_site or a.called_post)]
            self.bookings.sort(key=lambda a: (not a.called_post, as_naive(a.scheduled_at)))
            etas = self.service.estimates()
        except Exception as e:
            self.db.rollback()
            log.error(f"Очередь не прочиталась: {e}")
            self.state_label.config(text=f"Не удалось прочитать: {e}")
            return

        self._draw_posts(posts)

        for row in self.tree.get_children():
            self.tree.delete(row)
        now = as_naive(get_moscow_time())
        # Записанные на месте идут первыми — показываем их сверху
        for booking in self.bookings:
            state = (f"позван на пост {booking.called_post}" if booking.called_post
                     else 'на месте, ждёт пост')
            self.tree.insert('', 'end', iid=f"b{booking.id}", values=(
                'З', booking.license_plate or '—',
                format_phone(booking.client_phone) if booking.client_phone else '—',
                booking.wheel_diameter or '—',
                WHEELS_TITLES.get(booking.wheels_assembled, '—'),
                '', '', f"запись {as_naive(booking.scheduled_at).strftime('%H:%M')}",
                state), tags=('booking',))
        place = 0
        for entry in self.entries:
            waited = int((now - as_naive(entry.joined_at)).total_seconds() // 60)
            if entry.status == CALLED:
                state = f"позван на пост {entry.post_number}"
                number = '→'
            else:
                place += 1
                number = str(place)
                state = 'ждёт' if not entry.misses else 'ждёт (пропустил вызов)'
            eta = etas.get(entry.id)
            self.tree.insert('', 'end', iid=str(entry.id), values=(
                number, entry.license_plate,
                format_phone(entry.phone) if entry.phone else '—',
                entry.wheel_diameter or '—',
                WHEELS_TITLES.get(entry.wheels_assembled, '—'),
                f"{waited} мин",
                eta.strftime('%H:%M') if eta and entry.status != CALLED else '',
                'по QR' if entry.source == 'qr' else 'в цеху',
                state), tags=('called',) if entry.status == CALLED else ())

        waiting = sum(1 for e in self.entries if e.status != CALLED)
        self.state_label.config(text=f"ждут {waiting}" if waiting else "очереди нет")

    def _draw_posts(self, posts):
        for child in self.posts_frame.winfo_children():
            child.destroy()
        plan = {p['post']: p for p in self.plan}
        for state in posts:
            box = tk.Frame(self.posts_frame, bg=styles.COLORS['bg_subtle'],
                           highlightthickness=1,
                           highlightbackground=styles.COLORS['border'])
            box.pack(side='left', fill='both', expand=True, padx=(0, 8))
            tk.Label(box, text=f"Пост {state['post']}", bg=styles.COLORS['bg_subtle'],
                     fg=styles.COLORS['text'],
                     font=(styles.DEFAULT_FONT, 12, 'bold')).pack(anchor='w', padx=10, pady=(8, 2))

            line, colour, action = '', styles.COLORS['text_secondary'], None
            if state['state'] == 'busy':
                order = state['order']
                plate = order.car.license_plate if order.car else '—'
                line = f"{plate} · до ≈ {state['free_at'].strftime('%H:%M')}"
                colour = styles.COLORS['text']
            elif state['state'] == 'called':
                who = state['entry'] or state.get('booking')
                prefix = 'едет (запись) ' if state.get('booking') else 'едет '
                line = prefix + (who.license_plate or '—')
                colour = styles.COLORS['danger']
            else:
                suggestion = plan.get(state['post'])
                if suggestion and suggestion.get('booking') is not None:
                    booking = suggestion['booking']
                    line = f"свободен → запись {booking.license_plate}"
                    colour = styles.COLORS['success']
                    action = ('b', booking.id, state['post'])
                elif suggestion and suggestion['entry'] is not None:
                    entry = suggestion['entry']
                    line = f"свободен → {entry.license_plate}"
                    colour = styles.COLORS['success']
                    action = (entry.id, state['post'])
                elif suggestion and suggestion['hold_for'] is not None:
                    line = f"держим под запись {suggestion['hold_for'].strftime('%H:%M')}"
                    colour = styles.COLORS['warning']
                else:
                    line = "свободен"
                    colour = styles.COLORS['success']
            tk.Label(box, text=line, bg=styles.COLORS['bg_subtle'], fg=colour,
                     font=(styles.DEFAULT_FONT, 10)).pack(anchor='w', padx=10, pady=(0, 6))
            if action:
                styles.create_button(box, "Позвать",
                                     lambda a=action: self._call_any(a),
                                     'Compact.Primary.TButton').pack(anchor='w', padx=10, pady=(0, 8))

    def _selected(self):
        """Номер места в очереди или ('b', номер записи)."""
        chosen = self.tree.selection()
        if not chosen:
            messagebox.showinfo("Очередь", "Выберите машину в списке", parent=self.frame)
            return None
        key = chosen[0]
        if key.startswith('b'):
            return ('b', int(key[1:]))
        return int(key)

    def _booking(self, booking_id):
        from models import Appointment
        return self.db.query(Appointment).filter(Appointment.id == booking_id).first()

    def _call_any(self, action):
        if action[0] == 'b':
            return self._call_booking(action[1], action[2])
        return self._call(*action)

    def _call_booking(self, booking_id, post):
        booking = self._booking(booking_id)
        if booking is None:
            return None
        problem = self._run(lambda: self.service.call_booking(booking, post))
        if problem:
            messagebox.showwarning(
                "Нет связи",
                f"Записанного позвали на пост {post}, но сообщение ему не ушло: "
                f"{problem}\n\nСкажите ему голосом.", parent=self.frame)
        return problem

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------

    def _run(self, action):
        try:
            result = action()
        except QueueError as e:
            messagebox.showwarning("Очередь", str(e), parent=self.frame)
            return None
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Очередь", f"Не вышло: {e}", parent=self.frame)
            return None
        self.load()
        if self.on_changed:
            self.on_changed()
        return result

    def _call(self, entry_id, post):
        return self._run(lambda: self.service.call(entry_id, post))

    def call(self):
        entry_id = self._selected()
        if entry_id is None:
            return
        free = [s['post'] for s in self.service.posts() if s['state'] == 'free']
        if not free:
            messagebox.showinfo("Очередь", "Свободных постов нет", parent=self.frame)
            return
        post = ask_post(self.frame, free)
        if not post:
            return
        if isinstance(entry_id, tuple):
            self._call_booking(entry_id[1], post)
        else:
            self._call(entry_id, post)

    def open_order(self):
        entry_id = self._selected()
        if entry_id is None:
            return
        if isinstance(entry_id, tuple):
            order = self._open_booking(entry_id[1])
        else:
            order = self._run(lambda: self.service.open_order(entry_id))
        if order is None:
            return
        if self.orders_tab is not None:
            try:
                self.orders_tab.open_order_tab(order)
                if hasattr(self.orders_tab, 'refresh_active_orders'):
                    self.orders_tab.refresh_active_orders()
            except Exception as e:
                log.error(f"Наряд из очереди не открылся во вкладке: {e}")
        if self.on_order_opened:
            self.on_order_opened()

    def _open_booking(self, booking_id):
        """Записанный подъехал: наряд по пакету, запись — «приехал»."""
        from services.booking_gateway import get_booking

        booking = self._booking(booking_id)
        if booking is None:
            return None
        order = self._run(lambda: self.service.open_booking_order(booking))
        if order is None:
            return None
        try:
            gateway = get_booking(self.db)
            gateway.mark_arrived(gateway.key_of(booking))
        except Exception as e:
            log.warning(f"Запись не отмечена приехавшей: {e}")
        return order

    def missed(self):
        entry_id = self._selected()
        if entry_id is None or isinstance(entry_id, tuple):
            return
        if messagebox.askyesno("Не подъехал",
                               "Отправить в конец очереди? Второй пропуск — "
                               "место закроется.", parent=self.frame):
            self._run(lambda: self.service.missed(entry_id))

    def leave(self):
        entry_id = self._selected()
        if entry_id is None or isinstance(entry_id, tuple):
            return
        if messagebox.askyesno("Ушёл", "Убрать машину из очереди?", parent=self.frame):
            self._run(lambda: self.service.leave(entry_id))

    def add(self):
        def added():
            self.load()
            if self.on_changed:
                self.on_changed()
        dialog = AddDialog(self.frame, self.service, on_added=added)
        return dialog.window

    # ------------------------------------------------------------------
    # Самообновление
    # ------------------------------------------------------------------

    def _schedule(self):
        try:
            self.frame.after(REFRESH_SECONDS * 1000, self._tick)
        except Exception:
            pass

    def _tick(self):
        try:
            if (self.frame.winfo_ismapped()
                    and not self.frame.winfo_toplevel().grab_current()):
                self.load()
        except Exception as e:
            log.warning(f"Не удалось обновить очередь: {e}")
        self._schedule()


def ask_post(parent, free):
    """Выбор поста из свободных. Возвращает номер или None."""
    window = tk.Toplevel(parent)
    window.title("На какой пост")
    window.configure(bg=styles.COLORS['bg_card'])
    window.transient(parent.winfo_toplevel())
    chosen = {'post': None}
    body = ttk.Frame(window, style='White.TFrame')
    body.pack(fill='both', expand=True, padx=18, pady=14)
    styles.create_label(body, "Свободные посты:", 'Card.TLabel').pack(anchor='w', pady=(0, 8))
    row = ttk.Frame(body, style='White.TFrame')
    row.pack(fill='x')

    def pick(post):
        chosen['post'] = post
        window.destroy()

    for post in free:
        styles.create_button(row, f"Пост {post}", lambda p=post: pick(p),
                             'Primary.TButton').pack(side='left', padx=(0, 6))
    styles.create_button(body, "Отмена", window.destroy,
                         'Secondary.TButton').pack(anchor='w', pady=(12, 0))
    window.bind('<Escape>', lambda e: window.destroy())
    styles.center_window(window, parent.winfo_toplevel())
    window.grab_set()
    window.wait_window()
    return chosen['post']


class AddDialog:
    """Добавить в очередь из цеха: номер, телефон, диаметр, колёса."""

    def __init__(self, parent, service, on_added=None):
        self.service = service
        self.on_added = on_added
        self.window = tk.Toplevel(parent)
        self.window.title("Добавить в очередь")
        self.window.configure(bg=styles.COLORS['bg_card'])
        self.window.resizable(False, False)
        self.window.transient(parent.winfo_toplevel())

        body = ttk.Frame(self.window, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=16)

        styles.create_label(body, "Номер машины:", 'Card.TLabel').grid(row=0, column=0, sticky='w', pady=4)
        self.plate = styles.create_entry(body, width=16)
        self.plate.grid(row=0, column=1, sticky='w', padx=(10, 0), pady=4)

        styles.create_label(body, "Телефон:", 'Card.TLabel').grid(row=1, column=0, sticky='w', pady=4)
        self.phone = styles.create_entry(body, width=20)
        self.phone.grid(row=1, column=1, sticky='w', padx=(10, 0), pady=4)

        styles.create_label(body, "Диаметр:", 'Card.TLabel').grid(row=2, column=0, sticky='w', pady=4)
        self.diameter = ttk.Combobox(body, values=DIAMETERS, state='readonly', width=8)
        self.diameter.grid(row=2, column=1, sticky='w', padx=(10, 0), pady=4)

        styles.create_label(body, "Колёса:", 'Card.TLabel').grid(row=3, column=0, sticky='w', pady=4)
        self.wheels = tk.StringVar(value='')
        wheels_row = ttk.Frame(body, style='White.TFrame')
        wheels_row.grid(row=3, column=1, sticky='w', padx=(10, 0), pady=4)
        ttk.Radiobutton(wheels_row, text="В сборе", value='1', variable=self.wheels).pack(side='left')
        ttk.Radiobutton(wheels_row, text="Только шины", value='0',
                        variable=self.wheels).pack(side='left', padx=(10, 0))

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(14, 0))
        styles.create_button(buttons, "В очередь", self.save, 'Primary.TButton').pack(side='left')
        styles.create_button(buttons, "Отмена", self.window.destroy,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))

        self.window.bind('<Return>', lambda e: self.save())
        self.window.bind('<Escape>', lambda e: self.window.destroy())
        styles.center_window(self.window, parent.winfo_toplevel())
        self.window.grab_set()
        self.plate.focus_set()

    def save(self):
        wheels = {'1': True, '0': False}.get(self.wheels.get())
        try:
            self.service.add(self.plate.get(), self.phone.get() or None,
                             self.diameter.get() or None, wheels, source='shop')
        except QueueError as e:
            messagebox.showwarning("Очередь", str(e), parent=self.window)
            return
        except Exception as e:
            self.service.db.rollback()
            messagebox.showerror("Очередь", f"Не вышло: {e}", parent=self.window)
            return
        self.window.destroy()
        if self.on_added:
            self.on_added()
