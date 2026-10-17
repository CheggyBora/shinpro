"""
Категории мастеров: с каких услуг кому не начисляется.

Считаем ровно те примеры, на которых владелец проверял логику:
Иван 40%, Олег 35%, съёмщик Саша 25%; съёмщику не начисляются
ремонт и правка. Каждая услуга делится только между теми, кому она
начисляется: доля = база × свой процент ÷ сколько человек делят.

Ещё проверяем:
  · без категорий — копейка в копейку как раньше;
  · с товара не начисляется никому — раньше наценка с вентиля
    при оплате всё-таки попадала в процент;
  · услугу некому начислить — оплата проходит, доля цеху;
  · разбор «за что начислено» сохранён вместе с начислением;
  · категорию меняют только по PIN, правки списков — в журнал.
"""
import _setup
from _setup import use_temp_db, check, finish

import os

use_temp_db('master_roles')
os.chdir(_setup.PROJECT_DIR)

from config import init_db, SessionLocal
from models import Service, SalaryTransaction, Employee, AuditLog
from services import OrderService, EmployeeService, SalaryService
from services.shift_service import ShiftService
from services.employee_role_service import EmployeeRoleService
from services.salary_service import read_detail, split

init_db()
db = SessionLocal()

for name, price in (('Съём+Установка', 2000), ('Балансировка', 1200),
                    ('Ремонт жгутом', 600), ('Правка литого диска', 1500)):
    db.add(Service(name=name, vehicle_type='car', price_r16=price))
# Та же правка для джипов — исключать её надо вместе с легковой
db.add(Service(name='Правка литого диска', vehicle_type='suv', price_r16=1800))
db.add(Service(name='Вентиль', vehicle_type='car', is_goods=True,
               flat_price=100, purchase_price=30))
db.commit()

ShiftService(db).open_shift(open_posts=2)
people = EmployeeService(db)
for number, name, percent in ((1, 'Иван', 40), (2, 'Олег', 35), (3, 'Саша', 25)):
    people.register_employee(number, name)
    db.get(Employee, number).salary_percent = percent
db.commit()

orders = OrderService(db)
salary = SalaryService(db)
roles = EmployeeRoleService(db)


def service_id(name):
    return db.query(Service).filter(Service.name == name,
                                    Service.vehicle_type == 'car').first().id


def make_order(plate, names):
    order = orders.create_order(plate, 'R16', 'car', create_client=False)
    for name in names:
        orders.add_service_to_order(order.id, service_id(name))
    return order


FULL = ['Съём+Установка', 'Балансировка', 'Ремонт жгутом',
        'Правка литого диска', 'Вентиль']


def pay(order):
    nobody = salary.process_payment(order.id, 'cash',
                                    orders.calculate_total(order.id))
    paid = {t.employee_id: t for t in db.query(SalaryTransaction).filter(
        SalaryTransaction.work_order_id == order.id).all()}
    return paid, nobody


def amounts(paid):
    return {emp_id: t.amount for emp_id, t in paid.items()}


print('=== Категории по умолчанию ===')
titles = [r.title for r in roles.roles()]
check('мастер, сезонный мастер, сезонный съёмщик',
      titles == ['Мастер', 'Сезонный мастер', 'Сезонный съёмщик'], str(titles))
check('исключений по умолчанию нет ни у кого',
      all(not r.excluded for r in roles.roles()))
names = roles.service_names()
check('в списке услуг правка одна, хоть в прайсе их две',
      names.count('Правка литого диска') == 1, str(names))
check('товаров в списке нет', 'Вентиль' not in names, str(names))

print()
print('=== Пример 3: категорий нет — как раньше ===')
for number in (1, 2, 3):
    people.start_shift(number)
order = make_order('А001АА77', FULL)
check('в наряде трое', order.employee_ids == '1,2,3', order.employee_ids)
paid, nobody = pay(order)
got = amounts(paid)
# 5300 работы (вентиль — товар) × процент ÷ 3
check('Иван 706,67', got[1] == 706.67, str(got))
check('Олег 618,33', got[2] == 618.33, str(got))
check('Саша 441,67', got[3] == 441.67, str(got))
check('некому начислить — ничего', nobody == [], str(nobody))
db.refresh(order)
check('база наряда 5300 — без товара', order.salary_base == 5300,
      str(order.salary_base))

