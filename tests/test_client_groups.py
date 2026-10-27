"""
Группы клиентов: кому предлагать допы, а с кем лучше не говорить.

Это мнение цеха о человеке. Проверяем то, из-за чего им нельзя будет
пользоваться:

  · группы по умолчанию 11…55 заводятся один раз, удалённые не
    возвращаются при следующем запуске;
  · группы настраиваются, коды не повторяются;
  · удалили группу — клиенты остаются без группы, а не уезжают в
    соседнюю: 44 и 55 значат разное;
  · группа никогда не уходит на сервер — ни кодом, ни названием;
  · значок в наряде одинаковый у всех, пока его не нажмёшь.
"""
import _setup
from _setup import use_temp_db, check, finish

import json
import os

use_temp_db('client_groups')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from init_data import initialize_data
from models import Client, ClientGroup
from services import OrderService, EmployeeService
from services.shift_service import ShiftService
from services.client_group_service import ClientGroupService

init_db()
initialize_data()

db = SessionLocal()
groups = ClientGroupService(db)

print('=== Группы по умолчанию ===')
codes = [g.code for g in groups.groups()]
check('пять групп от 11 до 55', codes == ['11', '22', '33', '44', '55'],
      str(codes))
first = groups.groups()[0]
check('11 — очень лояльный', first.title == 'Очень лояльный', first.title)
check('у группы есть подсказка, как говорить', bool(first.hint))
check('повторный вызов не плодит дублей',
      len(groups.groups()) == 5, str(len(groups.groups())))

print()
print('=== Своя группа и порядок ===')
nine = groups.add('9', 'Свой человек', 'Можно по-простому')
codes = [g.code for g in groups.groups()]
check('«9» стоит раньше «11», как число', codes[0] == '9', str(codes))

try:
    groups.add('11', 'Двойник')
    check('повтор кода не пускаем', False)
except ValueError as e:
    check('повтор кода не пускаем', 'уже есть' in str(e), str(e))

try:
    groups.add('', 'Без кода')
    check('пустой код не пускаем', False)
except ValueError as e:
    check('пустой код не пускаем', True)

groups.update(nine.id, '99', 'Свой человек', '')
check('код поменяли', groups.get(nine.id).code == '99')
check('пустая подсказка хранится как пусто', groups.get(nine.id).hint is None)

print()
print('=== Ставим группу клиенту ===')
ShiftService(db).open_shift(open_posts=2)
EmployeeService(db).register_employee(1)
EmployeeService(db).start_shift(1)
order = OrderService(db).create_order(
    'А123ВВ777', 'R16', 'car', client_name='Андрей',
    client_phone='79099018931')
client_id = order.client_id

check('у нового клиента группы нет', groups.group_of(client_id) is None)

g55 = next(g for g in groups.groups() if g.code == '55')
g11 = next(g for g in groups.groups() if g.code == '11')
groups.set_group(client_id, g55.id)
check('поставили 55', groups.group_of(client_id).code == '55')
stamp = db.get(Client, client_id).group_set_at
check('запомнили, когда', stamp is not None)

groups.set_group(client_id, g11.id)
check('прав последний: теперь 11', groups.group_of(client_id).code == '11')

groups.set_group(client_id, None)
check('сняли — группы нет', groups.group_of(client_id) is None)
check('и даты нет', db.get(Client, client_id).group_set_at is None)

print()
print('=== Группа не уходит с компьютера цеха ===')
groups.set_group(client_id, g55.id)
from services.sync_service import SyncService

push = SyncService(db).collect_push()
sent = json.dumps(push, ensure_ascii=False, default=str)
pushed_client = next(c for c in push['clients'] if c['local_id'] == client_id)
check('у клиента на сервер только имя и телефон',
      set(pushed_client) == {'local_id', 'phone', 'name'},
      str(sorted(pushed_client)))
check('названия группы нет нигде в обмене', 'Негатив' not in sent)
check('подсказки тоже', g55.hint not in sent)
check('и слова group', 'group' not in sent.lower())

print()
print('=== Удалили группу — клиенты без группы ===')
check('в 55 один клиент', groups.count_clients(g55.id) == 1)
moved = groups.delete(g55.id)
check('освободили одного', moved == 1, str(moved))
db.expire_all()
check('клиент остался без группы', groups.group_of(client_id) is None)
check('группы 55 больше нет',
      '55' not in [g.code for g in groups.groups()])

