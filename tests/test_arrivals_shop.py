"""
Наряд по фото машины — сторона цеха (docs/order_photo.md).

Телефон снял машину, сервер прочитал номер. Цех забирает «машину с
телефона», скачивает снимок и открывает окно создания с номером. Наряд
создаёт приёмщик; снимок становится обложкой — в шапке наряда, на
вкладке и во «Всё по машине». Закрыли окно — машина снимается.
"""
import _setup
from _setup import use_temp_db, check, finish

import io
import os

use_temp_db('arrivals_shop')
os.chdir(_setup.PROJECT_DIR)
_setup.silence_dialogs()

from config import init_db, SessionLocal
from models import Service, WorkOrder
from services.shift_service import ShiftService
from services.sync_service import SyncService
from services.arrival_service import ArrivalService, cover_file, covers_dir

init_db()
db = SessionLocal()
db.add(Service(name='Шиномонтаж', vehicle_type='car', price_r16=2000))
db.commit()
ShiftService(db).open_shift(cash_start=0)


def jpeg():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (640, 480), (60, 70, 80)).save(buffer, 'JPEG')
    return buffer.getvalue()


# Сервер подменяем: проверяем цех, а не сеть
server = {'arrivals': [{'id': 7, 'plate': 'А123ВВ777', 'directions': ['tire'],
                        'photo_id': 70, 'created_at': '2026-10-26T14:50:00'}],
          'done': [], 'downloads': 0}


def fake_photo(self, arrival_id):
    server['downloads'] += 1
    return jpeg()


SyncService.is_enabled = lambda self: True
SyncService.arrivals = lambda self: [a for a in server['arrivals']
                                     if a['id'] not in [d[0] for d in server['done']]]
SyncService.arrival_photo = fake_photo
SyncService.arrival_done = lambda self, arrival_id, order_local_id=None: server['done'].append(
    (arrival_id, order_local_id))

print('=== Включается отдельно у шинки и мойки ===')
from services import directions
check('по умолчанию выключено', directions.photo_directions(db) == [])
check('выключено — машины с телефона не забираем', ArrivalService(db).pending() == [])
directions.set_photo_on(db, 'wash', True)
check('мойка выключена — и фото мойки нет', directions.photo_directions(db) == [])
directions.set_photo_on(db, 'tire', True)
check('включили у шиномонтажа', directions.photo_directions(db) == ['tire'])
payload = SyncService(db)._collect_settings()
check('сервер узнаёт, где включено', payload['arrival_photo_tire'] == '1'
      and payload['arrival_photo_wash'] == '0')

print()
print('=== Забираем машину с телефона ===')
arrivals = ArrivalService(db).pending()
check('пришла одна машина с номером', len(arrivals) == 1 and arrivals[0]['plate'] == 'А123ВВ777')
check('снимок скачан в папку обложек', arrivals[0]['photo'] and os.path.exists(arrivals[0]['photo'])
      and os.path.dirname(arrivals[0]['photo']) == covers_dir())
ArrivalService(db).pending()
check('второй раз не качаем', server['downloads'] == 1)

print()
print('=== Окно создания ===')
import tkinter as tk
from ui import MainWindow
root = tk.Tk()
root.withdraw()
app = MainWindow(root)
root.update()
app._show_arrivals(arrivals)
root.update()
dialog = app.orders_tab.create_dialog
check('открылось окно создания', dialog is not None and dialog.winfo_exists())


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


texts = [w.cget('text') for w in widgets(dialog) if isinstance(w, tk.Label) or w.winfo_class() == 'TLabel']
check('номер подставлен, видно, что с телефона', any('А123ВВ777 · с телефона' in str(t) for t in texts))
check('снимок в окне', any(isinstance(w, tk.Label) and str(w.cget('image')) for w in widgets(dialog)))
app._show_arrivals(arrivals)
check('пока окно открыто, второе не открываем', app.orders_tab.create_dialog is dialog)

combos = [w for w in widgets(dialog) if w.winfo_class() == 'TCombobox']
combos[0].set('R16')
create = next(w for w in widgets(dialog) if w.winfo_class() == 'TButton' and w.cget('text') == 'Создать наряд')
create.invoke()
root.update()
import time
for _ in range(20):
    if server['done']:
        break
    time.sleep(0.1)
order = db.query(WorkOrder).order_by(WorkOrder.id.desc()).first()
check('наряд создан приёмщиком', order is not None and order.car.license_plate == 'А123ВВ777')
check('снимок стал обложкой', cover_file(order) is not None and order.cover_path == f'order_{order.id}.jpg')
check('сервер узнал номер наряда', server['done'] == [(7, order.id)], str(server['done']))
widget = app.orders_tab.active_orders[order.id]
check('на вкладке — картинка', widget._tab_image is not None
      and app.orders_tab.order_notebook.tab(widget.frame, 'image'))
check('в шапке наряда — миниатюра', any(isinstance(w, tk.Label) and str(w.cget('image'))
                                        for w in widgets(widget.frame)))

print()
print('=== Закрыли окно, не создав ===')
server['arrivals'].append({'id': 8, 'plate': 'К555КК77', 'directions': [], 'photo_id': 80,
                          'created_at': '2026-10-26T15:00:00'})
fresh = ArrivalService(db).pending()
app._show_arrivals(fresh)
root.update()
dialog = app.orders_tab.create_dialog
dialog.protocol('WM_DELETE_WINDOW')
dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
for _ in range(20):
    if len(server['done']) == 2:
        break
    time.sleep(0.1)
check('машина снята без наряда', server['done'][-1] == (8, None), str(server['done']))
check('окно закрыто', not dialog.winfo_exists())

print()
print('=== Всё по машине ===')
from ui.car_info import CarInfo
info = CarInfo(root, db, 'А123ВВ777')
images = [w for w in widgets(info.body) if isinstance(w, tk.Label) and str(w.cget('image'))]
check('крупное последнее фото и маленькое у визита', len(images) == 2)
info.dialog.destroy()

print()
print('=== Выключили у шиномонтажа ===')
check('QR на месте, пока включено', app.orders_tab.qr_button.winfo_manager() == 'pack')
directions.set_photo_on(db, 'tire', False)
root.update()
check('кнопки QR нет', app.orders_tab.qr_button.winfo_manager() == '')
check('обложка не видна', cover_file(order, db) is None and cover_file(order) is not None)
info = CarInfo(root, db, 'А123ВВ777')
check('и во «Всё по машине» нет', not [w for w in widgets(info.body)
                                      if isinstance(w, tk.Label) and str(w.cget('image'))])
info.dialog.destroy()
directions.set_photo_on(db, 'tire', True)
root.update()
check('включили — QR вернулся', app.orders_tab.qr_button.winfo_manager() == 'pack')

root.destroy()
db.close()
finish()
