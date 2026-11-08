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
        self.alone_box.pack(anchor='w', pady=(0, 4))

        # Администратор — свой процент со всего наряда, в делёжку мастеров
        # не входит (решение владельца 08.11.2026)
        self.admin_var = tk.BooleanVar(value=False)
        self.admin_box = ttk.Checkbutton(
            right, text='Администратор: свой процент с выручки шиномонтажа и мойки, работу не делит',
            variable=self.admin_var, command=self.save_admin)
        self.admin_box.pack(anchor='w', pady=(0, 10))

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
            self.admin_box.state(['disabled'])
            return
        self.alone_box.state(['!disabled'])
        self.alone_var.set(role.can_work_alone is not False)
        self.admin_box.state(['!disabled'])
        self.admin_var.set(bool(role.is_admin))

        self.caption.config(
            text=f'«{role.title}»: отметьте услуги, с которых НЕ начислять')

        from services import directions
        excluded = role.excluded
        # Мойщикам — только процент (решение владельца 09.11.2026): у
        # мастерских категорий — услуги шиномонтажа. Администратору —
        # по направлениям, и с товаров — отдельно
        groups = [('Шиномонтаж', self.service.service_names('tire'))]
        if role.is_admin and directions.wash_on(self.db):
            groups.append(('Мойка', self.service.service_names('wash')))
        if len(groups) == 1:
            groups = [(None, groups[0][1])]
        row = 0
        shown = set()
        for title, names in groups:
            if title:
                self._small(title.upper(), bold=True).grid(row=row, column=0, columnspan=2,
                                                            sticky='w', pady=(8 if row else 0, 2))
                row += 1
            # Две колонки: услуг в прайсе за тридцать, в одну не влезают
            half = (len(names) + 1) // 2
            for index, name in enumerate(names):
                var = tk.BooleanVar(value=name in excluded)
                box = ttk.Checkbutton(self.services_frame, text=name, variable=var,
                                      command=self.save)
                box.grid(row=row + (index % half if half else 0),
                         column=index // half if half else 0, sticky='w', padx=(0, 18), pady=1)
                self.checks[name] = var
                shown.add(name)
            row += half

        self.goods_vars = {}
        if role.is_admin:
            self._small('С ТОВАРОВ (вентили, грузики, химия) — платить процент:', bold=True).grid(
                row=row, column=0, columnspan=2, sticky='w', pady=(10, 2))
            row += 1
            have = [(directions.TIRE, 'с товаров шиномонтажа')]
            if directions.wash_on(self.db):
                have.append((directions.WASH, 'с товаров мойки'))
            for key, text in have:
                var = tk.BooleanVar(value=key in role.goods_from)
                ttk.Checkbutton(self.services_frame, text=text, variable=var,
                                command=self.save_goods).grid(row=row, column=0, columnspan=2,
                                                              sticky='w', pady=1)
                self.goods_vars[key] = var
                row += 1
            self._small('По умолчанию с товаров не платится. Магазин — по правилам магазина '
                        '(Настройки → «От чего считается зарплата»).').grid(
                row=row, column=0, columnspan=2, sticky='w')
            row += 1

        # Исключённые услуги, которых в прайсе уже нет, не теряем молча:
        # снятая с прайса и возвращённая услуга начислялась бы всем
        gone = sorted(excluded - set(self.service.service_names()))
        if gone:
            self._small('Нет в прайсе, но исключены: ' + ', '.join(gone)).grid(
                row=row + 1, column=0, columnspan=2, sticky='w', pady=(8, 0))
        # Исключённое, чего здесь не видно (мойка у мастерской категории),
        # сохраняем как было
        self._gone = excluded - shown

    def _small(self, text, bold=False):
        return ttk.Label(self.services_frame, text=text,
                         font=(styles.DEFAULT_FONT, 9, 'bold') if bold else (styles.DEFAULT_FONT, 9),
                         background=styles.COLORS['bg_card'],
                         foreground=styles.COLORS['text_secondary'])

    def save_goods(self):
        if self.role_id is None:
            return
        try:
            self.service.set_goods(self.role_id, [k for k, v in self.goods_vars.items() if v.get()])
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}', parent=self.window)

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

    def save_admin(self):
        if self.role_id is None:
            return
        try:
            self.service.set_admin(self.role_id, self.admin_var.get())
        except Exception as e:
            self.db.rollback()
            messagebox.showerror('Ошибка', f'Не удалось сохранить: {e}',
                                 parent=self.window)
            return
        # У администратора — свой список: мойка и товары
        self.draw_services()

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
