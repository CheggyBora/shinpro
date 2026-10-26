"""
Позиции наряда: добавление услуг, количество, цена, скидки.

Всё, что меняет состав наряда и его строки, собрано здесь: правка
количества и цены прямо в таблице, скидка на позицию, удаление строки
и перерисовка списка.
"""
import tkinter as tk
from tkinter import messagebox, simpledialog

from services import OrderService
from services.wheel_service import WheelSettings, item_title
from services.wheel_service import parse as parse_wheels
from utils import retry_after_rollback
from ui import wheel_picker

class OrderItemsMixin:
    """Работа со списком услуг наряда."""

    def add_service_by_name(self, service_name):
        from models import Service
        vehicle_type = self.order.vehicle_type

        def find_service():
            # Сначала ищем услугу для этого типа транспорта,
            # затем общую для всех типов
            found = self.db.query(Service).filter(
                Service.name == service_name,
                Service.vehicle_type == vehicle_type
            ).first()
            if not found:
                found = self.db.query(Service).filter(
                    Service.name == service_name,
                    Service.vehicle_type == 'all'
                ).first()
            return found

        try:
            service = retry_after_rollback(self.db, find_service)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка добавления услуги: {str(e)}")
            return

        if service:
            self.add_service(service)
        else:
            messagebox.showerror("Ошибка", f"Услуга '{service_name}' не найдена")

    def add_service(self, service):
        # Ремонт и правка: сначала — на каком колесе. «Пропустить» —
        # добавить без колеса, «Отмена» — не добавлять: пробили по ошибке
        wheels = None
        try:
            asks = retry_after_rollback(
                self.db, lambda: WheelSettings(self.db).asks(service.name))
        except Exception:
            asks = False
        if asks:
            already = []
            for item in self.order_service.get_order_items(self.order.id):
                if item.service_id == service.id:
                    already = parse_wheels(item.wheels)
            wheels = wheel_picker.pick_wheels(
                self.frame, self.order.vehicle_type, service.name,
                already=already)
            if wheels is None:
                return

        def add():
            self.order_service.add_service_to_order(self.order.id, service.id,
                                                    wheels=wheels)
            self.refresh_items()

        try:
            retry_after_rollback(self.db, add)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def on_double_click(self, event):
        # Определяем на какую колонку кликнули
        region = self.items_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        column = self.items_tree.identify_column(event.x)
        selected = self.items_tree.selection()
        if not selected:
            return
        
        # Название (#1) у ремонта и правки — переотметить колёса.
        # Редактируем "Кол-во" (#2), "Цена" (#3) или "Скидка %" (#4)
        if column == '#1':
            self.edit_wheels(selected[0])
        elif column == '#2':
            self.edit_quantity_inline(selected[0], event)
        elif column == '#3':
            self.edit_price_inline(selected[0], event)
        elif column == '#4':
            self.edit_discount(selected[0])
        elif column == '#6':
            item_id = int(self.items_tree.item(selected[0])['tags'][0])
            item = next((i for i in self.order_service.get_order_items(self.order.id)
                         if i.id == item_id), None)
            if item is not None:
                self.choose_item_employee(item)

    def edit_wheels(self, item_id_str):
        """Ошиблись колесом — двойной клик по названию и отметить заново."""
        from models import WorkOrderItem

        item_id = int(self.items_tree.item(item_id_str)['tags'][0])
        item = self.db.query(WorkOrderItem).filter(
            WorkOrderItem.id == item_id).first()
        if item is None or item.service is None:
            return
        if not item.wheels and not WheelSettings(self.db).asks(item.service.name):
            return

        wheels = wheel_picker.pick_wheels(
            self.frame, self.order.vehicle_type, item.service.name,
            initial=parse_wheels(item.wheels))
        if wheels is None:
            return
        try:
            self.order_service.set_item_wheels(item_id, wheels)
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        self.refresh_items()

    def edit_quantity_inline(self, item_id_str, event):
        # Получаем данные позиции
        item_id = int(self.items_tree.item(item_id_str)['tags'][0])
        item = next((i for i in self.order_service.get_order_items(self.order.id) if i.id == item_id), None)
        
        if not item:
            return
        
        # Удаляем предыдущий Entry если он есть
        if self.edit_entry:
            self.edit_entry.destroy()
            self.edit_entry = None
        
        # Получаем координаты ячейки
        x, y, width, height = self.items_tree.bbox(item_id_str, 'Кол-во')
        
        # Создаём Entry поверх ячейки
        self.edit_entry = tk.Entry(self.items_tree, justify='center')
        self.edit_entry.place(x=x, y=y, width=width, height=height)
        self.edit_entry.insert(0, str(item.quantity))
        self.edit_entry.select_range(0, tk.END)
        self.edit_entry.focus_set()
        
        def save_inline(event=None):
            try:
                quantity = int(self.edit_entry.get())
                if quantity < 1:
                    messagebox.showerror("Ошибка", "Количество должно быть больше 0")
                    return
                
                # Сохраняем все остальные поля без изменений
                self.order_service.update_item_full(
                    item_id, 
                    quantity, 
                    item.price, 
                    item.discount_percent, 
                    item.comment or ""
                )
                self.refresh_items()
                
                if self.edit_entry:
                    self.edit_entry.destroy()
                    self.edit_entry = None
            except ValueError:
                messagebox.showerror("Ошибка", "Введите число")
        
        def cancel_inline(event=None):
            if self.edit_entry:
                self.edit_entry.destroy()
                self.edit_entry = None
        
        # Горячие клавиши
        self.edit_entry.bind('<Return>', save_inline)
        self.edit_entry.bind('<KP_Enter>', save_inline)
        self.edit_entry.bind('<Escape>', cancel_inline)
        self.edit_entry.bind('<FocusOut>', save_inline)

    def edit_price_inline(self, item_id_str, event):
        # Получаем данные позиции
        item_id = int(self.items_tree.item(item_id_str)['tags'][0])
        item = next((i for i in self.order_service.get_order_items(self.order.id) if i.id == item_id), None)
        
        if not item:
            return
        
        # ПРОВЕРКА: редактировать можно только если editable_price = True
        service_name = item.service.name
        if not item.service.editable_price:
            messagebox.showwarning(
                "Редактирование недоступно", 
                f"Цену можно изменять только для специальных услуг.\n\n"
                f"Услуга '{service_name}' имеет фиксированную цену."
            )
            return
        
        # Диалоговое окно для редактирования цены (работает везде, включая Windows)
        from tkinter import simpledialog
        
        new_price = simpledialog.askfloat(
            "Изменение цены",
            f"Введите новую цену для '{service_name}':\n(текущая цена: {item.price:.2f} ₽)",
            initialvalue=item.price,
            minvalue=0.01,
            parent=self.frame
        )
        
        if new_price is not None and new_price > 0:
            try:
                # Сохраняем новую цену
                self.order_service.update_item_full(
                    item_id, 
                    item.quantity, 
                    new_price, 
                    item.discount_percent, 
                    item.comment or ""
                )
                self.refresh_items()
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось изменить цену: {str(e)}")

    def edit_discount(self, item_id_str):
        """
        Скидка по отдельной услуге: двойной клик по колонке «Скидка %».

        Вводить можно любое число от нуля до максимума, заданного для этой
        услуги. Выставленное вручную значение общая скидка на наряд
        больше не перезаписывает.
        """
        item_id = int(self.items_tree.item(item_id_str)['tags'][0])
        item = next((i for i in self.order_service.get_order_items(self.order.id)
                     if i.id == item_id), None)
        if not item:
            return

        limit = self.order_service.max_discount_for(item)
        if limit <= 0:
            messagebox.showinfo(
                "Скидка недоступна",
                f"Для услуги «{item.service.name}» скидка не предусмотрена.")
            return

        value = simpledialog.askinteger(
            "Скидка на услугу",
            f"«{item.service.name}»\n\n"
            f"Скидка в процентах (от 0 до {limit}):",
            initialvalue=item.discount_percent or 0,
            minvalue=0, maxvalue=limit,
            parent=self.frame
        )
        if value is None:
            return

        try:
            self.order_service.set_item_discount(item_id, value)
            self.refresh_items()
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
        except Exception as e:
            self.db.rollback()
            messagebox.showerror("Ошибка", f"Не удалось изменить скидку: {e}")

    def delete_item(self, event):
        selected = self.items_tree.selection()
        if not selected:
            return
        
        item_id = int(self.items_tree.item(selected[0])['tags'][0])
        self.order_service.delete_item(item_id)
        self.refresh_items()

    def apply_rim_discount(self):
        discount = int(self.rim_discount_var.get())
        self.order_service.update_rim_discount(self.order.id, discount)
        self.db.refresh(self.order)
        self.refresh_items()

    def apply_general_discount(self):
        discount = int(self.general_discount_var.get())
        self.order_service.update_general_discount(self.order.id, discount)
        self.db.refresh(self.order)
        self.refresh_items()

    def refresh_items(self):
        def reload():
            loaded = self.order_service.get_order_items(self.order.id)
            self.db.refresh(self.order)
            return loaded

        items = retry_after_rollback(self.db, reload)

        # Направления наряда поменялись — сначала перестроить блоки
        from services import directions as _directions
        trees = getattr(self, 'trees', None) or {'tire': self.items_tree}
        if hasattr(self, 'render_blocks') and \
                _directions.parse(self.order.directions) != getattr(self, '_rendered_directions', None):
            self.render_blocks()
            trees = self.trees
        for tree in trees.values():
            for row in tree.get_children():
                tree.delete(row)

        # Обновляем значения в комбобоксах
        self.rim_discount_var.set(str(self.order.rim_discount))
        self.general_discount_var.set(str(self.order.general_discount))
        
        # Отображаем позиции
        # Считаем теми же функциями, что касса и чек, — числа на экране
        # и в распечатанном чеке всегда совпадают
        total_without_discount = 0
        for item in items:
            total_without_discount += OrderService.item_total_without_discount(item)
            item_total = OrderService.item_total(item)

            # Скидка позиции. Звёздочка означает, что её задали вручную
            # и общая скидка на наряд её не перезапишет
            discount_display = f"{item.discount_percent}%"
            if item.discount_manual:
                discount_display += " *"

            who = ''
            from services import directions as _directions
            if _directions.assigned(self.db, getattr(item, 'direction', None) or 'tire'):
                from ui.order_screen.directions import employee_name
                who = employee_name(self.db, item.employee_id) if item.employee_id else 'выбрать ▾'
            tree = trees.get(getattr(item, 'direction', None) or 'tire') or next(iter(trees.values()))
            tree.insert('', 'end', values=(
                item_title(item),
                item.quantity,
                f"{item.price:.2f}",
                discount_display,
                f"{item_total:.2f}",
                who
            ), tags=(str(item.id),))
        
        if hasattr(self, 'refresh_block_summaries'):
            self.refresh_block_summaries(items)

        total_with_discount = self.order_service.calculate_total(self.order.id)
        
        # Обновляем лейблы с ценами
        self.price_label.config(text=f"{total_without_discount:.2f} руб.")
        
        if total_with_discount < total_without_discount:
            self.discount_price_label.config(text=f"{total_with_discount:.2f} руб. со скидкой")
        else:
            self.discount_price_label.config(text="")

        # Расходники показываем, только если они есть: пока себестоимости
        # не заполнены, строка не мозолит глаза
        consumables = self.order_service.calculate_consumables(self.order.id)
        if consumables > 0:
            base = self.order_service.calculate_salary_base(self.order.id)
            self.salary_base_label.config(
                text=f"Расходники: {consumables:.0f} руб.  ·  База для ЗП: {base:.0f} руб."
            )
        else:
            self.salary_base_label.config(text="")

        self.refresh_time_display()
        
        # Обновляем список сотрудников
        self.update_employees_display()
