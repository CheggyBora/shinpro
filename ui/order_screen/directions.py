"""
Направления в наряде: шиномонтаж и мойка (services/directions.py).

Наряд один на машину. Приехал на шиномонтаж и решил помыться — «+ Мойка»
добавляет второе направление в тот же наряд: спрашивает класс машины,
если его ещё не знаем, и занимает пост мойки. Услуги мойки начисляются
тому, кто их делал: его выбирают в строке или сразу «Все на одного».
"""
import tkinter as tk
from tkinter import ttk, messagebox

import styles
from logger import log
from services import directions
from ui.order_screen.shift_guard import needs_shift


def employee_name(db, employee_id):
    from models import Employee
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    return employee.title if employee is not None else f'№{employee_id}'


def wash_people(db):
    """Кого можно выбрать: сначала те, кто на смене, потом остальные."""
    from models import Employee, WorkShift
    on_shift = [s.employee_id for s in db.query(WorkShift).filter(WorkShift.end_time.is_(None)).all()]
    people = db.query(Employee).filter(Employee.is_active.isnot(False)).order_by(Employee.id).all()
    return sorted(people, key=lambda e: (e.id not in on_shift, e.id))


def ask_choice(parent, title, prompt, options):
    """Небольшое окно выбора из списка. Возвращает выбранное или None."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=styles.COLORS['bg_card'])
    dialog.transient(parent.winfo_toplevel())
    body = ttk.Frame(dialog, style='White.TFrame')
    body.pack(fill='both', expand=True, padx=18, pady=14)
    styles.create_label(body, prompt, 'Card.TLabel').pack(anchor='w', pady=(0, 8))
    chosen = {'value': None}
    for value, text in options:
        styles.create_button(body, text, lambda v=value: (chosen.update(value=v), dialog.destroy()),
                             'Secondary.TButton').pack(fill='x', pady=2)
    styles.create_button(body, 'Отмена', dialog.destroy, 'Secondary.TButton').pack(fill='x', pady=(10, 0))
    styles.center_window(dialog, parent.winfo_toplevel())
    dialog.grab_set()
    dialog.wait_window()
    return chosen['value']


class OrderDirectionsMixin:
    """Направления наряда, пост мойки и кто делал мойку."""

    # ------------------------------------------------------------------

    @needs_shift
    def add_direction(self, direction):
        wash_class = None
        diameter = None
        if direction == directions.WASH and not (self.order.wash_class or
                                                 (self.order.car and self.order.car.wash_class)):
            wash_class = ask_choice(self.frame, 'Мойка', 'Класс машины для мойки:',
                                    [(k, directions.WASH_CLASS_TITLES[k]) for k in directions.WASH_CLASSES])
            if not wash_class:
                return
        if direction == directions.TIRE and not (self.order.wheel_diameter or
                                                 (self.order.car and self.order.car.wheel_diameter)):
            diameter = ask_choice(self.frame, 'Шиномонтаж', 'Диаметр колёс:',
                                  [(f'R{n}', f'R{n}') for n in range(13, 25)])
            if not diameter:
                return
        try:
            self.order_service.add_direction(self.order.id, direction, wash_class, diameter)
        except ValueError as e:
            messagebox.showerror('Наряд', str(e), parent=self.frame)
            return
        except Exception as e:
            self.db.rollback()
            log.error(f'Направление не добавилось: {e}')
            messagebox.showerror('Наряд', f'Не получилось: {e}', parent=self.frame)
            return
        self.db.refresh(self.order)
        self.refresh_directions()
        self.pick_services(direction)

    @needs_shift
    def pick_services(self, direction):
        """Список услуг направления — отметить нужные и добавить в наряд."""
        from models import Service
        rows = self.db.query(Service).filter(
            Service.is_active.isnot(False), Service.direction == direction,
            Service.vehicle_type.in_([self.order.vehicle_type or 'car', 'all'])).order_by(Service.name).all()
        unique = {}
        for row in rows:
            if row.name not in unique or row.vehicle_type == self.order.vehicle_type:
                unique[row.name] = row
        if not unique:
            messagebox.showinfo('Услуги', 'В прайс-листе нет услуг этого направления', parent=self.frame)
            return
        dialog = tk.Toplevel(self.frame)
        dialog.title(f'Услуги: {directions.TITLES[direction].lower()}')
        dialog.configure(bg=styles.COLORS['bg_card'])
        dialog.transient(self.frame.winfo_toplevel())
        body = ttk.Frame(dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=16, pady=14)
        box = tk.Listbox(body, selectmode='multiple', height=12, width=44,
                         exportselection=False, font=styles.FONTS['normal'])
        box.pack(fill='both', expand=True)
        services = list(unique.values())
        for service in services:
            price = self.order_service.price_for(service, self.order.wheel_diameter, self.order.wash_class)
            box.insert(tk.END, f'{service.name} — {price:,.0f} ₽'.replace(',', ' '))

        def add():
            for index in box.curselection():
                try:
                    self.add_service(services[index])
                except Exception as e:
                    self.db.rollback()
                    log.error(f'Услуга не добавилась: {e}')
            dialog.destroy()

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        styles.create_button(buttons, 'Добавить', add, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(dialog, self.frame.winfo_toplevel())
        dialog.grab_set()
        dialog.add = add
        dialog.box = box
        self._services_dialog = dialog

    @needs_shift
    def change_wash_post(self):
        from services.wash_posts import WashPosts
        posts = WashPosts(self.db)
        free = [p['post'] for p in posts.posts()
                if p['state'] == 'free' or (p['order'] is not None and p['order'].id == self.order.id)]
        if not free:
            messagebox.showinfo('Пост мойки', 'Свободных постов мойки нет', parent=self.frame)
            return
        post = ask_choice(self.frame, 'Пост мойки', 'Свободные посты мойки:',
                          [(n, f'Пост {n}') for n in free])
        if not post:
            return
        try:
            posts.set_post(self.order, post)
        except ValueError as e:
            messagebox.showerror('Пост мойки', str(e), parent=self.frame)
            return
        self.refresh_directions()

    def _choose_person(self, prompt):
        people = wash_people(self.db)
        if not people:
            messagebox.showinfo('Мойка', 'Нет сотрудников', parent=self.frame)
            return None
        return ask_choice(self.frame, 'Мойка', prompt, [(p.id, p.title) for p in people])

    @needs_shift
    def assign_all_wash(self, direction=directions.WASH):
        what = 'мойки' if direction == directions.WASH else 'шиномонтажа'
        who = self._choose_person(f'Все услуги {what} в наряде — на кого?')
        if not who:
            return
        self.order_service.assign_wash(self.order.id, who, direction)
        self.refresh_items()

    @needs_shift
    def choose_masters(self):
        """Кто работает на посту — им и делится шиномонтаж наряда."""
        people = wash_people(self.db)
        chosen = {int(i) for i in (self.order.employee_ids or '').split(',') if i.strip()}
        dialog = tk.Toplevel(self.frame)
        dialog.title('Мастера наряда')
        dialog.configure(bg=styles.COLORS['bg_card'])
        dialog.transient(self.frame.winfo_toplevel())
        body = ttk.Frame(dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=18, pady=14)
        styles.create_label(body, 'Кто работает на этом наряде:', 'Card.TLabel').pack(anchor='w', pady=(0, 8))
        marks = {}
        for person in people:
            marks[person.id] = tk.BooleanVar(value=person.id in chosen)
            ttk.Checkbutton(body, text=person.title, variable=marks[person.id]).pack(anchor='w', pady=1)

        def save():
            ids = [pid for pid, var in marks.items() if var.get()]
            self.order_service.set_order_masters(self.order.id, ids)
            self.db.refresh(self.order)
            dialog.destroy()
            self.update_employees_display()

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(12, 0))
        styles.create_button(buttons, 'Сохранить', save, 'Primary.TButton').pack(side='right')
        styles.create_button(buttons, 'Отмена', dialog.destroy,
                             'Secondary.TButton').pack(side='right', padx=(0, 6))
        styles.center_window(dialog, self.frame.winfo_toplevel())
        dialog.grab_set()
        dialog.marks, dialog.save = marks, save
        self._masters_dialog = dialog

    @needs_shift
    def choose_item_employee(self, item):
        if not directions.assigned(self.db, item.direction or 'tire'):
            return
        who = self._choose_person(f'Кто делал «{item.service.name}»?')
        if not who:
            return
        self.order_service.set_item_employee(item.id, who)
        self.refresh_items()
