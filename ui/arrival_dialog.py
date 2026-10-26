"""
QR рядом с «Создать наряд»: телефон для съёмки машин (docs/order_photo.md).

Это тот же пропуск, что у фото мастеров: телефон, подключённый раз,
открывает страницу с закладки. На странице — «Новая машина»: снимок,
номер читается сам, человек подтверждает, и здесь открывается окно
создания наряда.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles


class PhoneCodeDialog:
    def __init__(self, parent, db):
        self.db = db
        from services.sync_service import SyncService
        sync = SyncService(db)
        if not sync.is_enabled():
            messagebox.showinfo('Обмен не настроен',
                                'Наряд по фото работает через сервер. Включите обмен '
                                'в «Настройки» → «Связь с приложением».', parent=parent)
            return
        try:
            answer = sync.master_link()
        except Exception as e:
            messagebox.showerror('Не вышло', f'Не удалось получить код:\n{e}', parent=parent)
            return

        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Телефон для съёмки машин')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=20, pady=16)
        styles.create_label(body, 'Наряд по фото машины', 'CardHeading.TLabel').pack(anchor='w')
        canvas = tk.Canvas(body, width=260, height=260, bg='white', highlightthickness=0)
        canvas.pack(pady=12)
        from ui.photo_dialog import draw_qr
        draw_qr(canvas, answer['url'])
        ttk.Label(body, text=(
            'Наведите камеру телефона на код. На странице нажмите «Новая машина» и '
            'снимите машину так, чтобы был виден номер: он прочитается сам.\n\n'
            'После «Создать наряд» на телефоне здесь откроется окно наряда '
            f'с номером и фото. Код действует {answer.get("minutes", 15)} мин; '
            'подключать телефон нужно один раз.'),
            wraplength=300, justify='left', font=styles.FONTS['small'],
            background=styles.COLORS['bg_card'],
            foreground=styles.COLORS['text_secondary']).pack(anchor='w')
        styles.create_button(body, 'Закрыть', self.dialog.destroy,
                             'Secondary.TButton').pack(anchor='e', pady=(12, 0))
        styles.center_window(self.dialog, parent.winfo_toplevel())
