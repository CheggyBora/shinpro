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
        
        # Регистрируем русский шрифт
        font_path = os.path.join(base_path, "fonts", "DejaVuSans.ttf")
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('DejaVu', font_path))
            self.font_name = 'DejaVu'
        else:
            self.font_name = 'Helvetica'
    
    def generate_receipt(self, order, items, total_amount):
        filename = f"{self.receipts_dir}/receipt_{order.id}.pdf"
        
        c = canvas.Canvas(filename, pagesize=(80*mm, 200*mm))
        
        y = 190*mm
        c.setFont(self.font_name, 12)
        c.drawCentredString(40*mm, y, "Шиномонтаж РИФ")
        
        y -= 10*mm
        c.setFont(self.font_name, 9)
        c.drawCentredString(40*mm, y, f"Наряд #{order.id}")
        
        y -= 5*mm
        c.drawCentredString(40*mm, y, datetime.now().strftime("%d.%m.%Y %H:%M"))
        
        y -= 8*mm
        c.drawString(5*mm, y, f"Авто: {order.car.license_plate}")
        
        if order.client:
            y -= 5*mm
            client_info = f"{order.client.name or ''}"
            if order.client.client_number:
                client_info += f" (#{order.client.client_number})"
            c.drawString(5*mm, y, f"Клиент: {client_info}")
        
        y -= 5*mm
        c.drawString(5*mm, y, f"Диаметр: {order.wheel_diameter}")
        
        y -= 8*mm
        c.line(5*mm, y, 75*mm, y)
        
        y -= 5*mm
        c.setFont(self.font_name, 9)
        c.drawString(5*mm, y, "Услуги:")
        
        c.setFont(self.font_name, 8)
        subtotal = 0
        for item in items:
            y -= 5*mm
            service_name = item.service.name[:25]
            quantity = 1
            item_price = item.price * (1 - item.discount_percent / 100)
            subtotal += item_price
            
            line = f"{service_name} x{quantity} - {item_price:.0f}р"
            c.drawString(5*mm, y, line)
            
            if item.comment:
                y -= 4*mm
                c.drawString(8*mm, y, f"  ({item.comment[:20]})")
        
        y -= 6*mm
        c.line(5*mm, y, 75*mm, y)
        
        y -= 5*mm
        c.setFont(self.font_name, 9)
        c.drawString(5*mm, y, f"Сумма: {subtotal:.0f}р")
        
        total_discount = 0
        if order.general_discount > 0:
            total_discount += order.general_discount
        if order.auto_discount:
            total_discount += 5
        
        if total_discount > 0:
            y -= 4*mm
            c.drawString(5*mm, y, f"Скидка: {total_discount}%")
        
        y -= 6*mm
        c.setFont(self.font_name, 11)
        c.drawString(5*mm, y, f"ИТОГО: {total_amount:.0f}р")
        
        y -= 6*mm
        c.line(5*mm, y, 75*mm, y)
        
        y -= 5*mm
        c.setFont(self.font_name, 9)
        payment_method = "Наличные" if order.payment_method == "cash" else "Карта"
        c.drawString(5*mm, y, f"Оплата: {payment_method}")
        
        y -= 10*mm
        c.setFont(self.font_name, 8)
        c.drawCentredString(40*mm, y, "Спасибо за визит!")
        
        c.save()
        return filename