print()
print('=== Удалённые группы не возвращаются ===')
for group in groups.groups():
    groups.delete(group.id)
db.close()
db = SessionLocal()
check('после «перезапуска» групп нет',
      ClientGroupService(db).groups() == [],
      str(ClientGroupService(db).groups()))
ClientGroupService(db).add('11', 'Очень лояльный')
ClientGroupService(db).add('55', 'Негатив', 'Ничего не предлагать')
db.close()

print()
print('=== Значок в наряде ===')
import tkinter as tk
import ui.orders_tab
import ui.client_group_badge as badge_module

_setup.silence_dialogs(ui.orders_tab, badge_module)
from ui import MainWindow

root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()

orders = app.orders_tab
ui_db = orders.db
other = OrderService(ui_db).create_order('К900ОР99', 'R16', 'car',
                                         client_phone='79161234567')
ui_groups = ClientGroupService(ui_db)
g55 = next(g for g in ui_groups.groups() if g.code == '55')
ui_groups.set_group(client_id, g55.id)

# Как в экране нового наряда: нашли клиента по номеру — передали его
found = ui_db.get(Client, client_id)
open_order = OrderService(ui_db).create_order('А123ВВ777', 'R16', 'car',
                                              client_id=found.id)
orders.open_order_tab(open_order)
orders.open_order_tab(other)
root.update()


def all_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from all_widgets(child)


def texts(widget):
    found = []
    for w in all_widgets(widget):
        try:
            found.append(str(w.cget('text')))
        except tk.TclError:
            pass
    return found


marked = orders.active_orders[open_order.id]
plain = orders.active_orders[other.id]
check('наряд того же клиента', open_order.client_id == client_id)

marked_texts = texts(marked.frame)
plain_texts = texts(plain.frame)
check('кнопка «⋯» в наряде есть', badge_module.BADGE_TEXT in marked_texts)
check('у клиента без группы — тоже', badge_module.BADGE_TEXT in plain_texts)
check('код группы виден сразу, без нажатия', '55' in marked_texts,
      str([t for t in marked_texts if '55' in t]))
check('у клиента без группы кода нет', '55' not in plain_texts and '11' not in plain_texts)
check('что код значит — на экране нет', not any('Негатив' in t for t in marked_texts))

print()
print('=== Нажали «⋯» — только коды, можно поменять ===')
button = next(w for w in all_widgets(marked.frame)
              if isinstance(w, tk.ttk.Button)
              and w.cget('text') == badge_module.BADGE_TEXT)
button.invoke()
root.update()
popup = next(w for w in all_widgets(root)
             if isinstance(w, tk.Toplevel) and w.winfo_exists()
             and 'Клиент' == w.title())
popup_texts = texts(popup)
check('в окошке коды', '55' in popup_texts and '11' in popup_texts, str(popup_texts))
check('названия нет', not any('Негатив' in t or 'лояльный' in t for t in popup_texts),
      str(popup_texts))
check('как говорить — тоже нет', not any('Ничего не предлагать' in t for t in popup_texts))
check('заголовок окна ничего не выдаёт', popup.title() == 'Клиент')

choose_11 = next(w for w in all_widgets(popup)
                 if isinstance(w, tk.ttk.Button)
                 and str(w.cget('text')) == '11')
choose_11.invoke()
root.update()
check('окошко закрылось', not popup.winfo_exists())
ui_db.expire_all()
check('теперь клиент в 11', ui_groups.group_of(client_id).code == '11')
marked_texts = texts(marked.frame)
check('новый код виден сразу, старого нет', '11' in marked_texts and '55' not in marked_texts,
      str([t for t in marked_texts if t in ('11', '55')]))

print()
print('=== В настройках группы правятся ===')
from ui.client_groups_editor import ClientGroupsEditor
holder = tk.Toplevel(root)
editor = ClientGroupsEditor(holder, ui_db, holder)
listed = [editor.tree.item(r)['values'][0] for r in editor.tree.get_children()]
check('список групп показан', [str(c) for c in listed] == ['11', '55'],
      str(listed))
holder.destroy()

root.destroy()
finish()
