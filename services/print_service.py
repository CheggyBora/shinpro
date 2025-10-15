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
    
    def generate_receipt(self, order, items, total_amount):
        filename = f"{self.receipts_dir}/receipt_{order.id}.pdf"
        
        c = canvas.Canvas(filename, pagesize=(80*mm, 200*mm))
        
        y = 190*mm
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(40*mm, y, "SHINOMONT")
        
        y -= 10*mm
        c.setFont("Helvetica", 9)
        c.drawCentredString(40*mm, y, f"Naryad #{order.id}")
        
        y -= 5*mm
        c.drawCentredString(40*mm, y, datetime.now().strftime("%d.%m.%Y %H:%M"))
        
        y -= 8*mm
        c.drawString(5*mm, y, f"Auto: {order.car.license_plate}")
        
        if order.client:
            y -= 5*mm
            client_info = f"{order.client.name or ''}"
            if order.client.client_number:
                client_info += f" (#{order.client.client_number})"
            c.drawString(5*mm, y, f"Client: {client_info}")
        
        y -= 5*mm
        c.drawString(5*mm, y, f"Diametr: {order.wheel_diameter}")
        
        y -= 8*mm
        c.line(5*mm, y, 75*mm, y)
        
        y -= 5*mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(5*mm, y, "SERVICES:")
        
        c.setFont("Helvetica", 8)
        subtotal = 0
        for item in items:
            y -= 5*mm
            c.drawString(5*mm, y, item.service.name[:30])
            
            item_price = item.price * (1 - item.discount_percent / 100)
            subtotal += item_price
            
            y -= 4*mm
            price_str = f"{item.price:.2f} rub"
            if item.discount_percent > 0:
                price_str += f" (discount {item.discount_percent}%)"
            c.drawString(8*mm, y, price_str)
            
            if item.comment:
                y -= 4*mm
                c.drawString(8*mm, y, f"Note: {item.comment[:25]}")
        
        y -= 6*mm
        c.line(5*mm, y, 75*mm, y)
        
        y -= 5*mm
        c.drawString(5*mm, y, f"Subtotal: {subtotal:.2f} rub")
        
        if order.general_discount > 0:
            y -= 4*mm
            discount_amount = subtotal * (order.general_discount / 100)
            c.drawString(5*mm, y, f"Discount {order.general_discount}%: -{discount_amount:.2f} rub")
        
        if order.auto_discount:
            y -= 4*mm
            auto_discount_amount = (subtotal - (subtotal * order.general_discount / 100)) * 0.05
            c.drawString(5*mm, y, f"Auto discount 5%: -{auto_discount_amount:.2f} rub")
        
        y -= 6*mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(5*mm, y, f"TOTAL: {total_amount:.2f} rub")
        
        y -= 6*mm
        c.line(5*mm, y, 75*mm, y)
        
        y -= 5*mm
        c.setFont("Helvetica", 9)
        payment_method = "Cash" if order.payment_method == "cash" else "Card"
        c.drawString(5*mm, y, f"Payment: {payment_method}")
        
        y -= 10*mm
        c.setFont("Helvetica", 8)
        c.drawCentredString(40*mm, y, "Thank you!")
        
        c.save()
        return filename
