"""
Настройка категорий мастеров: с каких услуг какой категории не
начисляется.

Слева категории, справа услуги прайса галочками. Галочка — «этой
категории с этой услуги не начислять». Сохраняется сразу: это не те
настройки, что ждут общей кнопки, и забытое «Сохранить» здесь стоило
бы людям денег.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from services.employee_role_service import EmployeeRoleService
import styles


class EmployeeRolesEditor:
    def __init__(self, parent, db, window):
        self.db = db
        self.window = window
        self.service = EmployeeRoleService(db)
        self.role_id = None
        self.checks = {}

        body = ttk.Frame(parent, style='White.TFrame')
        body.pack(fill='both', expand=True, pady=(0, 10))

        # --- Категории ----------------------------------------------
        left = ttk.Frame(body, style='White.TFrame')
        left.pack(side='left', fill='y')

        self.roles_list = tk.Listbox(
            left, height=8, width=24, exportselection=False,
            font=styles.FONTS['normal'], bg=styles.COLORS['bg_subtle'],
            fg=styles.COLORS['text'],
            selectbackground=styles.COLORS['primary'],
            relief='flat', highlightthickness=1,
            highlightbackground=styles.COLORS['border'])
        self.roles_list.pack(fill='y')
        self.roles_list.bind('<<ListboxSelect>>', lambda e: self.pick())

        buttons = ttk.Frame(left, style='White.TFrame')
        buttons.pack(fill='x', pady=(6, 0))
        styles.create_button(buttons, 'Добавить', self.add,
                             'Compact.Secondary.TButton').pack(fill='x')
        styles.create_button(buttons, 'Переименовать', self.rename,
                             'Compact.Secondary.TButton').pack(fill='x', pady=(3, 0))
        styles.create_button(buttons, 'Удалить', self.delete,
                             'Compact.Secondary.TButton').pack(fill='x', pady=(3, 0))

        # --- Услуги -------------------------------------------------
        right = ttk.Frame(body, style='White.TFrame')
        right.pack(side='left', fill='both', expand=True, padx=(16, 0))

        self.caption = ttk.Label(
            right, text='', font=(styles.DEFAULT_FONT, 10, 'bold'),
            background=styles.COLORS['bg_card'],
            foreground=styles.COLORS['text'])
        self.caption.pack(anchor='w', pady=(0, 6))

        self.alone_var = tk.BooleanVar(value=True)
        self.alone_box = ttk.Checkbutton(
            right, text='Может стоять на смене один (без мастера)',
            variable=self.alone_var, command=self.save_alone)
        self.alone_box.pack(anchor='w', pady=(0, 10))

        self.services_frame = ttk.Frame(right, style='White.TFrame')
        self.services_frame.pack(fill='both', expand=True)

        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self, select_id=None):
        try:
            self.roles = self.service.roles()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось прочитать категории: {e}',
                                 parent=self.window)
            return

        self.roles_list.delete(0, tk.END)
        for role in self.roles:
            count = len(role.excluded)
            suffix = f'  (без {count})' if count else ''
            self.roles_list.insert(tk.END, role.title + suffix)

        ids = [r.id for r in self.roles]
        keep = select_id if select_id in ids else (
            self.role_id if self.role_id in ids else (ids[0] if ids else None))
        if keep is not None:
            index = ids.index(keep)
            self.roles_list.selection_clear(0, tk.END)
            self.roles_list.selection_set(index)
        self.role_id = keep
        self.draw_services()

    def pick(self):
        chosen = self.roles_list.curselection()
        if not chosen:
            return
        self.role_id = self.roles[chosen[0]].id
        self.draw_services()

    def draw_services(self):
        for child in self.services_frame.winfo_children():
            child.destroy()
        self.checks = {}

        role = self.service.get(self.role_id)
        if role is None:
            self.caption.config(text='Добавьте категорию слева')
            self.alone_box.state(['disabled'])
            return
        self.alone_box.state(['!disabled'])
        self.alone_var.set(role.can_work_alone is not False)

        self.caption.config(
            text=f'«{role.title}»: отметьте услуги, с которых НЕ начислять')

        names = self.service.service_names()
        excluded = role.excluded
        # Две колонки: услуг в прайсе за тридцать, в одну не влезают
        half = (len(names) + 1) // 2
        for index, name in enumerate(names):
            var = tk.BooleanVar(value=name in excluded)
            box = ttk.Checkbutton(self.services_frame, text=name, variable=var,
                                  command=self.save)
            box.grid(row=index % half if half else 0, column=index // half if half else 0,
                     sticky='w', padx=(0, 18), pady=1)
            self.checks[name] = var

        # Исключённые услуги, которых в прайсе уже нет, не теряем молча:
        # иначе снятая с прайса и возвращённая услуга начислялась бы всем
        gone = sorted(excluded - set(names))
        if gone:
            ttk.Label(self.services_frame,
                      text='Нет в прайсе, но исключены: ' + ', '.join(gone),
                      font=(styles.DEFAULT_FONT, 9),
                      background=styles.COLORS['bg_card'],
                      foreground=styles.COLORS['text_secondary']).grid(
                          row=half + 1, column=0, columnspan=2,
                          sticky='w', pady=(8, 0))
        self._gone = set(gone)

    def save(self):
        if self.role_id is None:
            return
        names = {name for name, var in self.checks.items() if var.get()}
        names |= getattr(self, '_gone', set())
        try:
            self.service.set_excluded(self.role_id, names)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                 parent=self.window)
            return
        # Подпись «(без N)» в списке слева
        self.refresh(select_id=self.role_id)

    def save_alone(self):
        if self.role_id is None:
            return
        try:
            self.service.set_can_work_alone(self.role_id, self.alone_var.get())
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                 parent=self.window)

    # ------------------------------------------------------------------

    def add(self):
        title = simpledialog.askstring('Новая категория', 'Название категории:',
                                       parent=self.window)
        if not title:
            return
        try:
            role = self.service.add(title)
        except ValueError as e:
            messagebox.showerror('Категория', str(e), parent=self.window)
            return
        self.refresh(select_id=role.id)

    def rename(self):
        role = self.service.get(self.role_id)
        if role is None:
            return
        title = simpledialog.askstring('Категория', 'Новое название:',
                                       initialvalue=role.title,
                                       parent=self.window)
        if not title:
            return
        try:
            self.service.rename(role.id, title)
        except ValueError as e:
            messagebox.showerror('Категория', str(e), parent=self.window)
            return
        self.refresh(select_id=role.id)

    def delete(self):
        role = self.service.get(self.role_id)
        if role is None:
            return
        count = self.service.count_employees(role.id)
        question = f'Удалить категорию «{role.title}»?'
        if count:
            question += (f'\n\nСотрудников в ней: {count}. Им станет '
                         f'начисляться со всех услуг, как мастеру.')
        if not messagebox.askyesno('Удалить категорию', question,
                                   parent=self.window):
            return
        try:
            self.service.delete(role.id)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось удалить: {e}',
                                 parent=self.window)
        self.role_id = None
        self.refresh()
