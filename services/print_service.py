from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from datetime import datetime
import os
import sys
from utils import get_moscow_time, money_round
from logger import log

class PrintService:
    def __init__(self, db=None):
        # Сессия для чтения реквизитов. Печать вызывается из мест, где
        # сессии под рукой нет, поэтому её можно не передавать — тогда
        # реквизиты читаются своей короткой сессией.
        self.db = db
        self._company = None

        # Определяем базовый путь для ресурсов (шрифтов)
        if getattr(sys, 'frozen', False):
            # PyInstaller создаёт временную папку sys._MEIPASS для упакованных ресурсов
            base_path = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
        else:
            # Если запущен как скрипт
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Директория для чеков всегда рядом с exe (не внутри временной папки)
        if getattr(sys, 'frozen', False):
            receipts_base = os.path.dirname(sys.executable)
        else:
            receipts_base = base_path
        
        self.receipts_dir = os.path.join(receipts_base, "receipts")
        if not os.path.exists(self.receipts_dir):
            os.makedirs(self.receipts_dir)
        
        # Путь к логотипу (нормализуем для Windows)
        self.logo_path = os.path.normpath(os.path.join(base_path, "assets", "logo.jpg"))
        log.debug(f"Путь к логотипу: {self.logo_path}")
        log.debug(f"Логотип существует: {os.path.exists(self.logo_path)}")
        
        # Регистрируем шрифт DejaVu Sans для PDF с поддержкой кириллицы
        fonts_dir = os.path.join(base_path, "fonts")
        font_path = os.path.join(fonts_dir, 'DejaVuSans.ttf')
        
        try:
            # Регистрируем шрифт только если еще не зарегистрирован
            if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
                    log.debug(f"Шрифт DejaVuSans зарегистрирован для PDF: {font_path}")
                else:
                    raise FileNotFoundError(f"Файл шрифта не найден: {font_path}")
            
            self.font_name = 'DejaVuSans'
        except Exception as e:
            log.error(f"Ошибка регистрации шрифта DejaVu: {e}")
            log.debug(f"  Используется Helvetica в качестве резервного шрифта")
            self.font_name = 'Helvetica'
    
    def company(self):
        """Реквизиты из настроек. Читаем один раз на документ."""
        if self._company is None:
            from services.company_service import get_company
            self._company = get_company(self.db)
        return self._company

    def generate_thermal_receipt(self, order, items, total_amount, width_mm=58):
        """
        Чек для термопринтера: узкая лента вместо листа A4.

        Высота считается по содержимому — у ленты её нет заранее.
        Всё в одну колонку: на 58 мм две колонки не помещаются.
        """
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas as pdf_canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth
        from services.order_service import OrderService

        padding = 3 * mm
        width = width_mm * mm
        inner = width - padding * 2

        # Прикидываем высоту: шапка, позиции, итоги, рекомендации, подвал
        lines_count = 14 + len(items) * 2
        if order.recommendations and order.recommendations.strip():
            lines_count += 3 + len(order.recommendations) // 30
        height = max(120 * mm, lines_count * 4.6 * mm)

        os.makedirs(self.receipts_dir, exist_ok=True)
        filename = os.path.join(self.receipts_dir, f'thermal_{order.id}.pdf')
        c = pdf_canvas.Canvas(filename, pagesize=(width, height))

        y = height - padding - 4 * mm

        def line(text, size=7.5, bold_gap=False, align='left'):
            nonlocal y
            c.setFont(self.font_name, size)
            if align == 'center':
                c.drawCentredString(width / 2, y, text)
            elif align == 'right':
                c.drawRightString(width - padding, y, text)
            else:
                c.drawString(padding, y, text)
            y -= (size + (2.5 if bold_gap else 1.5))

        def separator():
            nonlocal y
            c.setLineWidth(0.4)
            c.line(padding, y + 2, width - padding, y + 2)
            y -= 4

        def pair(left, right, size=7.5):
            nonlocal y
            c.setFont(self.font_name, size)
            c.drawString(padding, y, left)
            c.drawRightString(width - padding, y, right)
            y -= size + 1.5

        company = self.company()
        if company.name:
            line(company.name, size=10, align='center', bold_gap=True)
        if company.slogan:
            line(company.slogan, size=6, align='center')
        if company.phone:
            line(company.phone, size=6, align='center', bold_gap=True)
        separator()

        line(f"Наряд № {order.id}", size=8)
        if order.paid_at:
            line(order.paid_at.strftime('%d.%m.%Y %H:%M'), size=7)
        line(f"Автомобиль: {order.car.license_plate if order.car else '—'}", size=7)
        if order.client and order.client.name:
            line(f"Клиент: {order.client.name}", size=7)
        separator()

        subtotal = 0
        for item in items:
            unit = OrderService.item_unit_price(item)
            item_total = OrderService.item_total(item)
            subtotal += OrderService.item_total_without_discount(item)

            name = item.service.name
            while stringWidth(name, self.font_name, 7.5) > inner and len(name) > 4:
                name = name[:-2]
            line(name, size=7.5)
            pair(f"  {item.quantity} x {unit:.0f}", f"{item_total:.0f} ₽", size=7)

        separator()
        lines_total = sum(OrderService.item_total(i) for i in items)
        final_total = money_round(lines_total)

        pair("Сумма", f"{subtotal:.0f} ₽", size=8)
        discount = subtotal - final_total
        if discount > 0:
            pair("Скидка", f"-{discount:.0f} ₽", size=8)
        pair("ИТОГО", f"{final_total:.0f} ₽", size=10)

        payment = "Наличные" if order.payment_method == "cash" else "Карта"
        line(f"Оплата: {payment}", size=7)

        if order.recommendations and order.recommendations.strip():
            separator()
            line("Рекомендации:", size=7.5)
            for text_line in self._wrap_text(order.recommendations.strip(), inner, 6.5):
                line(text_line, size=6.5)

        separator()
        line("Спасибо за визит!", size=7.5, align='center')

        c.save()
        return filename

    def _wrap_text(self, text, max_width, font_size):
        """
        Разбить текст на строки, влезающие по ширине.

        Считаем по реальной ширине символов выбранного шрифта, а не по
        числу букв: кириллица в DejaVu Sans шире латиницы, и деление
        «по сто символов» вылезало бы за край листа.
        """
        from reportlab.pdfbase.pdfmetrics import stringWidth

        lines = []
        for paragraph in text.split('\n'):
            words = paragraph.split()
            if not words:
                lines.append('')
                continue

            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if stringWidth(candidate, self.font_name, font_size) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)

        return lines

    def generate_receipt(self, order, items, total_amount):
        filename = f"{self.receipts_dir}/receipt_{order.id}.pdf"
        
        c = canvas.Canvas(filename, pagesize=A4)
        width, height = A4
        
        # === ШАПКА С ЛОГОТИПОМ И ИНФОРМАЦИЕЙ О КОМПАНИИ ===
        y = height - 40
        
        # Логотип слева
        try:
            if os.path.exists(self.logo_path):
                from PIL import Image
                import tempfile
                
                # Открываем изображение через PIL
                pil_img = Image.open(self.logo_path)
                
                # Конвертируем в RGB
                if pil_img.mode != 'RGB':
                    pil_img = pil_img.convert('RGB')
                
                # Сохраняем во временный PNG файл
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_png:
                    pil_img.save(tmp_png.name, format='PNG')
                    temp_png_path = tmp_png.name
                
                # Загружаем PNG напрямую
                c.drawImage(temp_png_path, 50, y - 60, width=60, height=60, preserveAspectRatio=True)
                
                # Удаляем временный файл
                try:
                    os.unlink(temp_png_path)
                except:
                    pass
                
                log.debug(f"Логотип успешно загружен через temp PNG: {self.logo_path}")
            else:
                log.error(f"Файл логотипа не найден: {self.logo_path}")
        except Exception as e:
            log.error(f"Ошибка загрузки логотипа: {e}")
            import traceback
            traceback.print_exc()
        
        # Информация о компании справа — из настроек, а не из кода:
        # переезд или смена телефона не должны требовать пересборки
        company = self.company()
        company_x = width - 50
        c.setFont(self.font_name, 10)
        for text_line in company.header_lines():
            c.drawRightString(company_x, y, text_line)
            y -= 15

        # Заголовок по центру под логотипом
        y = height - 110
        if company.name:
            c.setFont(self.font_name, 18)
            c.drawCentredString(width/2, y, company.name)

        y -= 20
        if company.slogan:
            c.setFont(self.font_name, 10)
            c.drawCentredString(width/2, y, company.slogan)

        y -= 30
        c.setFont(self.font_name, 14)
        c.drawCentredString(width/2, y, f"Наряд-заказ № {order.id}")
        
        y -= 20
        c.setFont(self.font_name, 11)
        c.drawCentredString(width/2, y, get_moscow_time().strftime("%d.%m.%Y %H:%M"))
        
        y -= 30
        c.line(50, y, width-50, y)
        
        # Информация о клиенте
        y -= 30
        c.setFont(self.font_name, 12)
        c.drawString(50, y, f"Автомобиль: {order.car.license_plate}")
        c.drawRightString(width-50, y, f"Диаметр: {order.wheel_diameter}")
        
        if order.client:
            y -= 20
            client_info = f"{order.client.name or ''}"
            if order.client.client_number:
                client_info += f" (#{order.client.client_number})"
            c.drawString(50, y, f"Клиент: {client_info}")
        
        y -= 30
        c.line(50, y, width-50, y)
        
        # === ТАБЛИЦА УСЛУГ ===
        y -= 20
        
        # Подготовка данных для таблицы
        table_data = [
            ['Наименование услуги', 'Кол-во', 'Цена', 'Итого']
        ]
        
        # Считаем ровно теми же функциями, что и касса, — иначе строки чека
        # не сходятся с суммой к оплате
        from services.order_service import OrderService

        subtotal_without_discount = 0  # Полная сумма БЕЗ скидок
        lines_total = 0                # Сумма строк таблицы

        for item in items:
            display_price = OrderService.item_unit_price(item)
            item_total = OrderService.item_total(item)

            subtotal_without_discount += OrderService.item_total_without_discount(item)
            lines_total += item_total

            table_data.append([
                item.service.name,
                str(item.quantity),
                f"{display_price:.0f} ₽",  # Целое число
                f"{item_total:.0f} ₽"      # Целое число
            ])
        
        # Создание таблицы с фиксированными размерами колонок
        col_widths = [280, 60, 80, 75]  # ширина колонок
        table = Table(table_data, colWidths=col_widths)
        
        # Стиль таблицы
        table.setStyle(TableStyle([
            # Заголовок
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8F4F8')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), self.font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            
            # Данные
            ('FONTNAME', (0, 1), (-1, -1), self.font_name),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),  # Центр для кол-ва, цены, итого
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),     # Левое для названия
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            
            # Границы
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#2196F3')),
        ]))
        
        # Рисуем таблицу
        table_width, table_height = table.wrap(0, 0)
        table.drawOn(c, 50, y - table_height)
        
        # Обновляем позицию Y
        y = y - table_height - 20
        
        # Итоги.
        # Сумма строк таблицы (lines_total) — это и есть итог к оплате:
        # обе величины считаются одними и теми же функциями. Поэтому
        # «Сумма минус Скидка» всегда сходится с «Итого к оплате».
        final_total = money_round(lines_total)

        y -= 30
        c.setFont(self.font_name, 12)
        c.drawString(50, y, "Сумма:")
        c.drawRightString(width-50, y, f"{subtotal_without_discount:.0f} ₽")

        # Показываем скидку, если она есть
        discount_amount = subtotal_without_discount - final_total
        if discount_amount > 0:  # Показываем только если скидка есть
            y -= 20
            c.drawString(50, y, "Скидка:")
            c.drawRightString(width-50, y, f"-{discount_amount:.0f} ₽")

        y -= 30
        c.setFont(self.font_name, 16)
        c.drawString(50, y, "ИТОГО К ОПЛАТЕ:")
        c.drawRightString(width-50, y, f"{final_total:.0f} ₽")
        
        y -= 10
        c.line(50, y, width-50, y)
        
        # Способ оплаты
        y -= 30
        c.setFont(self.font_name, 12)
        payment_method = "Наличные" if order.payment_method == "cash" else "Карта"
        c.drawString(50, y, f"Способ оплаты: {payment_method}")

        # Рекомендации мастера.
        # Раньше мастер их записывал, а клиент никогда не видел —
        # текст оставался только внутри программы.
        if order.recommendations and order.recommendations.strip():
            y -= 40
            c.setFont(self.font_name, 12)
            c.drawString(50, y, "Рекомендации мастера:")

            y -= 6
            c.setLineWidth(0.5)
            c.line(50, y, width - 50, y)

            c.setFont(self.font_name, 10)
            for line in self._wrap_text(order.recommendations.strip(),
                                        width - 100, 10):
                y -= 15
                c.drawString(50, y, line)
                if y < 140:  # не залезаем на подвал
                    break

        # Подвал
        y = 100
        c.setFont(self.font_name, 10)
        c.drawCentredString(width/2, y, "Спасибо за визит!")
        c.drawCentredString(width/2, y-15, "Будем рады видеть Вас снова!")
        
        c.save()
        return filename