print()
print('=== Наценка с товара в процент больше не попадает ===')
# Раньше: база = итог 5400 − себестоимость 30 = 5370, и Иван получал
# 5370 × 40% ÷ 3 = 716 вместо 706,67
check('у Ивана не 716', got[1] != 716.0, str(got[1]))

print()
print('=== Настраиваем съёмщика ===')
loader = next(r for r in roles.roles() if r.title == 'Сезонный съёмщик')
master = next(r for r in roles.roles() if r.title == 'Мастер')
roles.set_excluded(loader.id, ['Ремонт жгутом', 'Правка литого диска'])
check('исключения записаны',
      roles.get(loader.id).excluded == {'Ремонт жгутом', 'Правка литого диска'})
journal = db.query(AuditLog).filter(
    AuditLog.action == 'employee_role.services').all()
check('правка списка — в журнале', len(journal) == 1,
      str([j.description for j in journal]))

try:
    people.update_role(3, loader.id, '9999')
    check('без PIN категорию не сменить', False)
except ValueError as e:
    check('без PIN категорию не сменить', 'PIN' in str(e), str(e))
people.update_role(3, loader.id, '0000')
people.update_role(1, master.id, '0000')
people.update_role(2, master.id, '0000')
check('Саша — съёмщик', roles.role_title(db.get(Employee, 3)) == 'Сезонный съёмщик')

print()
print('=== Пример 1: два мастера и съёмщик ===')
order = make_order('А002АА77', FULL)
paid, nobody = pay(order)
got = amounts(paid)
check('Иван 846,67', got[1] == 846.67, str(got))
check('Олег 740,83', got[2] == 740.83, str(got))
check('Саша 266,67', got[3] == 266.67, str(got))
check('всего на зарплату 1854,17',
      round(sum(got.values()), 2) == 1854.17, str(sum(got.values())))
check('некому начислить — ничего', nobody == [], str(nobody))

sasha = read_detail(paid[3])
check('у Саши в разборе — за что не начислено',
      sasha['skipped'] == ['Ремонт жгутом', 'Правка литого диска'],
      str(sasha['skipped']))
ivan = read_detail(paid[1])
repair = next(l for l in ivan['lines'] if l['name'] == 'Ремонт жгутом')
check('у Ивана ремонт делили двое', repair['shared'] == 2, str(repair))
check('и это 120', repair['amount'] == 120, str(repair))
removal = next(l for l in ivan['lines'] if l['name'] == 'Съём+Установка')
check('съём делили трое — 266,67',
      removal['shared'] == 3 and removal['amount'] == 266.67, str(removal))
check('вентиля в разборе нет',
      not any(l['name'] == 'Вентиль' for l in ivan['lines']))

print()
print('=== Пример 2: Олега на смене нет ===')
people.end_shift(2)
order = make_order('А003АА77', FULL)
check('в наряде двое', order.employee_ids == '1,3', order.employee_ids)
paid, nobody = pay(order)
got = amounts(paid)
check('Иван 1480', got[1] == 1480, str(got))
check('Саша 400', got[3] == 400, str(got))

print()
print('=== На смене один съёмщик, а в наряде правка ===')
people.end_shift(1)
order = make_order('А004АА77', ['Съём+Установка', 'Правка литого диска'])
paid, nobody = pay(order)
got = amounts(paid)
check('Саше — только съём: 2000 × 25% = 500', got[3] == 500, str(got))
check('правку назвали некому начислить',
      nobody == [{'name': 'Правка литого диска', 'base': 1500}], str(nobody))
db.refresh(order)
check('оплата прошла', order.status == 'paid')

