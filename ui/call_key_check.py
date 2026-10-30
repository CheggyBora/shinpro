"""
Окно «Проверить ключ flashcall.ru»: пробный звонок со своего телефона.

Ключ берётся из поля как есть, даже несохранённый: проверить хотят то,
что только что вставили. Сеть — в отдельном потоке, окно не замирает.
"""
import threading
import time
import tkinter as tk
from tkinter import ttk

import styles
from services import flashcall

POLL_MS = 2000


class CallKeyCheck:
    def __init__(self, parent, token, phone=''):
        self.token = token
        self.check_id = None
        self.until = 0
        self.closed = False

        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Проверка ключа flashcall.ru')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        self.dialog.protocol('WM_DELETE_WINDOW', self.close)
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=20, pady=16)

        styles.create_label(body, 'Пробный звонок', 'CardHeading.TLabel').pack(anchor='w')
        ttk.Label(body, text='Программа попросит у flashcall.ru номер, вы позвоните на него '
                             'со своего телефона. Отвечать не надо — вызов сбросится сам. '
                             'Звонок стоит 0,20 ₽, если не позвоните — бесплатно.',
                  wraplength=440, justify='left', font=styles.FONTS['small'],
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w', pady=(4, 12))

        row = ttk.Frame(body, style='White.TFrame')
        row.pack(fill='x')
        styles.create_label(row, 'С какого номера позвоните:', 'Card.TLabel').pack(side='left')
        self.phone = styles.create_entry(row, width=18)
        self.phone.insert(0, phone or '')
        self.phone.pack(side='left', padx=(8, 0))

        self.start_button = styles.create_button(body, 'Получить номер для звонка', self.start,
                                                 'Primary.TButton')
        self.start_button.pack(fill='x', pady=(12, 8))

        self.dial = tk.Label(body, text='', bg=styles.COLORS['bg_card'], fg=styles.COLORS['primary'],
                             font=(styles.DEFAULT_FONT, 18, 'bold'))
        self.dial.pack(anchor='w')
        self.state = ttk.Label(body, text='', wraplength=440, justify='left',
                               background=styles.COLORS['bg_card'])
        self.state.pack(anchor='w', pady=(4, 0))

        styles.create_button(body, 'Закрыть', self.close, 'Secondary.TButton').pack(
            fill='x', pady=(14, 0))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    # ------------------------------------------------------------------

    def _say(self, text, tone='normal'):
        colors = {'ok': styles.COLORS['success'], 'bad': '#b91c1c',
                  'normal': styles.COLORS['text']}
        self.state.configure(text=text, foreground=colors[tone])

    def _in_background(self, work, done):
        """Сеть — в потоке; ответ забираем в окне по таймеру."""
        box = {}

        def run():
            try:
                box['value'] = work()
            except flashcall.FlashcallError as e:
                box['error'] = str(e)
            except Exception as e:
                box['error'] = f'Не получилось: {e}'

        threading.Thread(target=run, daemon=True).start()

        def wait():
            if self.closed:
                return
            if 'value' not in box and 'error' not in box:
                self.dialog.after(100, wait)
                return
            done(box.get('value'), box.get('error'))

        self.dialog.after(100, wait)

    def start(self):
        phone = self.phone.get()
        self.start_button.configure(state='disabled')
        self.dial.configure(text='')
        self._say('Спрашиваем flashcall.ru…')

        def done(value, error):
            if error:
                self.start_button.configure(state='normal')
                self._say('✗ ' + error, 'bad')
                return
            self.check_id, dial, seconds = value
            self.until = time.time() + seconds
            self.dial.configure(text=dial)
            self._say(f'Ключ принят. Позвоните на этот номер с {phone} — '
                      f'на это {seconds} сек.')
            self.dialog.after(POLL_MS, self.poll)

        self._in_background(lambda: flashcall.get_phone(self.token, phone), done)

    def poll(self):
        if self.closed or self.check_id is None:
            return

        def done(value, error):
            if self.closed:
                return
            if error:
                # Связь моргнула — пробуем ещё, пока не вышло время
                if time.time() < self.until:
                    self.dialog.after(POLL_MS, self.poll)
                else:
                    self._finish('✗ ' + error, 'bad')
                return
            state, caller = value
            if state == flashcall.CONFIRMED:
                self._finish('✓ Всё работает: звонок' + (f' с {caller}' if caller else '')
                             + ' подтверждён. Сохраните настройки — ключ уедет на сервер.', 'ok')
            elif state == flashcall.EXPIRED or time.time() >= self.until:
                self._finish('Звонка не было. Ключ рабочий — номер выдан, но звонок не дошёл: '
                             'звоните именно с указанного номера, не со скрытого. '
                             'Можно попробовать ещё раз.', 'bad')
            else:
                left = max(0, int(self.until - time.time()))
                self._say(f'Ждём звонка… осталось {left} сек.')
                self.dialog.after(POLL_MS, self.poll)

        self._in_background(lambda: flashcall.status(self.token, self.check_id), done)

    def _finish(self, text, tone):
        self.check_id = None
        self.start_button.configure(state='normal', text='Проверить ещё раз')
        self._say(text, tone)

    def close(self):
        self.closed = True
        self.dialog.destroy()
