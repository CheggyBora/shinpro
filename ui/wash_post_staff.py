"""
Кто на каком посту мойки в эту смену (решение владельца 13.11.2026).

В начале смены на каждый пост ставят мойщиков и администратора. Наряд
встаёт на пост — они подставляются в него сами: мойку делят мойщики
поста, процент администратора — администратору поста. В наряде можно
поменять.
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles


class WashPostStaffDialog:
    def __init__(self, parent, db):
        from services import directions
        from services.salary_service import SalaryService
        from services.shift_service import ShiftService
        from services.wash_posts import WashPosts
        from models import WorkShift

        self.db = db
        if not directions.wash_on(db):
            messagebox.showinfo('Посты мойки', 'Мойка выключена (Настройки → «Что работает»).',
                                parent=parent)
            self.dialog = None
            return
        if ShiftService(db).get_current_shift() is None:
            messagebox.showinfo('Посты мойки', 'Сначала откройте смену.', parent=parent)
            self.dialog = None
            return
        self.posts = WashPosts(db)
        admins = SalaryService(db).admins_on_shift()
        admin_ids = {a.id for a in admins}
        people = []
        for shift in db.query(WorkShift).filter(WorkShift.end_time.is_(None)).order_by(
                WorkShift.employee_id).all():
            if shift.employee is not None and shift.employee.id not in admin_ids \
                    and shift.employee.id not in [p.id for p in people]:
                people.append(shift.employee)
        self.admins = admins
        staff = self.posts.staff()

        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Посты мойки на смену')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=14)
        styles.create_label(body, 'Кто на каком посту мойки сегодня. Наряд встаёт на пост — '
                                  'мойщики и администратор подставятся сами.',
                            'Card.TLabel').pack(anchor='w', pady=(0, 10))
        self.rows = {}
        for post in range(1, self.posts.total() + 1):
            mine = staff.get(post) or {}
            box = ttk.LabelFrame(body, text=f'Пост мойки {post}')
            box.pack(fill='x', pady=4)
            marks = {}
            line = ttk.Frame(box)
            line.pack(fill='x', padx=8, pady=4)
            ttk.Label(line, text='Мойщики:').pack(side='left')
            for person in people:
                marks[person.id] = tk.BooleanVar(value=person.id in (mine.get('washers') or []))
                ttk.Checkbutton(line, text=person.name or f'№{person.id}',
                                variable=marks[person.id]).pack(side='left', padx=(8, 0))
            admin_var = tk.StringVar()
            if admins:
                line2 = ttk.Frame(box)
                line2.pack(fill='x', padx=8, pady=(0, 6))
                ttk.Label(line2, text='Администратор:').pack(side='left')
                titles = ['—'] + [a.title for a in admins]
                current = next((a.title for a in admins if a.id == mine.get('admin')), '—')
                admin_var.set(current)
                ttk.Combobox(line2, textvariable=admin_var, values=titles, state='readonly',
                             width=24).pack(side='left', padx=(8, 0))
            self.rows[post] = (marks, admin_var)
        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Сохранить', self.save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(self.dialog, parent.winfo_toplevel())
        self.dialog.grab_set()

    def save(self):
        for post, (marks, admin_var) in self.rows.items():
            washers = [pid for pid, var in marks.items() if var.get()]
            admin = next((a.id for a in self.admins if a.title == admin_var.get()), None)
            self.posts.set_post_staff(post, washers, admin)
        self.dialog.destroy()
