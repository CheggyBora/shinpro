"""
Экраны зарплаты по правилам владельца 09.11.2026.

  · «Создать нового сотрудника»: галочка «Администратор» открывает поле
    «% от выручки», без процента не заводим;
  · Категории мастеров: у администратора — услуги шиномонтажа и мойки и
    «с товаров» отдельно; у мастерских категорий — только шиномонтаж;
  · наряд: «Мойщики ▾» в блоке мойки, в строках — оба мойщика;
  · магазин в наряде: колонка «Продал» — только при проценте с продаж.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('salary_ui')
shown = _setup.silence_dialogs()

import tkinter as tk
from config import init_db, SessionLocal
from init_data import initialize_data
from models import Employee, Service
from services import EmployeeService, OrderService, directions
from services.employee_role_service import EmployeeRoleService
from services.shift_service import ShiftService
from services.shop_service import ShopService

init_db()
initialize_data()
db = SessionLocal()
directions.set_enabled(db, True, True)
ShiftService(db).open_shift(open_posts=2)
staff = EmployeeService(db)
staff.register_employee(1, name='Анна')
staff.register_employee(2, name='Мария')
staff.start_shift(1)
staff.start_shift(2)

root = tk.Tk()
root.geometry('1400x860')
from ui import MainWindow
app = MainWindow(root)
root.update()
# Дальше — сессией окна: наряды открываются в ней
db = app.db

print('=== Создать нового сотрудника: администратор ===')
tab = app.employees_tab
check('поля процента сначала нет', tab.new_admin_percent.winfo_manager() == '')
tab.new_admin_var.set(True)
tab._admin_toggled()
check('галочка — поле «% от выручки»', tab.new_admin_percent.winfo_manager() == 'pack')
check('категория — «Администратор», выбрать другую нельзя',
      tab.employee_role_box.get() == 'Администратор' and tab.employee_role_box.instate(['disabled']))
tab.employee_id_entry.insert(0, '9')
tab.employee_name_entry.insert(0, 'Ольга')
tab.register_employee()
check('без процента — не заводим', db.query(Employee).get(9) is None, str(shown[-1:]))
tab.new_admin_percent.insert(0, '5,5')
tab.register_employee()
db.expire_all()
olga = db.query(Employee).get(9)
check('заведена администратором, 5,5% от выручки', olga is not None and olga.admin_percent == 5.5
      and EmployeeRoleService(db).is_admin(olga), str(olga and olga.admin_percent))
check('после — галочка снята, категория снова выбирается',
      not tab.new_admin_var.get() and not tab.employee_role_box.instate(['disabled']))

print('\n=== Категории мастеров ===')
from ui.employee_roles_editor import EmployeeRolesEditor
window = tk.Toplevel(root)
editor = EmployeeRolesEditor(window, db, window)
roles = EmployeeRoleService(db)
admin_role = next(r for r in roles.roles() if r.is_admin)
master_role = next(r for r in roles.roles() if r.title == 'Мастер')
wash_names = set(roles.service_names('wash'))
editor.role_id = master_role.id
editor.draw_services()
check('у мастера — только шиномонтаж', wash_names and not (set(editor.checks) & wash_names))
editor.role_id = admin_role.id
editor.draw_services()
check('у администратора — и мойка', wash_names <= set(editor.checks))
editor.checks['Мойка кузова, 2 фазы'].set(True)
editor.save()
db.expire_all()
role = roles.get(admin_role.id)
check('сохранилось: мойка кузова администратору не начисляется',
      'Мойка кузова, 2 фазы' in role.excluded)
window.destroy()

print('\n=== Наряд: мойщики машины ===')
orders = OrderService(db)
order = orders.create_order('А100АА77', 'R16', 'car', create_client=False)
orders.add_direction(order.id, 'wash', wash_class='sedan')
wash = db.query(Service).filter(Service.direction == 'wash').first()
orders.add_service_to_order(order.id, wash.id)
app.orders_tab.open_order_tab(order)
root.update()
widget = app.orders_tab.active_orders[order.id]


def texts(widget_):
    found = []
    for child in widget_.winfo_children():
        try:
            found.append(child.cget('text'))
        except tk.TclError:
            pass
        found.extend(texts(child))
    return found


check('в блоке мойки «Мойщики: выбрать ▾»', 'Мойщики: выбрать ▾' in texts(widget.blocks_holder),
      str([t for t in texts(widget.blocks_holder) if 'Мой' in str(t)]))
orders.set_wash_masters(order.id, [1, 2])
widget.db.refresh(widget.order)
widget.render_blocks()
widget.refresh_items()
root.update()
check('в шапке — оба', any(str(t).startswith('Мойщики: Анна') and 'Мария' in str(t)
                           for t in texts(widget.blocks_holder)))
rows = [widget.trees['wash'].item(r)['values'] for r in widget.trees['wash'].get_children()]
check('в строке «Кто делал» — оба', rows and 'Анна' in str(rows[0][5]) and 'Мария' in str(rows[0][5]),
      str(rows))

print('\n=== Магазин в наряде: «Продал» только при проценте ===')
directions.set_shop_on(db, True)
card = ShopService(db).save_card(name='Ароматизатор', price=150, quantity=5)
orders.add_service_to_order(order.id, card.service_id)
widget.render_blocks()
widget.refresh_items()
root.update()
shop_tree = widget.trees['shop']
check('процент выключен — колонки «Продал» нет', 'Кто' not in shop_tree.cget('displaycolumns'),
      str(shop_tree.cget('displaycolumns')))
directions.set_shop_pay_on(db, True)
widget.render_blocks()
widget.refresh_items()
root.update()
check('процент включён — колонка «Продал» есть',
      widget.trees['shop'].cget('displaycolumns') in ('#all', ('#all',)) or
      'Кто' in widget.trees['shop'].cget('displaycolumns'),
      str(widget.trees['shop'].cget('displaycolumns')))

root.destroy()
finish()
