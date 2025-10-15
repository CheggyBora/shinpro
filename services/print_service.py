from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime
import os
import sys

class PrintService:
    def __init__(self):
        # Определяем базовый путь для EXE или обычного запуска
        if getattr(sys, 'frozen', False):
            # Если запущен как EXE (PyInstaller)
            base_path = os.path.dirname(sys.executable)
        else:
            # Если запущен как скрипт
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        self.receipts_dir = os.path.join(base_path, "receipts")
        if not os.path.exists(self.receipts_dir):
            os.makedirs(self.receipts_dir)
        
        # Регистрируем русский шрифт для PDF (только если еще не зарегистрирован)
        font_path = os.path.join(base_path, "fonts", "DejaVuSans.ttf")
        print(f"PDF шрифт - базовый путь: {base_path}")
        print(f"PDF шрифт - полный путь: {font_path}")
        print(f"PDF шрифт - файл существует: {os.path.exists(font_path)}")
        
        if os.path.exists(font_path):
            try:
                # Проверяем, зарегистрирован ли уже шрифт
                if 'DejaVu' not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont('DejaVu', font_path))
                    print(f"✓ PDF шрифт DejaVu зарегистрирован")
                else:
                    print(f"✓ PDF шрифт DejaVu уже зарегистрирован")
                self.font_name = 'DejaVu'
            except Exception as e:
                print(f"✗ Ошибка регистрации PDF шрифта: {e}")
                self.font_name = 'Helvetica'
        else:
            print(f"✗ Файл шрифта не найден, используется Helvetica")
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
        c.drawRightString(width-200, y, "Кол-во")
        c.drawRightString(width-50, y, "Цена")
        
        y -= 5
        c.line(50, y, width-50, y)
        
        # Услуги
        c.setFont(self.font_name, 11)
        subtotal = 0
        for item in items:
            y -= 25
            service_name = item.service.name[:45]
            quantity = 1
            item_price = item.price * (1 - item.discount_percent / 100)
            subtotal += item_price
            
            c.drawString(50, y, service_name)
            c.drawRightString(width-200, y, f"{quantity}")
            c.drawRightString(width-50, y, f"{item_price:.0f} ₽")
            
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
        
        total_discount = 0
        if order.general_discount > 0:
            total_discount += order.general_discount
        if order.auto_discount:
            total_discount += 5
        
        if total_discount > 0:
            y -= 20
            c.drawString(50, y, f"Скидка ({total_discount}%):")
            discount_amount = subtotal - total_amount
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