print()
print('=== Скидка на наряд ===')
people.start_shift(1)
people.start_shift(2)
order = make_order('А005АА77', ['Ремонт жгутом', 'Балансировка'])
orders.update_general_discount(order.id, 10)
paid, _ = pay(order)
got = amounts(paid)
# Ремонт 540 после скидки, делят Иван и Олег (Саша исключён):
#   Иван 540×40%÷2 = 108, Олег 540×35%÷2 = 94,5
# Балансировка 1080, делят трое:
#   Иван 144, Олег 126, Саша 90
check('Иван 252', got[1] == 252, str(got))
check('Олег 220,5', got[2] == 220.5, str(got))
check('Саша 90', got[3] == 90, str(got))

print()
print('=== Возврат откатывает начисления, как и раньше ===')
ok, message = orders.refund_order(order.id, reason='тест')
check('возврат проведён', ok, message)
net = {}
for t in db.query(SalaryTransaction).filter(
        SalaryTransaction.work_order_id == order.id).all():
    net[t.employee_id] = round(net.get(t.employee_id, 0) + t.amount, 2)
check('у всех ноль', all(v == 0 for v in net.values()), str(net))

print()
print('=== Правка списка не трогает прошлое ===')
first = db.query(SalaryTransaction).filter(
    SalaryTransaction.employee_id == 3).order_by(SalaryTransaction.id).first()
before = first.amount
roles.set_excluded(loader.id, ['Ремонт жгутом', 'Правка литого диска',
                               'Балансировка'])
db.refresh(first)
check('старое начисление Саши не изменилось', first.amount == before)

print()
print('=== Удалили категорию — люди снова получают со всего ===')
moved = roles.delete(loader.id)
check('Сашу освободили', moved == 1, str(moved))
db.expire_all()
check('Саша теперь «Мастер»', roles.role_title(db.get(Employee, 3)) == 'Мастер')

print()
print('=== Расчёт сам по себе ===')
result, nobody = split([('Правка', 1000.0)], [(1, 40, set()), (2, 30, {'Правка'})])
check('исключённый не делит: 1000 × 40% = 400', result[1]['amount'] == 400,
      str(result))
check('у исключённого 0', result[2]['amount'] == 0, str(result))
result, nobody = split([('Съём', 1000.0), ('Балансировка', 1000.0),
                        ('Шиномонтаж', 1000.0)],
                       [(1, 40, set()), (2, 40, set()), (3, 40, set())])
check('округляется итог, а не строки: 3000 × 40% ÷ 3 = 400',
      result[1]['amount'] == 400, str(result[1]['amount']))

db.close()

print()
print('=== Экран: категория в списке и в настройках ===')
import tkinter as tk
import ui.employees_tab
import ui.employee_roles_editor as editor_module

_setup.silence_dialogs(ui.employees_tab, editor_module)
root = tk.Tk()
root.withdraw()

ui_db = SessionLocal()
tab = ui.employees_tab.EmployeesTab(root, ui_db)
rows = {str(tab.employees_tree.item(r)['values'][0]):
        tab.employees_tree.item(r)['values'] for r in tab.employees_tree.get_children()}
check('в списке есть категория', rows['1'][2] == 'Мастер', str(rows['1']))

holder = tk.Toplevel(root)
editor = editor_module.EmployeeRolesEditor(holder, ui_db, holder)
root.update()
check('категории показаны', editor.roles_list.size() == 2,
      str(editor.roles_list.get(0, 'end')))
editor.roles_list.selection_clear(0, 'end')
editor.roles_list.selection_set(1)
editor.pick()
check('услуги галочками', 'Правка литого диска' in editor.checks,
      str(list(editor.checks)))
editor.checks['Правка литого диска'].set(True)
editor.save()
ui_db.expire_all()
picked = EmployeeRoleService(ui_db).roles()[1]
check('галочка сохранилась сразу', picked.excluded == {'Правка литого диска'},
      str(picked.excluded))

from services.shift_service import ShiftService as _Shift
shift = _Shift(ui_db).get_current_shift()
details = _Shift(ui_db).get_shift_salary_details(shift.id)
loader_rows = [row for row in details[3]['orders'] if row['skipped']]
check('в разборе смены у Саши видно, что не начислено',
      bool(loader_rows) and 'Правка литого диска' in loader_rows[0]['skipped'],
      str(loader_rows[:1]))

holder.destroy()
root.destroy()
finish()
