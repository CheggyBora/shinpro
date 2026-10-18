"""
Схема машины сверху: на каком колесе делали ремонт или правку.

Открывается сама, когда в наряд пробивают услугу из списка «Выбор
колеса» (Настройки). Мастер нажимает на колёса — отмеченные синие —
и «Готово». Сколько колёс отмечено, столько выполнений встанет в
наряд.
"""
import tkinter as tk
from tkinter import ttk

from services.wheel_service import wheels_for, full_name, SPARE
import styles

TIRE = '#334155'
TIRE_PICKED = '#2563eb'
BODY = '#e2e8f0'
BODY_LINE = '#94a3b8'
GLASS = '#cbd5e1'

WIDTH = 340


def _layout(vehicle_type):
    """
    Где рисовать колёса: {код: (x0, y0, x1, y1)} и рамка кузова.
    Перед машины — сверху.
    """
    if vehicle_type == 'truck':
        body = (115, 40, 225, 420)
        wheels = {
            'ПЛ': (79, 85, 113, 155),
            'ПП': (227, 85, 261, 155),
            'ЗЛн': (43, 315, 77, 385),
            'ЗЛв': (79, 315, 113, 385),
            'ЗПв': (227, 315, 261, 385),
            'ЗПн': (263, 315, 297, 385),
        }
        return body, wheels, 470
    body = (110, 40, 230, 370)
    wheels = {
        'ПЛ': (74, 85, 108, 155),
        'ПП': (232, 85, 266, 155),
        'ЗЛ': (74, 260, 108, 330),
        'ЗП': (232, 260, 266, 330),
    }
    return body, wheels, 420


def pick_wheels(parent, vehicle_type, service_name, initial=None,
                already=None):
    """
    Показать схему и дождаться выбора.

    Список отмеченных колёс; пустой список — «Пропустить» (не знают,
    какое колесо, услугу добавить без него); None — «Отмена», услугу
    не добавлять.
    """
    picker = WheelPicker(parent, vehicle_type, service_name,
                         initial=initial, already=already)
    picker.window.wait_window()
    return picker.result


