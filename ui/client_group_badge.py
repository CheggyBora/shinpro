"""
Значок группы клиента: в наряде и в карточке.

Сам значок одинаковый у всех — стоит группа или нет, какая она. По
нему ничего не прочесть, пока не нажмёшь: клиент у стойки видит
обычную кнопку «⋯». Нажал — открылось окошко с кодом группы, тем,
как с человеком говорить, и кнопками, чтобы поменять.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from services.client_group_service import ClientGroupService
import styles

BADGE_TEXT = '⋯'


def create_group_badge(parent, db, client_id, on_change=None):
    """Кнопка-значок. Возвращает её — разместить, как удобно."""
    button = ttk.Button(parent, text=BADGE_TEXT, width=2,
                        style='Badge.Secondary.TButton')
    button.configure(command=lambda: open_group_popup(
        button, db, client_id, on_change))
    return button


def open_group_popup(anchor, db, client_id, on_change=None):
    """Окошко группы под значком. Возвращает окно."""
    return GroupPopup(anchor, db, client_id, on_change).window


class GroupPopup:
    def __init__(self, anchor, db, client_id, on_change=None):
        self.db = db
        self.client_id = client_id
        self.on_change = on_change
        self.service = ClientGroupService(db)

        self.window = tk.Toplevel(anchor)
        # В заголовке — ничего говорящего: окно видно и через плечо
        self.window.title('Клиент')
        self.window.configure(bg=styles.COLORS['bg_card'])
        self.window.resizable(False, False)
        self.window.transient(anchor.winfo_toplevel())

        self.body = ttk.Frame(self.window, style='White.TFrame')
        self.body.pack(fill='both', expand=True, padx=16, pady=14)

        self.window.bind('<Escape>', lambda e: self.close())

        try:
            self.draw()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось открыть: {e}',
                                 parent=anchor.winfo_toplevel())
            self.window.destroy()
            return

        # Под значком, а не посреди экрана: так понятно, к чему окошко
        self.window.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 2
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        x = max(0, min(x, screen_w - width - 8))

        # Внизу экрана — панель задач. Не влезает под значком — ставим
        # над ним, а если и там тесно, прижимаем к верху
        bottom_room = screen_h - 60
        if y + height > bottom_room:
            above = anchor.winfo_rooty() - height - 34
            y = above if above >= 0 else max(0, bottom_room - height)
        self.window.geometry(f'+{x}+{y}')

        self.window.grab_set()
        self.window.focus_set()

    def draw(self):
        for child in self.body.winfo_children():
            child.destroy()

        groups = self.service.groups()
        current = self.service.group_of(self.client_id)

        # --- Что стоит сейчас ---------------------------------------
        if current is not None:
            top = ttk.Frame(self.body, style='White.TFrame')
            top.pack(fill='x')
            ttk.Label(top, text=current.code,
                      font=(styles.DEFAULT_FONT, 22, 'bold'),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text']).pack(side='left')
            ttk.Label(top, text=current.title,
                      font=(styles.DEFAULT_FONT, 11, 'bold'),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text']).pack(
                          side='left', padx=(10, 0))

            if current.hint:
                ttk.Label(self.body, text=current.hint, wraplength=300,
                          justify='left', font=(styles.DEFAULT_FONT, 10),
                          background=styles.COLORS['bg_card'],
                          foreground=styles.COLORS['text']).pack(
                              anchor='w', pady=(6, 0))

            client = self._client()
            if client is not None and client.group_set_at:
                ttk.Label(self.body,
                          text='Поставлена ' +
                          client.group_set_at.strftime('%d.%m.%Y'),
                          font=(styles.DEFAULT_FONT, 9),
                          background=styles.COLORS['bg_card'],
                          foreground=styles.COLORS['text_secondary']).pack(
                              anchor='w', pady=(4, 0))
        else:
            ttk.Label(self.body, text='Группа не поставлена',
                      font=(styles.DEFAULT_FONT, 11, 'bold'),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text']).pack(anchor='w')

        ttk.Separator(self.body, orient='horizontal').pack(
            fill='x', pady=(12, 10))

        # --- Поменять -----------------------------------------------
        if not groups:
            ttk.Label(self.body,
                      text='Групп нет. Заведите их в Настройках → '
                           'Группы клиентов',
                      wraplength=300, justify='left',
                      font=(styles.DEFAULT_FONT, 9),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text_secondary']).pack(
                          anchor='w')
        for group in groups:
            is_current = current is not None and group.id == current.id
            styles.create_button(
                self.body, f'{group.code}  ·  {group.title}',
                lambda g=group.id: self.choose(g),
                'Compact.Primary.TButton' if is_current
                else 'Compact.Secondary.TButton'
            ).pack(fill='x', pady=(0, 3))

        bottom = ttk.Frame(self.body, style='White.TFrame')
        bottom.pack(fill='x', pady=(8, 0))
        if current is not None:
            styles.create_button(bottom, 'Снять группу',
                                 lambda: self.choose(None),
                                 'Compact.Secondary.TButton').pack(side='left')
        styles.create_button(bottom, 'Закрыть', self.close,
                             'Compact.Secondary.TButton').pack(side='right')

    def _client(self):
        from models import Client
        return self.db.query(Client).filter(
            Client.id == self.client_id).first()

    def choose(self, group_id):
        try:
            self.service.set_group(self.client_id, group_id)
        except ValueError as e:
            messagebox.showerror('Ошибка', str(e), parent=self.window)
            return
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                 parent=self.window)
            return

        # Без «Сохранено!»: всплывашка с восклицанием посреди разговора
        # привлекает ровно то внимание, от которого прячем
        self.close()
        if self.on_change:
            self.on_change()

    def close(self):
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()
