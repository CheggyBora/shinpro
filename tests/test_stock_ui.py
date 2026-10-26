"""
Окна склада открываются и работают (ui/stock_tab.py, ui/wash_prices.py).
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('stock_ui')
os.chdir(_setup.PROJECT_DIR)
_setup.silence_dialogs()

import tkinter as tk
import styles
from config import init_db, SessionLocal
from models import Service
from models.stock import GOODS, MATERIAL
from services import directions
from services.stock_service import StockService

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
stock = StockService(db)
stock.set_enabled(True)
directions.set_enabled(db, True, True)

root = tk.Tk()
root.withdraw()
styles.apply_modern_styles(root)

from ui.stock_tab import StockTab, ItemDialog, ReceiveDialog, RecipesDialog
tab = StockTab(root, db)
check('пустой склад открывается', tab.tree.get_children() == ())

dialog = ItemDialog(tab.frame, db, None, tab._changed)
dialog.direction.set('tire')
dialog.kind.set(MATERIAL)
for key, value in (('name', 'Грибок'), ('price', '50'), ('quantity', '1'), ('min_quantity', '2')):
    dialog.fields[key].delete(0, tk.END)
    dialog.fields[key].insert(0, value)
dialog.save()
check('позиция заведена из окна', len(tab.tree.get_children()) == 1)
item = stock.items()[0]
check('мало — жёлтым', tab.tree.item(str(item.id))['tags'] == ['low'])

receive = ReceiveDialog(tab.frame, db, item, tab._changed)
receive.amount.insert(0, '5')
receive.save()
db.refresh(item)
check('приход из окна', item.quantity == 6)

card = ItemDialog(tab.frame, db, item, tab._changed)
card.fields['price'].delete(0, tk.END)
card.fields['price'].insert(0, '60')
card.save()
db.refresh(item)
check('карточка сохраняет цену', item.price == 60)

recipes = RecipesDialog(tab.frame, db)
check('в расходе — услуги шиномонтажа', [s.name for s in recipes.services] == ['Шиномонтаж'])
recipes.services_box.selection_set(0)
recipes.load_recipe()
check('без расхода — 0 ₽', 'Итого расходник: 0' in recipes.total.cget('text'))
recipes.dialog.destroy()

tab.direction = 'wash'
tab.load()
check('фильтр «Мойка» прячет шиномонтаж', tab.tree.get_children() == ())
tab.direction, tab.kind = None, GOODS
tab.load()
check('фильтр «Товары»', tab.tree.get_children() == ())

from ui.wash_prices import WashPrices
prices = WashPrices(root, db)
stock.save_item(None, direction='wash', kind=GOODS, name='Ароматизатор', price=300)
prices.load()
rows = [prices.tree.item(r)['values'] for r in prices.tree.get_children()]
goods = [r for r in rows if 'товар' in str(r[0])]
check('товар мойки в прайсе с одной ценой', goods and set(goods[0][1:]) == {300})
prices.dialog.destroy()

root.destroy()
db.close()
finish()
