"""
Настройки → Календарь: разделы задач (решение владельца 30.10.2026).

Встроенные можно переименовать и скрыть, свои — ещё и перекрасить.
Удаления нет, только «скрыть»: старые задачи раздела остаются со своим
названием. Правки сохраняются сразу и уходят в дашборд обменом.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import styles
from services import task_sections

WHERE = {('tire',): 'Шиномонтаж', ('wash',): 'Мойка', ('tire', 'wash'): 'Шиномонтаж и мойка'}


class TaskSectionsEditor:
    def __init__(self, parent, db, dialog, on_change=None, wash=False):
        self.db = db
        self.dialog = dialog
        self.on_change = on_change
        self.wash = wash

        self.tree = ttk.Treeview(parent, columns=('title', 'where', 'state'),
                                 show='headings', height=7)
        for column, title, width in (('title', 'Раздел', 220), ('where', 'Где', 170),
                                     ('state', 'В новых задачах', 160)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)
        self.tree.pack(fill='x', pady=(0, 6))
        self.tree.bind('<Double-1>', lambda e: self.rename())

        buttons = ttk.Frame(parent, style='White.TFrame')
        buttons.pack(fill='x', pady=(0, 8))
        for title, command in (('+ Раздел', self.add), ('Переименовать', self.rename),
                               ('Другой цвет', self.recolor), ('Скрыть / показать', self.toggle)):
            styles.create_button(buttons, title, command, 'Secondary.TButton').pack(
                side='left', padx=(0, 6))
        if wash:
            styles.create_label(buttons, 'новый — для', 'Card.TLabel').pack(side='left', padx=(10, 4))
            self.where = tk.StringVar(value='Шиномонтаж')
            ttk.Combobox(buttons, textvariable=self.where, state='readonly', width=20,
                         values=list(WHERE.values())).pack(side='left')
        self.draw()

    def draw(self):
        self.tree.delete(*self.tree.get_children())
        for row in task_sections.load(self.db):
            fg, bg = row['colors']
            tag = 'c_' + row['key']
            self.tree.tag_configure(tag, foreground=fg, background=bg)
            state = 'скрыт' if row['hidden'] else 'есть'
            if row['builtin']:
                state += ' · встроенный'
            self.tree.insert('', 'end', iid=row['key'], tags=(tag,),
                             values=(row['title'], WHERE.get(tuple(row['directions']), ''), state))

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo('Разделы', 'Выберите раздел в списке', parent=self.dialog)
            return None
        return selection[0]

    def _changed(self):
        self.draw()
        if self.on_change is not None:
            self.on_change()

    def _run(self, work):
        try:
            work()
        except task_sections.SectionError as e:
            messagebox.showerror('Разделы', str(e), parent=self.dialog)
            return False
        self._changed()
        return True

    def add(self):
        title = simpledialog.askstring('Новый раздел', 'Название, например «От контрагента»:',
                                       parent=self.dialog)
        if title is None:
            return
        directions = ['tire']
        if self.wash:
            directions = next((list(k) for k, v in WHERE.items() if v == self.where.get()), ['tire'])
        self._run(lambda: task_sections.add(self.db, title, directions))

    def rename(self):
        key = self._selected()
        if key is None:
            return
        current = self.tree.item(key)['values'][0]
        title = simpledialog.askstring('Переименовать', 'Новое название:', initialvalue=current,
                                       parent=self.dialog)
        if title is None:
            return
        self._run(lambda: task_sections.rename(self.db, key, title))

    def recolor(self):
        key = self._selected()
        if key is None:
            return
        row = next(r for r in task_sections.load(self.db) if r['key'] == key)
        if row['builtin']:
            messagebox.showinfo('Разделы', 'Цвет меняется только у своих разделов: у встроенных '
                                           'он одинаковый в цеху и в дашборде.', parent=self.dialog)
            return
        self._run(lambda: task_sections.set_color(self.db, key, row.get('color', 0) + 1))
        self.tree.selection_set(key)

    def toggle(self):
        key = self._selected()
        if key is None:
            return
        row = next(r for r in task_sections.load(self.db) if r['key'] == key)
        self._run(lambda: task_sections.set_hidden(self.db, key, not row['hidden']))
        self.tree.selection_set(key)
