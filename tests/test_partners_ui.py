"""
Работы у партнёров — экраны (решения владельца 13.11.2026).

  · «+ Работа у партнёра» в наряде: партнёр, его услуга подставляет цены
    и начисление; в наряде свой блок, в нём только наша цена и статус;
  · карточка работы: цена партнёра → в работе → партнёр сделал → оплатить;
  · касса → «Оплата партнёрам»: что ждёт оплаты, оплатить отмеченные;
  · контрагент: его услуги; покраска: «Через партнёра».
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('partners_ui')
shown = _setup.silence_dialogs()

import tkinter as tk
from config import init_db, SessionLocal
from init_data import initialize_data
from models import Service
from models.cash import CashOrder
from services import EmployeeService, OrderService
from services.calendar_service import CalendarService
from services import partner_service as ps
from services.shift_service import ShiftService

init_db()
initialize_data()
db = SessionLocal()
ShiftService(db).open_shift(open_posts=2, cash_start=5000)
staff = EmployeeService(db)
staff.register_employee(1, name='Иван')
staff.start_shift(1)
party = CalendarService(db).save_counterparty(name='Сварка Плюс', kind='сварка дисков')
ps.PartnerService(db).save_offering(counterparty_uid=party.uid, name='Сварка диска', our_price=3500,
                                    partner_price=2000, salary_to=ps.SAL_CREATOR,
                                    salary_mode=ps.MODE_MARGIN_PCT, salary_value=10)

root = tk.Tk()
root.geometry('1400x860')
from ui import MainWindow
app = MainWindow(root)
root.update()
db = app.db


def texts(widget_):
    found = []
    for child in widget_.winfo_children():
        try:
            found.append(child.cget('text'))
        except tk.TclError:
            pass
        found.extend(texts(child))
    return found


print('=== Наряд: «+ Работа у партнёра» ===')
orders = OrderService(db)
mount = db.query(Service).filter(Service.name == 'Шиномонтаж', Service.vehicle_type == 'car').first()
order = orders.create_order('А123ВВ777', 'R16', 'car', create_client=False)
orders.add_service_to_order(order.id, mount.id)
app.orders_tab.open_order_tab(order)
root.update()
widget = app.orders_tab.active_orders[order.id]
check('в наряде кнопка «+ Работа у партнёра»', '+ Работа у партнёра' in texts(widget.blocks_holder))

from ui.partner_ui import JobDialog, JobCard, PayDialog, PartnersWindow
dialog = JobDialog(widget.frame, db, order=widget.order, on_saved=lambda t: widget._after_shop())
dialog.party.current(0)
dialog._party_changed()
check('у партнёра — его услуга', list(dialog.offer.cget('values')) == ['Сварка диска'])
dialog.offer.set('Сварка диска')
dialog._offer_changed()
check('цены подставились: 3500 и 2000', dialog.our.get() == '3500' and dialog.theirs.get() == '2000')
check('начисление подставилось: оформившему, % от маржи, 10',
      dialog.salary.to.get() == ps.SAL_CREATOR and dialog.salary.value.get() == '10')
dialog.creator.set(dialog.people[0].title)
dialog.save()
root.update()
job = dialog.task
check('оформлено — сразу в работе (цену партнёра знали)', job.partner_status == ps.ST_WORK)
check('в наряде блок «РАБОТЫ У ПАРТНЁРОВ»', 'РАБОТЫ У ПАРТНЁРОВ' in texts(widget.blocks_holder))
rows = [widget.trees['partner'].item(r)['values'] for r in widget.trees['partner'].get_children()]
check('в строке — наша цена и статус, цены партнёра нет',
      rows and rows[0][0] == 'Сварка диска' and rows[0][4] == '3500.00'
      and rows[0][5] == 'В работе у партнёра' and '2000' not in str(rows), str(rows))
tire_rows = [widget.trees['tire'].item(r)['values'] for r in widget.trees['tire'].get_children()]
check('в шиномонтаже работы партнёра нет', all('Сварка' not in str(r) for r in tire_rows))

print('\n=== Карточка работы ===')
card = JobCard(widget.frame, db, job, on_change=widget._after_shop)
check('кнопка «Партнёр сделал»', 'Партнёр сделал' in texts(card.body))
card.act(lambda: card.service.finish(job))
check('после — «Оплатить партнёру…»', 'Оплатить партнёру…' in texts(card.body)
      and job.partner_status == ps.ST_WAIT)
pay = PayDialog(card.dialog, db, [job], on_paid=card.changed)
pay.method.set(ps.PAY_CASH)
pay.save()
check('оплачено наличными — РКО «Партнёры» 2000', job.partner_status == ps.ST_PAID and db.query(
    CashOrder).filter(CashOrder.category == 'Партнёры', CashOrder.amount == 2000).count() == 1)
card.dialog.destroy()

print('\n=== Касса → «Оплата партнёрам» ===')
job2 = ps.PartnerService(db).create_job(party.uid, 'Сварка R18', 4000, partner_price=2500)
ps.PartnerService(db).finish(job2)
window = PartnersWindow(root, db)
check('ждёт оплаты: 2500', 'Оплата партнёрам: 2 500 ₽' in texts(window.dialog), str(texts(window.dialog))[:300])
check('в списке одна работа', len(window.tree.get_children()) == 1)
window.only_wait.set(False)
window.fill()
check('все работы — две', len(window.tree.get_children()) == 2)
window.dialog.destroy()

print('\n=== Контрагент: его услуги ===')
from ui.counterparties_editor import CounterpartiesEditor
holder = tk.Toplevel(root)
editor = CounterpartiesEditor(holder, db, holder)
editor.listbox.selection_set(0)
editor._chosen()
check('в карточке контрагента — его услуга', len(editor.offerings.get_children()) == 1)
holder.destroy()

print('\n=== Покраска через партнёра ===')
import ui.partner_ui as partner_ui
opened = []
real = partner_ui.JobDialog
partner_ui.JobDialog = lambda *a, **k: opened.append(k)
app.paint_tab.diameter.set(17)
app.paint_tab.wheels.set(4)
app.paint_tab.recalc()
app.paint_tab.via_partner()
partner_ui.JobDialog = real
check('открыта работа «покраска» с ценой калькулятора',
      opened and opened[0]['kind'] == ps.KIND_PAINT and opened[0]['our_price'] > 0, str(opened))

root.destroy()
finish()
