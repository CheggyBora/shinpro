"""
Группа клиента: в наряде и в карточке.

Код группы (11, 22, 33…) виден сразу, без нажатия, рядом с кнопкой «⋯»
(решение владельца 28.10.2026). Что код значит, на экране не пишем
нигде — ни рядом, ни в окошке: клиент у стойки видит только цифры.
Расшифровка — в Настройках → Группы клиентов.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from services.client_group_service import ClientGroupService
import styles

BADGE_TEXT = '⋯'


def create_group_badge(parent, db, client_id, on_change=None):
    """
    Код группы и кнопка «⋯», чтобы поставить или поменять. Возвращает
    рамку с ними — разместить, как удобно.
    """
    frame = ttk.Frame(parent, style='White.TFrame')
    code = ttk.Label(frame, text='', font=(styles.DEFAULT_FONT, 12, 'bold'),
                     background=styles.COLORS['bg_card'],
                     foreground=styles.COLORS['text'])
    button = ttk.Button(frame, text=BADGE_TEXT, width=2,
                        style='Badge.Secondary.TButton')

    def show_code():
        try:
            group = ClientGroupService(db).group_of(client_id)
        except Exception:
            db.rollback()
            group = None
        code.configure(text=group.code if group is not None else '')
        if group is not None:
            code.pack(side='left', padx=(0, 4), before=button)
        else:
            code.pack_forget()

    def changed():
        show_code()
        if on_change:
            on_change()

    button.pack(side='left')
    show_code()
    button.configure(command=lambda: open_group_popup(button, db, client_id, changed))
    return frame


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

        # Только коды: что они значат, здесь не пишем (решение владельца
        # 28.10.2026) — окошко видно клиенту через стойку
        ttk.Label(self.body, text='Группа клиента',
                  font=(styles.DEFAULT_FONT, 10, 'bold'),
                  background=styles.COLORS['bg_card'],
                  foreground=styles.COLORS['text']).pack(anchor='w', pady=(0, 8))

        if not groups:
            ttk.Label(self.body,
                      text='Групп нет. Заведите их в Настройках → '
                           'Группы клиентов',
                      wraplength=300, justify='left',
                      font=(styles.DEFAULT_FONT, 9),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text_secondary']).pack(
                          anchor='w')
        grid = ttk.Frame(self.body, style='White.TFrame')
        grid.pack(fill='x')
        for index, group in enumerate(groups):
            is_current = current is not None and group.id == current.id
            styles.create_button(
                grid, group.code,
                lambda g=group.id: self.choose(g),
                'Compact.Primary.TButton' if is_current
                else 'Compact.Secondary.TButton'
            ).grid(row=index // 4, column=index % 4, sticky='ew', padx=(0, 4), pady=(0, 4))

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
