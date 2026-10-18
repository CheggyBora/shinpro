"""
Табличка с QR «Встать в очередь» у въезда — печатается из цеха.

Ссылку даёт сервер: в ней ключ точки. «Перевыпустить» меняет ключ —
старая табличка (и её фото, пересланное знакомым) перестаёт ставить в
очередь. Тех, кто уже стоит, это не трогает. Последнюю ссылку помним,
чтобы допечатать табличку и без интернета (docs/live_queue.md).
"""
import os
import sys

from logger import log

URL_CACHE_KEY = 'live_qr_url'


class PosterError(Exception):
    pass


class QueuePosterService:
    def __init__(self, db):
        self.db = db
        self.out_dir = None     # подменяют в тестах

    def _settings(self):
        from services.settings_service import SettingsService
        return SettingsService(self.db)

    # ------------------------------------------------------------------
    # Ссылка
    # ------------------------------------------------------------------

    def cached_url(self):
        return self._settings().get(URL_CACHE_KEY, '') or ''

    def url(self, reissue=False):
        """
        Ссылка для QR. Нет связи — последняя известная; перевыпустить
        без связи нельзя: сервер не узнал бы новый ключ, и табличка не
        работала бы.
        """
        from services.sync_service import SyncService

        sync = SyncService(self.db)
        if not sync.is_enabled():
            if reissue or not self.cached_url():
                raise PosterError('Нет связи с сервером приложения: '
                                  'включите обмен в настройках')
            return self.cached_url()
        try:
            answer = sync._call('POST' if reissue else 'GET', '/sync/live/qr',
                                {} if reissue else None)
        except Exception as e:
            if reissue or not self.cached_url():
                raise PosterError(f'Сервер не ответил: {e}')
            log.warning(f"Ссылка для QR не обновилась, печатаем прежнюю: {e}")
            return self.cached_url()
        url = sync.get_url() + answer['path']
        self._settings().set(URL_CACHE_KEY, url)
        return url

    # ------------------------------------------------------------------
    # Табличка
    # ------------------------------------------------------------------

    def _dir(self):
        if self.out_dir:
            path = self.out_dir
        else:
            if getattr(sys, 'frozen', False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base, 'labels')
        os.makedirs(path, exist_ok=True)
        return path

    def _font(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        if getattr(sys, 'frozen', False):
            base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont('DejaVuSans', os.path.join(base, 'fonts', 'DejaVuSans.ttf')))
            return 'DejaVuSans'
        except Exception as e:
            log.error(f"Шрифт для таблички не зарегистрирован: {e}")
            return 'Helvetica'

    def make(self, url, title=None):
        """PDF A4 с QR. Возвращает путь к файлу."""
        import qrcode
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        if not title:
            from services.company_service import get_company
            title = get_company(self.db).name or 'Шиномонтаж'

        path = os.path.join(self._dir(), 'qr_очередь.pdf')
        font = self._font()
        width, height = A4
        page = canvas.Canvas(path, pagesize=A4)

        def centered(y, text, size, color=(0.08, 0.09, 0.11)):
            page.setFont(font, size)
            page.setFillColorRGB(*color)
            page.drawCentredString(width / 2, y, text)

        # Красная полоса с названием
        page.setFillColorRGB(0.89, 0.15, 0.18)
        page.rect(0, height - 36 * mm, width, 36 * mm, stroke=0, fill=1)
        centered(height - 23 * mm, title.upper(), 26, color=(1, 1, 1))

        centered(height - 62 * mm, 'Встать в очередь', 40)
        centered(height - 76 * mm, 'Наведите камеру телефона на код', 17,
                 color=(0.36, 0.39, 0.44))

        # QR — квадратами по матрице: картинки (PIL) программе не нужны
        code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
        code.add_data(url)
        code.make(fit=True)
        matrix = code.get_matrix()
        side = 130 * mm
        cell = side / len(matrix)
        left = (width - side) / 2
        top = height - 86 * mm
        page.setFillColorRGB(0, 0, 0)
        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                if dark:
                    page.rect(left + c * cell, top - (r + 1) * cell,
                              cell + 0.2, cell + 0.2, stroke=0, fill=1)

        y = top - side - 14 * mm
        centered(y, 'Номер машины, телефон, диаметр — и вы в очереди.', 15)
        centered(y - 9 * mm, 'Когда подойдёт ваша, на телефоне появится', 15,
                 color=(0.36, 0.39, 0.44))
        centered(y - 17 * mm, 'номер поста и схема, куда ехать.', 15,
                 color=(0.36, 0.39, 0.44))
        centered(18 * mm, url.replace('https://', ''), 10, color=(0.5, 0.53, 0.58))

        page.showPage()
        page.save()
        return path
