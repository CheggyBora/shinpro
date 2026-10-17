"""
Настройка групп клиентов: коды, названия, как говорить.

Правки сохраняются сразу, а не по общей кнопке «Сохранить» настроек:
группу ставят в наряде в ту же минуту, и ждать сохранения всего окна
ей незачем.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from services.client_group_service import ClientGroupService
import styles


class ClientGroupsEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.service = ClientGroupService(db)

        frame = ttk.Frame(parent, style='White.TFrame')
        frame.pack(fill='x', pady=(0, 10))

        self.tree = ttk.Treeview(frame, columns=('code', 'title', 'hint'),
                                 show='headings', height=6)
        for column, title, width in (('code', 'Код', 60),
                                     ('title', 'Группа', 160),
                                     ('hint', 'Как говорить', 360)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, anchor='w')
        self.tree.pack(fill='x')
        self.tree.bind('<Double-1>', lambda e: self.edit())

        buttons = ttk.Frame(parent, style='White.TFrame')
        buttons.pack(fill='x', pady=(0, 10))
        styles.create_button(buttons, 'Добавить', self.add,
                             'Success.TButton').pack(side='left')
        styles.create_button(buttons, 'Изменить', self.edit,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))
        styles.create_button(buttons, 'Удалить', self.delete,
                             'Danger.TButton').pack(side='left', padx=(6, 0))

        self.refresh()

    def refresh(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        try:
            groups = self.service.groups()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось прочитать группы: {e}',
                                 parent=self.window)
            return
        for group in groups:
            self.tree.insert('', 'end', iid=str(group.id),
                             values=(group.code, group.title, group.hint or ''))

    def _selected(self):
        chosen = self.tree.selection()
        if not chosen:
            messagebox.showinfo('Группы', 'Выберите группу в списке',
                                parent=self.window)
            return None
        return int(chosen[0])

    def add(self):
        self._ask(None)

    def edit(self):
        group_id = self._selected()
        if group_id is not None:
            self._ask(self.service.get(group_id))

    def delete(self):
        group_id = self._selected()
        if group_id is None:
            return
        group = self.service.get(group_id)
        if group is None:
            return self.refresh()

        count = self.service.count_clients(group_id)
        question = f'Удалить группу {group.code} «{group.title}»?'
        if count:
            question += (f'\n\nВ ней клиентов: {count}. Они останутся '
                         f'без группы.')
        if not messagebox.askyesno('Удалить группу', question,
                                   parent=self.window):
            return
        try:
            self.service.delete(group_id)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось удалить: {e}',
                                 parent=self.window)
        self.refresh()

    def _ask(self, group):
        dialog = tk.Toplevel(self.window)
        dialog.title('Группа клиентов')
        dialog.configure(bg=styles.COLORS['bg_card'])
        dialog.resizable(False, False)
        dialog.transient(self.window)

        body = ttk.Frame(dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=16)

        entries = {}
        for row, (key, title, width) in enumerate((
                ('code', 'Код (например, 11):', 10),
                ('title', 'Название:', 32),
                ('hint', 'Как говорить:', 48))):
            styles.create_label(body, title, 'Card.TLabel').grid(
                row=row, column=0, sticky='w', pady=4)
            entry = styles.create_entry(body, width=width)
            entry.grid(row=row, column=1, sticky='w', padx=(10, 0), pady=4)
            if group is not None:
                entry.insert(0, getattr(group, key) or '')
            entries[key] = entry

        def save():
            try:
                if group is None:
                    self.service.add(entries['code'].get(),
                                     entries['title'].get(),
                                     entries['hint'].get())
                else:
                    self.service.update(group.id, entries['code'].get(),
                                        entries['title'].get(),
                                        entries['hint'].get())
            except ValueError as e:
                messagebox.showerror('Группа', str(e), parent=dialog)
                return
            except Exception as e:
                self.db.rollback()
                messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                     parent=dialog)
                return
            dialog.destroy()
            self.refresh()

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(12, 0))
        styles.create_button(buttons, 'Сохранить', save,
                             'Primary.TButton').pack(side='left')
        styles.create_button(buttons, 'Отмена', dialog.destroy,
                             'Secondary.TButton').pack(side='left', padx=(6, 0))

        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        styles.center_window(dialog, self.window)
        dialog.grab_set()
        entries['code'].focus_set()
        return dialog
