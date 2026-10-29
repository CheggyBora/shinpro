"""
Настройки программы — отдельный раздел.

Раньше они жили кнопкой внутри прайс-листа, и найти их было негде:
человек искал, где поменять часы записи, и не догадывался лезть в
цены. Разделов в настройках десять, и прятать их за ценами на
балансировку неправильно.

Вход тот же, что в прайс-лист, — по ПИНу администратора. Здесь меняют
проценты мастерам, часы работы и приём записи; приёмщику этого касаться
незачем.

Сами настройки строит SettingsDialog — тот же код, что в окне. Два
набора экранов для одного и того же разошлись бы на первой же правке.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from services import AuthService


class SettingsTab:
    def __init__(self, parent, db):
        self.db = db
        self.frame = ttk.Frame(parent, style='BG.TFrame')

        self.locked = None
        self.body = None

        self.show_lock()

    # ------------------------------------------------------------------
    # Замок
    # ------------------------------------------------------------------

    def show_lock(self):
        """Экран входа. Тот же ПИН, что у прайс-листа."""
        if self.body is not None:
            self.body.destroy()
            self.body = None

        if self.locked is not None:
            self.locked.destroy()

        self.locked = ttk.Frame(self.frame, style='BG.TFrame')
        self.locked.pack(fill='both', expand=True)

        center = ttk.Frame(self.locked, style='BG.TFrame')
        center.place(relx=0.5, rely=0.5, anchor='center')

        # Замок рисуем сами: эмодзи Windows показывает квадратом
        lock = tk.Canvas(center, width=90, height=90,
                         bg=styles.COLORS['bg'], highlightthickness=0)
        lock.create_arc(28, 18, 62, 56, start=0, extent=180, style='arc',
                        outline=styles.COLORS['secondary'], width=7)
        lock.create_rectangle(20, 46, 70, 82,
                              fill=styles.COLORS['secondary'], outline='')
        lock.create_oval(41, 58, 49, 66,
                         fill=styles.COLORS['bg_card'], outline='')
        lock.pack(pady=(0, 14))

        styles.create_label(center, "Настройки программы",
                            'Heading.TLabel').pack()
        ttk.Label(center,
                  text="Здесь меняют часы работы, приём записи, проценты\n"
                       "мастерам и реквизиты. Нужен ПИН администратора.",
                  font=(styles.DEFAULT_FONT, 10),
                  foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg'],
                  justify='center').pack(pady=(6, 16))

        self.pin = styles.create_entry(center, width=14)
        self.pin.configure(show='*', justify='center',
                           font=(styles.DEFAULT_FONT, 18))
        self.pin.pack(pady=(0, 12), ipady=6)
        self.pin.bind('<Return>', lambda e: self.unlock())
        self.pin.focus_set()

        styles.create_button(center, "Войти", self.unlock,
                             'Primary.TButton').pack(fill='x')

    def unlock(self):
        pin = (self.pin.get() or '').strip()

        if not AuthService(self.db).verify_pin(pin):
            messagebox.showerror("Доступ закрыт", "Неверный ПИН-код")
            self.pin.delete(0, 'end')
            self.pin.focus_set()
            return

        self.show_settings()

    # ------------------------------------------------------------------
    # Сами настройки
    # ------------------------------------------------------------------

    def show_settings(self):
        if self.locked is not None:
            self.locked.destroy()
            self.locked = None

        self.body = ttk.Frame(self.frame, style='BG.TFrame')
        self.body.pack(fill='both', expand=True)

        holder = ttk.Frame(self.body, style='BG.TFrame')
        holder.pack(fill='both', expand=True, padx=15, pady=(12, 12))

        from ui.settings_dialog import SettingsDialog

        # «Закрыть доступ» — в строке заголовка: отдельная полоса над
        # настройками съедала место у списка разделов
        self.view = SettingsDialog(self.frame, self.db, host=holder,
                                   on_lock=self.show_lock)
