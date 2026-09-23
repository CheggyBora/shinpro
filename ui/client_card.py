"""
Карточка клиента: данные, машины и история визитов.

Отдельным окном, потому что открывается из двух мест — из наряда
и из вкладки «Клиенты».
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from models import Client
from services import ClientService, OrderService
from utils import format_phone, normalize_plate
import styles

VEHICLE_TYPES = {
    'car': 'Легковой',
    'suv': 'Джип/Кроссовер/Пикап',
    'truck': 'Категория С (коммерческий)',
}
VEHICLE_TYPES_REVERSE = {v: k for k, v in VEHICLE_TYPES.items()}

WHEELS = {
    'Не выяснено': None,
    'В сборе (на дисках)': True,
    'Без дисков (только шины)': False,
}
WHEELS_REVERSE = {True: 'В сборе (на дисках)', False: 'Без дисков (только шины)'}

DIAMETERS = [f'R{n}' for n in range(13, 25)]


def open_client_card(parent, db, client_id):
    """Открыть карточку клиента. Возвращает окно."""
    return ClientCard(parent, db, client_id).dialog


class ClientCard:
    def __init__(self, parent, db, client_id):
        self.db = db
        self.client_id = client_id
        self.client_service = ClientService(db)
        self.order_service = OrderService(db)

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Карточка клиента")
        self.dialog.geometry("820x640")
        self.dialog.configure(bg=styles.COLORS['bg'])
        self.dialog.transient(parent.winfo_toplevel())
        styles.center_window(self.dialog, parent.winfo_toplevel())

        content = ttk.Frame(self.dialog, style='White.TFrame')
        content.pack(fill='both', expand=True, padx=20, pady=20)

        # --- Данные клиента -------------------------------------------
        styles.create_label(content, "Клиент", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 10))

        fields = ttk.Frame(content, style='White.TFrame')
        fields.pack(fill='x', pady=(0, 5))

        styles.create_label(fields, "Имя:", 'Card.TLabel').grid(row=0, column=0, sticky='w', pady=3)
        self.name_entry = styles.create_entry(fields, width=32)
        self.name_entry.grid(row=0, column=1, sticky='w', padx=(10, 20), pady=3)

        styles.create_label(fields, "Телефон:", 'Card.TLabel').grid(row=0, column=2, sticky='w', pady=3)
        self.phone_entry = styles.create_entry(fields, width=24)
        self.phone_entry.grid(row=0, column=3, sticky='w', padx=(10, 20), pady=3)

        styles.create_button(fields, "Сохранить", self.save_client,
                             'Primary.TButton').grid(row=0, column=4, padx=(0, 0))

        self.summary_label = ttk.Label(content, text="", font=(styles.DEFAULT_FONT, 9),
                                       foreground='#64748b')
        self.summary_label.pack(anchor='w', pady=(5, 12))

        # --- Машины ---------------------------------------------------
        cars_header = ttk.Frame(content, style='White.TFrame')
        cars_header.pack(fill='x', pady=(0, 5))
        styles.create_label(cars_header, "Автомобили", 'CardHeading.TLabel').pack(side='left')
        styles.create_button(cars_header, "Удалить", self.delete_car,
                             'Danger.TButton').pack(side='right')
        styles.create_button(cars_header, "Открепить", self.detach_car,
                             'Secondary.TButton').pack(side='right', padx=(0, 5))
        styles.create_button(cars_header, "Добавить машину", self.add_car,
                             'Success.TButton').pack(side='right', padx=(0, 5))

        cars_frame = ttk.Frame(content, style='White.TFrame')
        cars_frame.pack(fill='x')

        self.cars_tree = ttk.Treeview(cars_frame, columns=('Номер', 'Тип', 'Диаметр', 'Колёса'),
                                      show='headings', height=5)
        for column, title, width in (('Номер', 'Госномер', 150),
                                     ('Тип', 'Тип транспорта', 220),
                                     ('Диаметр', 'Диаметр', 110),
                                     ('Колёса', 'Колёса', 240)):
            self.cars_tree.heading(column, text=title)
            self.cars_tree.column(column, width=width, anchor='w')
        self.cars_tree.pack(side='left', fill='x', expand=True)
        self.cars_tree.bind('<Double-1>', lambda e: self.edit_car())

        cars_scroll = ttk.Scrollbar(cars_frame, orient='vertical', command=self.cars_tree.yview)
        cars_scroll.pack(side='right', fill='y')
        self.cars_tree.config(yscrollcommand=cars_scroll.set)

        ttk.Label(content, text="Двойной клик по машине — изменить её данные",
                  font=(styles.DEFAULT_FONT, 9), foreground='#64748b').pack(anchor='w', pady=(3, 12))

        # --- Рекомендации мастера -------------------------------------
        # Клиент видит их на чеке; здесь приёмщик может напомнить,
        # что советовали в прошлый раз
        styles.create_label(content, "Рекомендации мастера",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))

        self.recommendations_text = tk.Text(
            content, height=4, font=(styles.DEFAULT_FONT, 9), wrap='word',
            bg=styles.COLORS['bg_subtle'], fg=styles.COLORS['text'],
            relief='flat', highlightthickness=1,
            highlightbackground=styles.COLORS['border'], padx=10, pady=8)
        self.recommendations_text.pack(fill='x', pady=(0, 14))
        self.recommendations_text.config(state='disabled')

        # --- История визитов ------------------------------------------
        styles.create_label(content, "История визитов", 'CardHeading.TLabel').pack(anchor='w', pady=(0, 5))

        orders_frame = ttk.Frame(content, style='White.TFrame')
        orders_frame.pack(fill='both', expand=True)

        self.orders_tree = ttk.Treeview(
            orders_frame, columns=('Дата', 'Наряд', 'Машина', 'Услуг', 'Сумма'),
            show='headings')
        for column, title, width in (('Дата', 'Дата', 150), ('Наряд', 'Наряд №', 90),
                                     ('Машина', 'Автомобиль', 160), ('Услуг', 'Услуг', 90),
                                     ('Сумма', 'Сумма', 120)):
            self.orders_tree.heading(column, text=title)
            self.orders_tree.column(column, width=width, anchor='w')
        self.orders_tree.pack(side='left', fill='both', expand=True)

        orders_scroll = ttk.Scrollbar(orders_frame, orient='vertical',
                                      command=self.orders_tree.yview)
        orders_scroll.pack(side='right', fill='y')
        self.orders_tree.config(yscrollcommand=orders_scroll.set)

        styles.create_button(content, "Закрыть", self.dialog.destroy,
                             'Secondary.TButton').pack(fill='x', pady=(12, 0))

        self.refresh()

    # ------------------------------------------------------------------

    def get_client(self):
        return self.db.query(Client).filter(Client.id == self.client_id).first()

    def refresh(self):
        """Перечитать всё из базы и показать."""
        try:
            client = self.get_client()
            if not client:
                messagebox.showerror("Ошибка", "Клиент не найден", parent=self.dialog)
                self.dialog.destroy()
                return

            self.name_entry.delete(0, tk.END)
            self.name_entry.insert(0, client.name or '')
            self.phone_entry.delete(0, tk.END)
            self.phone_entry.insert(0, format_phone(client.phone) if client.phone else '')

            summary = self.client_service.get_client_summary(self.client_id)
            last = summary['last_visit'].strftime('%d.%m.%Y') if summary['last_visit'] else '—'
            self.summary_label.config(
                text=f"Визитов: {summary['visits']}  ·  "
                     f"На сумму: {summary['total_spent']:.0f} руб.  ·  "
                     f"Последний визит: {last}")

            for row in self.cars_tree.get_children():
                self.cars_tree.delete(row)
            for car in summary['cars']:
                self.cars_tree.insert('', 'end', values=(
                    car.license_plate,
                    VEHICLE_TYPES.get(car.vehicle_type, car.vehicle_type or '—'),
                    car.wheel_diameter or '—',
                    WHEELS_REVERSE.get(car.wheels_assembled, 'Не выяснено'),
                ), tags=(car.license_plate,))

            # История рекомендаций по всем машинам клиента
            self.recommendations_text.config(state='normal')
            self.recommendations_text.delete('1.0', 'end')
            history = self.client_service.get_client_recommendations(self.client_id)
            if history:
                for entry in history:
                    when = entry['date'].strftime('%d.%m.%Y') if entry['date'] else '—'
                    self.recommendations_text.insert(
                        'end', f"{when} · {entry['license_plate']}\n{entry['text']}\n\n")
            else:
                self.recommendations_text.insert('end', 'Рекомендаций пока нет')
            self.recommendations_text.config(state='disabled')

            for row in self.orders_tree.get_children():
                self.orders_tree.delete(row)
            for order in self.client_service.get_client_orders(self.client_id):
                if order.status != 'paid':
                    continue
                items = self.order_service.get_order_items(order.id)
                self.orders_tree.insert('', 'end', values=(
                    order.paid_at.strftime('%d.%m.%Y %H:%M') if order.paid_at else '—',
                    order.id,
                    order.car.license_plate if order.car else '—',
                    sum(i.quantity for i in items),
                    f"{order.total_amount or 0:.0f} руб.",
                ))
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось загрузить карточку: {e}",
                                 parent=self.dialog)

    def save_client(self):
        """Сохранить имя и телефон."""
        try:
            self.client_service.update_client(
                self.client_id,
                name=self.name_entry.get(),
                phone=self.phone_entry.get()
            )
            self.refresh()
            messagebox.showinfo("Готово", "Данные клиента сохранены", parent=self.dialog)
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e), parent=self.dialog)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}", parent=self.dialog)

    def selected_plate(self):
        selection = self.cars_tree.selection()
        if not selection:
            return None
        return self.cars_tree.item(selection[0])['values'][0]

    def add_car(self):
        """Добавить клиенту ещё один автомобиль."""
        plate = simpledialog.askstring(
            "Новый автомобиль", "Госномер:", parent=self.dialog)
        if not plate:
            return

        normalized = normalize_plate(plate)
        if not normalized:
            messagebox.showerror("Ошибка", "Номер не распознан", parent=self.dialog)
            return

        existing = self.client_service.get_car(normalized)
        if existing and existing.client_id and existing.client_id != self.client_id:
            owner = existing.client
            if not messagebox.askyesno(
                    "Автомобиль уже закреплён",
                    f"{normalized} закреплён за клиентом "
                    f"«{owner.name or 'без имени'}».\n\nПереписать на текущего клиента?",
                    parent=self.dialog):
                return

        try:
            self.client_service.attach_car(normalized, self.client_id)
            self.refresh()
            self.edit_car(plate=normalized)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось добавить: {e}", parent=self.dialog)

    def edit_car(self, plate=None):
        """Изменить данные автомобиля."""
        plate = plate or self.selected_plate()
        if not plate:
            messagebox.showinfo("Выбор", "Выберите автомобиль в списке", parent=self.dialog)
            return

        car = self.client_service.get_car(plate)
        if not car:
            return

        dialog = tk.Toplevel(self.dialog)
        dialog.title(f"Автомобиль {car.license_plate}")
        dialog.geometry("420x330")
        dialog.configure(bg=styles.COLORS['bg'])
        dialog.transient(self.dialog)
        dialog.grab_set()
        styles.center_window(dialog, self.dialog)

        body = ttk.Frame(dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=20, pady=20)

        styles.create_label(body, f"Автомобиль {car.license_plate}",
                            'CardHeading.TLabel').pack(anchor='w', pady=(0, 15))

        styles.create_label(body, "Госномер:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        plate_entry = styles.create_entry(body, width=30)
        plate_entry.insert(0, car.license_plate)
        plate_entry.pack(fill='x', pady=(0, 12))

        styles.create_label(body, "Тип транспорта:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        type_var = tk.StringVar(value=VEHICLE_TYPES.get(car.vehicle_type, 'Легковой'))
        ttk.Combobox(body, textvariable=type_var, values=list(VEHICLE_TYPES.values()),
                     font=styles.FONTS['normal'], state='readonly').pack(fill='x', pady=(0, 12))

        styles.create_label(body, "Диаметр:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        diameter_var = tk.StringVar(value=car.wheel_diameter or '')
        ttk.Combobox(body, textvariable=diameter_var, values=DIAMETERS,
                     font=styles.FONTS['normal'], state='readonly').pack(fill='x', pady=(0, 12))

        styles.create_label(body, "Колёса:", 'Card.TLabel').pack(anchor='w', pady=(0, 5))
        wheels_var = tk.StringVar(
            value=WHEELS_REVERSE.get(car.wheels_assembled, 'Не выяснено'))
        ttk.Combobox(body, textvariable=wheels_var, values=list(WHEELS.keys()),
                     font=styles.FONTS['normal'], state='readonly').pack(fill='x', pady=(0, 18))

        def save():
            try:
                self.client_service.update_car(
                    car.license_plate,
                    vehicle_type=VEHICLE_TYPES_REVERSE.get(type_var.get(), 'car'),
                    wheel_diameter=diameter_var.get() or None,
                    wheels_assembled=WHEELS.get(wheels_var.get()),
                    new_plate=plate_entry.get()
                )
                dialog.destroy()
                self.refresh()
            except ValueError as e:
                messagebox.showerror("Ошибка", str(e), parent=dialog)
            except Exception as e:
                self.db.rollback()
                messagebox.showerror("Ошибка", f"Не удалось сохранить: {e}", parent=dialog)

        styles.create_button(body, "Сохранить", save, 'Primary.TButton').pack(fill='x')

    def detach_car(self):
        """Открепить машину от клиента, сохранив её и всю историю."""
        plate = self.selected_plate()
        if not plate:
            messagebox.showinfo("Выбор", "Выберите автомобиль в списке", parent=self.dialog)
            return

        if not messagebox.askyesno(
                "Открепить автомобиль",
                f"Открепить {plate} от этого клиента?\n\n"
                f"Автомобиль и вся история нарядов останутся в базе.",
                parent=self.dialog):
            return

        try:
            self.client_service.detach_car(plate)
            self.refresh()
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось открепить: {e}", parent=self.dialog)

    def delete_car(self):
        """Удалить машину совсем — только если по ней не было нарядов."""
        plate = self.selected_plate()
        if not plate:
            messagebox.showinfo("Выбор", "Выберите автомобиль в списке", parent=self.dialog)
            return

        orders = self.client_service.count_car_orders(plate)
        if orders:
            messagebox.showwarning(
                "Удалить нельзя",
                f"По автомобилю {plate} есть наряды ({orders}).\n\n"
                f"Удаление стёрло бы историю обслуживания. "
                f"Если машина больше не принадлежит клиенту — открепите её.",
                parent=self.dialog)
            return

        if not messagebox.askyesno(
                "Удаление автомобиля",
                f"Удалить {plate} из базы?\n\nНарядов по нему не было.",
                parent=self.dialog):
            return

        try:
            self.client_service.delete_car(plate)
            self.refresh()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e), parent=self.dialog)
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось удалить: {e}", parent=self.dialog)
