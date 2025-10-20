from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
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
        
        # Заголовок
        y = height - 50
        c.setFont(self.font_name, 24)
        c.drawCentredString(width/2, y, "Шиномонтаж РИФ")
        
        y -= 30
        c.setFont(self.font_name, 14)
        c.drawCentredString(width/2, y, f"Наряд-заказ № {order.id}")
        
        y -= 20
        c.setFont(self.font_name, 11)
        c.drawCentredString(width/2, y, datetime.now().strftime("%d.%m.%Y %H:%M"))
        
        y -= 40
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
        
        # Заголовок таблицы услуг
        y -= 30
        c.setFont(self.font_name, 12)
        c.drawString(50, y, "Наименование услуги")
        c.drawRightString(width-280, y, "Кол-во")
        c.drawRightString(width-180, y, "Цена")
        c.drawRightString(width-50, y, "Сумма")
        
        y -= 5
        c.line(50, y, width-50, y)
        
        # Услуги
        c.setFont(self.font_name, 11)
        subtotal = 0
        for item in items:
            y -= 25
            service_name = item.service.name[:35]
            quantity = item.quantity
            unit_price = item.price
            
            # Если есть скидка на позицию
            if item.discount_percent > 0:
                discounted_unit_price = unit_price * (1 - item.discount_percent / 100)
                item_total = discounted_unit_price * quantity
                
                c.drawString(50, y, service_name)
                c.drawRightString(width-280, y, f"{quantity}")
                c.setFont(self.font_name, 9)
                c.drawRightString(width-180, y, f"{unit_price:.0f} ₽")
                y -= 12
                c.setFont(self.font_name, 11)
                c.drawRightString(width-180, y, f"{discounted_unit_price:.0f} ₽ (-{item.discount_percent}%)")
                c.drawRightString(width-50, y, f"{item_total:.0f} ₽")
                y -= 13
            else:
                item_total = unit_price * quantity
                
                c.drawString(50, y, service_name)
                c.drawRightString(width-280, y, f"{quantity}")
                c.drawRightString(width-180, y, f"{unit_price:.0f} ₽")
                c.drawRightString(width-50, y, f"{item_total:.0f} ₽")
            
            subtotal += item_total
            
            if item.comment:
                y -= 15
                c.setFont(self.font_name, 9)
                c.drawString(70, y, f"({item.comment[:50]})")
                c.setFont(self.font_name, 11)
        
        y -= 10
        c.line(50, y, width-50, y)
        
        # Итоги
        y -= 30
        c.setFont(self.font_name, 12)
        c.drawString(50, y, "Сумма:")
        c.drawRightString(width-50, y, f"{subtotal:.0f} ₽")
        
        # Применяем ту же логику приоритетов, что и в calculate_total
        # Приоритет: general_discount > auto_discount
        final_discount = 0
        if order.general_discount > 0:
            final_discount = order.general_discount
        elif order.auto_discount:
            final_discount = 5
        
        if final_discount > 0:
            y -= 20
            discount_amount = subtotal - total_amount
            c.drawString(50, y, f"Скидка ({final_discount}%):")
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
