"""
Едут со склада и «Приехало» (решение владельца 13.11.2026).

  · заказали со склада (в программе или клиент из кабинета) — комплект
    «едет», в списке «Едут со склада» по дате;
  · «Приехало» — задача «Привезти со склада» сделана, сервер получает
    время приезда и пишет клиенту; отменил клиент — из «едут» убран.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('storage_transit')
shown = _setup.silence_dialogs()

from datetime import date, timedelta

from config import init_db, SessionLocal
from models import CalendarTask
from services.calendar_service import CalendarService
from services.sync_service import SyncService
from services.tire_storage_service import TireStorageService

init_db()
db = SessionLocal()
service = TireStorageService(db)
first = service.accept_storage('А123ВВ777', 'AB1', 'Шины с дисками', 'R16', 'Nokian', '', '',
                               client_name='Пётр', client_phone='+79005554433')
second = service.accept_storage('В222ВВ77', 'AB2', 'Шины', 'R17', 'Michelin', '', '')

print('=== Заказали со склада ===')
day = date.today() + timedelta(days=3)
CalendarService(db).storage_from_warehouse(first, day, '10:00', 'перекидка', created_by='Цех')
check('комплект «едет» к дате', first.delivery_state == 'ordered'
      and first.delivery_for.strftime('%d.%m %H:%M') == day.strftime('%d.%m') + ' 10:00')
SyncService(db)._apply_storage_request({'storage_local_id': second.id,
                                        'requested_for': (day + timedelta(days=1)).isoformat() + 'T12:00:00'})
db.refresh(second)
check('заказ клиента из кабинета — тоже «едет»', second.delivery_state == 'ordered')
check('в списке «Едут со склада» — оба, по дате', [r.id for r in service.in_transit()] == [first.id, second.id])

print('\n=== Приехало ===')
service.mark_arrived(first, by='Цех')
check('отмечено: приехал', first.delivery_state == 'arrived' and first.arrived_at is not None)
check('в календаре задач хранения нет', not db.query(CalendarTask).filter(
    CalendarTask.storage_ref == str(first.id)).count())
check('в «едут» остался один', [r.id for r in service.in_transit()] == [second.id])
pushed = {row['local_id']: row for row in SyncService(db)._collect_storage()}
check('сервер получает время приезда — напишет клиенту', pushed[first.id]['arrived_at'] is not None
      and pushed[second.id]['arrived_at'] is None)
try:
    service.mark_arrived(first)
    check('второй раз «Приехало» — отказ', False)
except ValueError:
    check('второй раз «Приехало» — отказ', True)

print('\n=== Клиент отменил заявку ===')
SyncService(db)._apply_storage_request({'storage_local_id': second.id, 'requested_for': None})
db.refresh(second)
check('отменил — из «едут» убран', second.delivery_state is None and not service.in_transit())

print('\n=== Окно «Едут со склада» ===')
import tkinter as tk
from ui.tire_storage_tab import TransitDialog
CalendarService(db).storage_from_warehouse(second, day, None, None)
root = tk.Tk()
dialog = TransitDialog(root, db)
check('в окне — комплект', list(dialog.tree.get_children()) == [str(second.id)])
dialog.tree.selection_set(str(second.id))
dialog.arrived()
db.refresh(second)
check('«Приехало» из окна', second.delivery_state == 'arrived' and 'empty' in dialog.tree.get_children())
root.destroy()

print('\n=== Надо отвезти на склад ===')
third = service.accept_storage('С333СС77', 'AB3', 'Шины', 'R15', 'Kama', '', '')
CalendarService(db).storage_to_warehouse(third, date.today() + timedelta(days=1))
check('в «надо отвезти» — новый комплект', [r.id for r in service.to_warehouse()] == [third.id])
service.mark_sent(third)
check('«Отвезли» — из списка убран', not service.to_warehouse() and third.warehouse_state == 'sent')

print('\n=== Старые задачи хранения из календаря — в списки, раз ===')
from models import CalendarTask as Task
from models.calendar import STORAGE
fourth = service.accept_storage('Е444ЕЕ77', 'AB4', 'Шины', 'R18', 'Pirelli', '', '')
fifth = service.accept_storage('К555КК77', 'AB5', 'Шины', 'R19', 'Yoko', '', '')
cal = CalendarService(db)
cal.create(title=f'Отвезти на склад №{fourth.id}', due_date=date.today(), category=STORAGE,
           storage_ref=str(fourth.id))
cal.create(title=f'Привезти со склада №{fifth.id}', due_date=date.today() + timedelta(days=2),
           due_time='11:00', category=STORAGE, storage_ref=str(fifth.id))
moved = service.move_calendar_tasks()
db.refresh(fourth)
db.refresh(fifth)
check('перенесено две задачи, в календаре хранения не осталось', moved == 2 and not db.query(Task).filter(
    Task.category == STORAGE, Task.deleted.is_(False)).count())
check('«Отвезти» → надо отвезти, «Привезти» → едет к 11:00', fourth.warehouse_state == 'to_send'
      and fifth.delivery_state == 'ordered' and fifth.delivery_for.strftime('%H:%M') == '11:00')
check('второй раз — ничего', service.move_calendar_tasks() == 0)
from services import task_sections
check('раздел «Хранение» в календаре спрятан',
      any(row['key'] == STORAGE and row.get('hidden') for row in task_sections.load(db)))

db.close()
finish()
