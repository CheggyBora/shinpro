"""
Печать наклеек для хранения шин.

Наклейка клеится на комплект и отвечает на один вопрос: чей это комплект
и что в нём. Когда клиент приезжает забирать, кладовщик находит его
по госномеру, не поднимая документы.

Размер наклейки задаётся в настройках: моделей принтеров этикеток много,
и ходовые размеры у них разные. Макет подстраивается под заданный размер,
поэтому менять код при смене принтера не придётся.
"""
import os
import subprocess
import sys

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont

from utils import format_phone
from logger import log

# Ходовые размеры наклеек, мм
LABEL_SIZES = ['58x40', '58x60', '58x80', '100x50', '100x70']

ENABLED_KEY = 'label_printing_enabled'
SIZE_KEY = 'label_size'
DEFAULT_SIZE = '58x40'


def parse_size(value):
    """Разобрать «58x40» в миллиметры. При мусоре — размер по умолчанию."""
    try:
        width, height = str(value).lower().replace(',', '.').split('x')
        return float(width), float(height)
    except (ValueError, AttributeError):
        width, height = DEFAULT_SIZE.split('x')
        return float(width), float(height)


class LabelService:
    def __init__(self, db=None):
        self.db = db
        self.font_name = self._register_font()
        # Можно подменить папку — нужно в тестах, чтобы не сорить
        # рядом с программой
        self.labels_dir = None

    def _register_font(self):
        """Шрифт с кириллицей — тот же, что для остальных документов."""
        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        path = os.path.join(base, 'fonts', 'DejaVuSans.ttf')
        try:
            if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('DejaVuSans', path))
            return 'DejaVuSans'
        except Exception as e:
            log.error(f"Шрифт для наклейки не зарегистрирован: {e}")
            return 'Helvetica'

    # ------------------------------------------------------------------
    # Настройки
    # ------------------------------------------------------------------

    def is_enabled(self):
        if self.db is None:
            return False
        from services.settings_service import SettingsService
        return SettingsService(self.db).get(ENABLED_KEY, '0') == '1'

    def get_size(self):
        if self.db is None:
            return parse_size(DEFAULT_SIZE)
        from services.settings_service import SettingsService
        return parse_size(SettingsService(self.db).get(SIZE_KEY, DEFAULT_SIZE))

    def get_labels_dir(self):
        if self.labels_dir:
            os.makedirs(self.labels_dir, exist_ok=True)
            return self.labels_dir

        if getattr(sys, 'frozen', False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'labels')
        os.makedirs(path, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Макет
    # ------------------------------------------------------------------

    def _fit_font_size(self, text, max_width, start_size, min_size=6):
        """Подобрать размер шрифта, при котором строка влезает в ширину."""
        size = start_size
        while size > min_size and stringWidth(text, self.font_name, size) > max_width:
            size -= 0.5
        return size

    def generate_storage_label(self, storage, client=None, copies=1):
        """
        Собрать наклейку на комплект шин.

        storage — запись хранения, client — владелец, если известен.
        copies — сколько одинаковых наклеек положить в файл подряд.
        Возвращает путь к файлу.
        """
        width_mm, height_mm = self.get_size()
        width, height = width_mm * mm, height_mm * mm

        path = os.path.join(self.get_labels_dir(), f'label_{storage.id}.pdf')
        c = canvas.Canvas(path, pagesize=(width, height))

        for _ in range(max(1, copies)):
            self._draw_label(c, storage, client, width, height)
            c.showPage()

        c.save()
        return path

    def _draw_label(self, c, storage, client, width, height):
        padding = 3 * mm
        inner_width = width - padding * 2
        y = height - padding

        # Госномер — самое крупное: по нему ищут комплект на складе
        plate = storage.car_number or '—'
        size = self._fit_font_size(plate, inner_width, start_size=height / mm * 0.42)
        c.setFont(self.font_name, size)
        y -= size
        c.drawString(padding, y, plate)

        # Владелец
        if client and (client.name or client.phone):
            y -= 4 * mm
            owner = client.name or ''
            if client.phone:
                owner = f"{owner} {format_phone(client.phone)}".strip()
            owner_size = self._fit_font_size(owner, inner_width, start_size=8)
            c.setFont(self.font_name, owner_size)
            c.drawString(padding, y, owner)

        # Разделитель
        y -= 2.5 * mm
        c.setLineWidth(0.4)
        c.line(padding, y, width - padding, y)

        # Состав комплекта
        details = []
        if storage.storage_type:
            details.append(storage.storage_type)
        if storage.diameter:
            details.append(storage.diameter)
        if storage.wheel_type:
            details.append(storage.wheel_type)

        lines = []
        if details:
            lines.append(' · '.join(details))
        if storage.brand:
            lines.append(storage.brand)
        if storage.accepted_date:
            lines.append(f"Принято {storage.accepted_date.strftime('%d.%m.%Y')}")
        lines.append(f"Комплект № {storage.id}")

        c.setFont(self.font_name, 7.5)
        for line in lines:
            if y < padding + 4 * mm:  # не вылезаем за нижний край
                break
            y -= 3.4 * mm
            text = line
            # Длинную строку обрезаем, а не выпускаем за край наклейки
            while (stringWidth(text, self.font_name, 7.5) > inner_width
                   and len(text) > 4):
                text = text[:-2]
            c.drawString(padding, y, text)

    # ------------------------------------------------------------------
    # Печать
    # ------------------------------------------------------------------

    def print_file(self, path):
        """
        Отправить наклейку на принтер по умолчанию.

        Конкретный принтер не выбираем: для этого нужен драйвер под
        известную модель. Пока принтер этикеток назначается в Windows
        принтером по умолчанию.
        """
        try:
            if sys.platform == 'win32':
                os.startfile(path, "print")
            elif sys.platform == 'darwin':
                subprocess.Popen(['lp', path])
            else:
                subprocess.Popen(['lp', path])
            return True
        except Exception as e:
            log.error(f"Не удалось напечатать наклейку: {e}")
            return False
