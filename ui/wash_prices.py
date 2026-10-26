"""
Прайс мойки: услуги и цены по классу машины (services/directions.py).

Открывается из «Прайс-листа» кнопкой «Мойка», когда мойка включена.
Цена правится двойным щелчком и сохраняется сразу — с записью в журнал
действий, как и правка цен шиномонтажа.
"""
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import styles
from models import Service
from services import directions


class WashPrices:
    def __init__(self, parent, db):
        self.db = db
        self.dialog = tk.Toplevel(parent)
        self.dialog.title('Прайс мойки')
        self.dialog.geometry('760x520')
        self.dialog.configure(bg=styles.COLORS['bg_card'])
        self.dialog.transient(parent.winfo_toplevel())
        body = ttk.Frame(self.dialog, style='White.TFrame')
        body.pack(fill='both', expand=True, padx=16, pady=14)
        styles.create_label(body, 'Прайс мойки', 'CardHeading.TLabel').pack(anchor='w')
        ttk.Label(body, text='Цена — по классу машины. Двойной щелчок по цене — изменить.',
                  font=styles.FONTS['small'], foreground=styles.COLORS['text_secondary'],
                  background=styles.COLORS['bg_card']).pack(anchor='w', pady=(2, 10))

        columns = ['Услуга'] + [directions.WASH_CLASS_TITLES[c] for c in directions.WASH_CLASSES]
        self.tree = ttk.Treeview(body, columns=columns, show='headings', height=14)
        self.tree.heading('Услуга', text='Услуга')
        self.tree.column('Услуга', width=260, anchor='w')
        for title in columns[1:]:
            self.tree.heading(title, text=title)
            self.tree.column(title, width=100, anchor='center')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<Double-1>', self.edit_price)

        buttons = ttk.Frame(body, style='White.TFrame')
        buttons.pack(fill='x', pady=(10, 0))
        for text, command in (('+ Услуга', self.add), ('Переименовать', self.rename),
                              ('Убрать', self.remove)):
            styles.create_button(buttons, text, command, 'Secondary.TButton').pack(side='left', padx=(0, 6))
        styles.create_button(buttons, 'Закрыть', self.dialog.destroy,
                             'Secondary.TButton').pack(side='right')
        self.load()
        styles.center_window(self.dialog, parent.winfo_toplevel())

    def services(self):
        return self.db.query(Service).filter(
            Service.direction == directions.WASH,
            Service.is_active.isnot(False)).order_by(Service.name).all()

    def load(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for service in self.services():
            values = [service.name] + [f'{getattr(service, f"price_{c}") or 0:.0f}'
                                       for c in directions.WASH_CLASSES]
            self.tree.insert('', 'end', values=values, tags=(str(service.id),))

    def _selected(self):
        chosen = self.tree.selection()
        if not chosen:
            messagebox.showinfo('Прайс мойки', 'Выберите услугу', parent=self.dialog)
            return None
        service_id = int(self.tree.item(chosen[0])['tags'][0])
        return self.db.query(Service).filter(Service.id == service_id).first()

    def _log(self, text):
        try:
            from services.audit_service import AuditService
            AuditService(self.db).log(AuditService.PRICE_CHANGE, text, entity_type='service')
        except Exception:
            self.db.rollback()

    def edit_price(self, event):
        row = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if not row or column == '#1':
            return
        self.tree.selection_set(row)
        service = self._selected()
        wash_class = directions.WASH_CLASSES[int(column[1:]) - 2]
        current = getattr(service, f'price_{wash_class}') or 0
        value = simpledialog.askfloat(
            'Цена', f'{service.name}, {directions.class_title(wash_class).lower()}:',
            initialvalue=current, minvalue=0, parent=self.dialog)
        if value is None:
            return
        setattr(service, f'price_{wash_class}', value)
        self.db.commit()
        self._log(f'Мойка «{service.name}», {directions.class_title(wash_class)}: '
                  f'{current:.0f} → {value:.0f} ₽')
        self.load()

    def add(self):
        name = simpledialog.askstring('Новая услуга мойки', 'Название:', parent=self.dialog)
        name = (name or '').strip()
        if not name:
            return
        if self.db.query(Service).filter(Service.name == name, Service.direction == directions.WASH,
                                         Service.is_active.isnot(False)).first():
            messagebox.showerror('Прайс мойки', 'Такая услуга уже есть', parent=self.dialog)
            return
        self.db.add(Service(name=name, vehicle_type='all', direction=directions.WASH, is_active=True))
        self.db.commit()
        self._log(f'Мойка: добавлена услуга «{name}»')
        self.load()

    def rename(self):
        service = self._selected()
        if service is None:
            return
        name = simpledialog.askstring('Переименовать', 'Новое название:',
                                      initialvalue=service.name, parent=self.dialog)
        name = (name or '').strip()
        if not name or name == service.name:
            return
        old = service.name
        service.name = name
        self.db.commit()
        self._log(f'Мойка: «{old}» → «{name}»')
        self.load()

    def remove(self):
        service = self._selected()
        if service is None:
            return
        if not messagebox.askyesno('Прайс мойки', f'Убрать «{service.name}» из прайса?',
                                   parent=self.dialog):
            return
        # Не удаляем: по ней могут быть закрытые наряды
        service.is_active = False
        self.db.commit()
        self._log(f'Мойка: убрана услуга «{service.name}»')
        self.load()
