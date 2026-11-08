"""
Экраны магазина (решение владельца 08.11.2026): кнопка «Магазин» сверху,
каталог карточек, продажа без машины, «+ Товар из магазина» в наряде и
блок «Магазин» в нём.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('shop_ui')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from services import OrderService, EmployeeService, directions
from services.shift_service import ShiftService
from services.shop_service import ShopService

init_db()
initialize_data()
db = SessionLocal()
ShiftService(db).open_shift(open_posts=2)
EmployeeService(db).register_employee(1, name='Олег')
EmployeeService(db).start_shift(1)
db.close()

import tkinter as tk
import ui.shop_tab as shop_module
shown = _setup.silence_dialogs(shop_module)
shop_module.os.startfile = lambda *a, **k: None
from ui import MainWindow

root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
db = app.db


def texts(widget, acc=None):
    acc = [] if acc is None else acc
    try:
        value = widget.cget('text')
        if value:
            acc.append(str(value))
    except Exception:
        pass
    for child in widget.winfo_children():
        texts(child, acc)
    return acc


print('=== Выключен — не видно ===')
check('кнопки «Магазин» сверху нет', 'Магазин' not in texts(app.mode_switch))

print('\n=== Включили ===')
directions.set_shop_on(db, True)
root.update()
check('сверху «Шиномонтаж | Магазин»', texts(app.mode_switch) == ['Шиномонтаж', 'Магазин'],
      str(texts(app.mode_switch)))
shop = ShopService(db)
scent = shop.save_card(name='Ароматизатор', category='Ароматизаторы', price=150, quantity=5)
shop.save_card(name='Коврики', category='Коврики', price=1900, quantity=1)
app.set_mode(directions.SHOP)
root.update()
tab = app.shop_tab
check('кнопка «Магазин» подсвечена', app._in_shop)
check('карточки нарисованы', len(tab.grid.winfo_children()) == 2, str(len(tab.grid.winfo_children())))
check('категории фильтром', 'Ароматизаторы' in texts(tab.chips) and 'Коврики' in texts(tab.chips))
tab._pick_category('Коврики')
check('фильтр по категории', len(tab.grid.winfo_children()) == 1)
tab._pick_category(None)

print('\n=== Продажа без машины ===')
tab.add(scent)
tab.add(scent)
check('в продаже 2 шт на 300', tab.total.cget('text') == 'Итого: 300 ₽', tab.total.cget('text'))
check('продавец — тот, кто на смене', tab.seller.get().startswith('Олег'))
shop_module.ask_payment = lambda parent, total: ('card', None)
tab.sell()
db.expire_all()
db.refresh(scent)
check('пробито, остаток 5 − 2', scent.quantity == 3, str(scent.quantity))
check('продажа очищена', not tab.basket)

print('\n=== В наряд ===')
orders = OrderService(db)
order = orders.create_order('А123ВВ777', 'R16', 'car', create_client=False)
app.orders_tab.open_order_tab(order)
root.update()
widget = app.orders_tab.active_orders[order.id]
check('в наряде «+ Товар из магазина»', '+ Товар из магазина' in texts(widget.blocks_holder))
picker = shop_module.ShopPicker(widget.frame, db, order, on_added=widget._after_shop)
picker.tree.selection_set(str(scent.id))
picker.qty.set(2)
picker.add()
root.update()
check('появился блок «МАГАЗИН», развёрнутый', 'МАГАЗИН' in texts(widget.blocks_holder)
      and not widget._is_collapsed('shop', ['tire', 'shop']), str(texts(widget.blocks_holder))[:300])
rows = [widget.trees['shop'].item(r)['values'] for r in widget.trees['shop'].get_children()]
check('строка товара, продал — Олег', rows and rows[0][0] == 'Ароматизатор' and rows[0][1] == 2
      and str(rows[0][5]).startswith('Олег'), str(rows))

root.destroy()
finish()
