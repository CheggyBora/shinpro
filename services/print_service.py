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

class PrintService:
    def __init__(self):
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
        print(f"Путь к логотипу: {self.logo_path}")
        print(f"Логотип существует: {os.path.exists(self.logo_path)}")
        
        # Регистрируем шрифт DejaVu Sans для PDF с поддержкой кириллицы
        fonts_dir = os.path.join(base_path, "fonts")
        font_path = os.path.join(fonts_dir, 'DejaVuSans.ttf')
        
        try:
            # Регистрируем шрифт только если еще не зарегистрирован
            if 'DejaVuSans' not in pdfmetrics.getRegisteredFontNames():
                if os.path.exists(font_path):
                    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))
                    print(f"✓ Шрифт DejaVuSans зарегистрирован для PDF: {font_path}")
                else:
                    raise FileNotFoundError(f"Файл шрифта не найден: {font_path}")
            
            self.font_name = 'DejaVuSans'
        except Exception as e:
            print(f"✗ Ошибка регистрации шрифта DejaVu: {e}")
            print(f"  Используется Helvetica в качестве резервного шрифта")
            self.font_name = 'Helvetica'
    
    def generate_receipt(self, order, items, total_amount):
        filename = f"{self.receipts_dir}/receipt_{order.id}.pdf"
        
        c = canvas.Canvas(filename, pagesize=A4)
        width, height = A4
        
        # === ШАПКА С ЛОГОТИПОМ И ИНФОРМАЦИЕЙ О КОМПАНИИ ===
        y = height - 40
        
        # Логотип слева
        try:
            if os.path.exists(self.logo_path):
                # Прямой путь к файлу
                c.drawImage(self.logo_path, 50, y - 60, width=60, height=60, preserveAspectRatio=True, mask='auto')
                print(f"✓ Логотип успешно загружен из {self.logo_path}")
            else:
                print(f"✗ Файл логотипа не найден: {self.logo_path}")
        except Exception as e:
            print(f"✗ Ошибка загрузки логотипа: {e}")
            import traceback
            traceback.print_exc()
        
        # Информация о компании справа
        company_x = width - 50
        c.setFont(self.font_name, 10)
        c.drawRightString(company_x, y, "ИП Дюпин Андрей")
        y -= 15
        c.drawRightString(company_x, y, "ИНН 770208926387")
        y -= 15
        c.drawRightString(company_x, y, "115280, г. Москва,")
        y -= 15
        c.drawRightString(company_x, y, "ул. Автозаводская, д. 24 стр. 1")
        y -= 15
        c.drawRightString(company_x, y, "Телефон: +79099018931")
        y -= 15
        c.drawRightString(company_x, y, "email: rifshina@gmail.com")
        
        # Заголовок по центру под логотипом
        y = height - 110
        c.setFont(self.font_name, 18)
        c.drawCentredString(width/2, y, "Шиномонтаж «РИФ»")
        
        y -= 20
        c.setFont(self.font_name, 10)
        c.drawCentredString(width/2, y, "Правка дисков, аргон, покраска")
        
        y -= 30
        c.setFont(self.font_name, 14)
        c.drawCentredString(width/2, y, f"Наряд-заказ № {order.id}")
        
        y -= 20
        c.setFont(self.font_name, 11)
        c.drawCentredString(width/2, y, datetime.now().strftime("%d.%m.%Y %H:%M"))
        
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
        
        subtotal_without_discount = 0  # Полная сумма БЕЗ скидок
        for item in items:
            service_name = item.service.name
            quantity = item.quantity
            unit_price = item.price
            
            # Считаем полную сумму БЕЗ скидок
            subtotal_without_discount += unit_price * quantity
            
            # Если есть скидка на позицию - применяем её для отображения
            if item.discount_percent > 0:
                discounted_unit_price = unit_price * (1 - item.discount_percent / 100)
                item_total = discounted_unit_price * quantity
                display_price = discounted_unit_price
            else:
                item_total = unit_price * quantity
                display_price = unit_price
            
            table_data.append([
                service_name,
                str(quantity),
                f"{display_price:.0f} ₽",
                f"{item_total:.0f} ₽"
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
        
        # Итоги
        y -= 30
        c.setFont(self.font_name, 12)
        c.drawString(50, y, "Сумма:")
        c.drawRightString(width-50, y, f"{subtotal_without_discount:.0f} ₽")
        
        # Показываем скидку, если она есть
        discount_amount = subtotal_without_discount - total_amount
        if discount_amount > 0:
            y -= 20
            c.drawString(50, y, "Скидка:")
            c.drawRightString(width-50, y, f"-{discount_amount:.0f} ₽")
        
        y -= 30
        c.setFont(self.font_name, 16)
        c.drawString(50, y, "ИТОГО К ОПЛАТЕ:")
        c.drawRightString(width-50, y, f"{total_amount:.0f} ₽")
        
        y -= 10
        c.line(50, y, width-50, y)
        
        # Способ оплаты
        y -= 30
        c.setFont(self.font_name, 12)
        payment_method = "Наличные" if order.payment_method == "cash" else "Карта"
        c.drawString(50, y, f"Способ оплаты: {payment_method}")
        
        # Подвал
        y = 100
        c.setFont(self.font_name, 10)
        c.drawCentredString(width/2, y, "Спасибо за визит!")
        c.drawCentredString(width/2, y-15, "Будем рады видеть Вас снова!")
        
        c.save()
        return filename
