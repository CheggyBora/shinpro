"""
Машина с телефона и обложка наряда (docs/order_photo.md).

Телефон снял машину, сервер прочитал номер, человек на телефоне его
подтвердил. Цех при живом обмене забирает такую «машину с телефона»,
скачивает снимок и открывает окно создания наряда. Создали наряд —
снимок становится его обложкой; закрыли окно — машина снимается.

Снимки лежат в папке photos/covers рядом с базой: в базе только имя
файла, чтобы база не пухла от фотографий.
"""
import os

from logger import log
from utils import as_naive

COVERS = os.path.join('photos', 'covers')


def covers_dir():
    from config import DATABASE_URL, get_app_dir
    base = get_app_dir()
    if DATABASE_URL.startswith('sqlite:///'):
        base = os.path.dirname(os.path.abspath(DATABASE_URL[len('sqlite:///'):])) or base
    folder = os.path.join(base, COVERS)
    os.makedirs(folder, exist_ok=True)
    return folder


def cover_file(order, db=None):
    """
    Полный путь к обложке наряда или None — обложки нет, файл пропал или
    обложка выключена у всех направлений наряда (db передан — проверяем).
    """
    name = getattr(order, 'cover_path', None)
    if not name:
        return None
    if db is not None:
        from services import directions
        if not any(directions.photo_on(db, d) for d in directions.parse(order.directions)):
            return None
    path = os.path.join(covers_dir(), os.path.basename(name))
    return path if os.path.exists(path) else None


def load_image(path, width, height=None):
    """Картинка для окна, вписанная в width×height. None — не открылась."""
    try:
        from PIL import Image, ImageTk
        with Image.open(path) as image:
            image = image.convert('RGB')
            image.thumbnail((width, height or width * 3 // 4))
            return ImageTk.PhotoImage(image)
    except Exception as e:
        log.warning(f'Обложка {path} не открылась: {e}')
        return None


def show_full(parent, path, title='Фото машины'):
    """Снимок на весь экран (почти): щелчок или Esc — закрыть."""
    import tkinter as tk
    window = tk.Toplevel(parent)
    window.title(title)
    window.configure(bg='black')
    width = int(window.winfo_screenwidth() * 0.8)
    height = int(window.winfo_screenheight() * 0.8)
    image = load_image(path, width, height)
    if image is None:
        window.destroy()
        return None
    label = tk.Label(window, image=image, bg='black', cursor='hand2')
    label.image = image
    label.pack()
    label.bind('<Button-1>', lambda e: window.destroy())
    window.bind('<Escape>', lambda e: window.destroy())
    window.transient(parent.winfo_toplevel())
    window.focus_set()
    return window


class ArrivalService:
    def __init__(self, db):
        self.db = db

    def _sync(self):
        from services.sync_service import SyncService
        return SyncService(self.db)

    def pending(self):
        """Машины с телефона, которых цех ещё не видел, со скачанными снимками."""
        sync = self._sync()
        if not sync.is_enabled():
            return []
        from services import directions
        allowed = directions.photo_directions(self.db)
        if not allowed:
            return []
        result = []
        for item in sync.arrivals():
            try:
                arrival_id = int(item['id'])
            except (KeyError, TypeError, ValueError):
                continue
            # Направление выключили, пока машина ждала, — не открываем
            wanted = [d for d in (item.get('directions') or []) if d in allowed]
            if item.get('directions') and not wanted:
                continue
            item = dict(item, directions=wanted)
            path = os.path.join(covers_dir(), f'arrival_{arrival_id}.jpg')
            if not os.path.exists(path):
                try:
                    data = sync.arrival_photo(arrival_id)
                    with open(path, 'wb') as f:
                        f.write(data)
                except Exception as e:
                    log.warning(f'Снимок машины с телефона №{arrival_id} не скачался: {e}')
                    path = None
            result.append({'id': arrival_id, 'plate': item.get('plate') or '',
                           'directions': item.get('directions') or [],
                           'photo': path, 'created_at': item.get('created_at')})
        return result

    def attach(self, order, path):
        """Снимок стал обложкой наряда."""
        if not path or not os.path.exists(path):
            return None
        name = f'order_{order.id}.jpg'
        target = os.path.join(covers_dir(), name)
        try:
            os.replace(path, target)
        except OSError as e:
            log.warning(f'Обложка наряда №{order.id} не сохранилась: {e}')
            return None
        order.cover_path = name
        self.db.commit()
        return target

    def done(self, arrival_id, order_id=None):
        """Сказать серверу: наряд создан (или окно закрыли) — больше не присылать."""
        try:
            self._sync().arrival_done(arrival_id, order_id)
            return True
        except Exception as e:
            log.warning(f'Сервер не узнал, что машина №{arrival_id} разобрана: {e}')
            return False

    def latest_for_car(self, car_id):
        """Последняя обложка машины: (наряд, путь) или (None, None)."""
        from models import WorkOrder
        rows = self.db.query(WorkOrder).filter(
            WorkOrder.car_id == car_id, WorkOrder.cover_path.isnot(None)).order_by(
                WorkOrder.id.desc()).all()
        for order in rows:
            path = cover_file(order, self.db)
            if path:
                return order, path
        return None, None