class WheelPicker:
    def __init__(self, parent, vehicle_type, service_name, initial=None,
                 already=None):
        self.vehicle_type = vehicle_type
        self.result = None
        self.picked = []
        for code in initial or []:
            if code not in self.picked:
                self.picked.append(code)

        self.window = tk.Toplevel(parent)
        self.window.title('Какое колесо')
        self.window.configure(bg=styles.COLORS['bg_card'])
        self.window.resizable(False, False)
        self.window.transient(parent.winfo_toplevel())

        body = ttk.Frame(self.window, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=14)

        ttk.Label(body, text=service_name,
                  font=(styles.DEFAULT_FONT, 12, 'bold'),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text']).pack(anchor='w')
        ttk.Label(body, text='Нажмите на колёса, на которых делали работу',
                  font=(styles.DEFAULT_FONT, 9),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text_secondary']).pack(
                      anchor='w', pady=(2, 8))

        frame, self.places, height = _layout(vehicle_type)
        self.canvas = tk.Canvas(body, width=WIDTH, height=height,
                                bg=styles.COLORS['bg_card'],
                                highlightthickness=0)
        self.canvas.pack()
        self._draw_car(frame, height)

        self.spare_button = styles.create_button(
            body, 'Запаска', lambda: self.toggle(SPARE[0]),
            'Compact.Secondary.TButton')
        self.spare_button.pack(fill='x', pady=(6, 0))

        if already:
            from services.wheel_service import describe, join
            ttk.Label(body, text='Уже в наряде: ' + describe(join(already)),
                      font=(styles.DEFAULT_FONT, 9),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text_secondary']).pack(
                          anchor='w', pady=(8, 0))

        self.summary = ttk.Label(body, text='',
                                 font=(styles.DEFAULT_FONT, 10),
                                 background=styles.COLORS['bg_card'],
                                 foreground=styles.COLORS['text'])
        self.summary.pack(anchor='w', pady=(8, 0))

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        self.done_button = styles.create_button(buttons, 'Готово', self.confirm,
                                                'Primary.TButton')
        self.done_button.pack(side='left', fill='x', expand=True, padx=(0, 4))
        # Не знают, на каком колесе делали, — услуга всё равно в наряде
        styles.create_button(buttons, 'Пропустить', self.skip,
                             'Secondary.TButton').pack(
                                 side='left', fill='x', expand=True, padx=4)
        styles.create_button(buttons, 'Отмена', self.cancel,
                             'Secondary.TButton').pack(
                                 side='left', fill='x', expand=True, padx=(4, 0))

        self.window.bind('<Escape>', lambda e: self.cancel())
        self.window.bind('<Return>', lambda e: self.confirm())
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)

        self.redraw()
        styles.center_window(self.window, parent.winfo_toplevel())
        self.window.grab_set()
        self.window.focus_set()

    # ------------------------------------------------------------------

    def _draw_car(self, frame, height):
        x0, y0, x1, y1 = frame
        c = self.canvas
        c.create_text(WIDTH // 2, 18, text='▲ ПЕРЕД',
                      font=(styles.DEFAULT_FONT, 9, 'bold'),
                      fill=styles.COLORS['text_secondary'])

        # Кузов: прямоугольник со скруглёнными углами
        r = 26
        c.create_polygon(
            x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
            x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
            smooth=True, fill=BODY, outline=BODY_LINE, width=2)

        middle = (x0 + x1) // 2
        if self.vehicle_type == 'truck':
            # Кабина и кузов-фургон
            c.create_rectangle(x0 + 8, y0 + 18, x1 - 8, y0 + 48,
                               fill=GLASS, outline='')
            c.create_line(x0, y0 + 130, x1, y0 + 130, fill=BODY_LINE, width=2)
        else:
            # Лобовое и заднее стекло
            c.create_polygon(x0 + 14, y0 + 78, x1 - 14, y0 + 78,
                             x1 - 24, y0 + 112, x0 + 24, y0 + 112,
                             fill=GLASS, outline='')
            c.create_polygon(x0 + 24, y1 - 82, x1 - 24, y1 - 82,
                             x1 - 14, y1 - 56, x0 + 14, y1 - 56,
                             fill=GLASS, outline='')

        c.create_text(middle, height - 14, text='ЗАД',
                      font=(styles.DEFAULT_FONT, 9, 'bold'),
                      fill=styles.COLORS['text_secondary'])

        for code, (wx0, wy0, wx1, wy1) in self.places.items():
            tag = f'wheel_{code}'
            c.create_rectangle(wx0, wy0, wx1, wy1, fill=TIRE, outline='',
                               tags=(tag, f'{tag}_tire'))
            # Подпись снаружи колеса, у внутренних — внутри кузова
            left = wx0 < middle
            inner = code.endswith('в')
            if left != inner:
                lx, anchor = wx0 - 6, 'e'
            else:
                lx, anchor = wx1 + 6, 'w'
            c.create_text(lx, (wy0 + wy1) // 2, text=code, anchor=anchor,
                          font=(styles.DEFAULT_FONT, 10, 'bold'),
                          fill=styles.COLORS['text'], tags=(tag,))
            c.tag_bind(tag, '<Button-1>', lambda e, k=code: self.toggle(k))
            c.tag_bind(tag, '<Enter>', lambda e: c.configure(cursor='hand2'))
            c.tag_bind(tag, '<Leave>', lambda e: c.configure(cursor=''))

    def toggle(self, code):
        if code in self.picked:
            self.picked.remove(code)
        else:
            self.picked.append(code)
        self.redraw()

    def redraw(self):
        for code in self.places:
            self.canvas.itemconfigure(
                f'wheel_{code}_tire',
                fill=TIRE_PICKED if code in self.picked else TIRE)
        self.spare_button.configure(
            style='Compact.Primary.TButton' if SPARE[0] in self.picked
            else 'Compact.Secondary.TButton')

        order = [code for code, _ in wheels_for(self.vehicle_type)]
        picked = sorted(self.picked, key=lambda k: order.index(k)
                        if k in order else len(order))
        if picked:
            names = ', '.join(full_name(code) for code in picked)
            self.summary.configure(text=f'Отмечено: {len(picked)} — {names}',
                                   foreground=styles.COLORS['text'])
            self.done_button.state(['!disabled'])
        else:
            self.summary.configure(text='Колесо не отмечено',
                                   foreground=styles.COLORS['text_secondary'])
            self.done_button.state(['disabled'])

    def confirm(self):
        if not self.picked:
            return
        order = [code for code, _ in wheels_for(self.vehicle_type)]
        self.result = sorted(self.picked, key=lambda k: order.index(k)
                             if k in order else len(order))
        self._close()

    def skip(self):
        self.result = []
        self._close()

    def cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()
