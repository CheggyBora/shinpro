"""
Табличка с QR «Встать в очередь» — для печати у въезда.

    python tools/queue_poster.py https://lk.rif-service.ru/z/testovaya-tochka/q

Делает A4 (PNG 300 dpi и PDF) в docs/print/. Ссылка — страница живой
очереди точки: /z/<точка>/q (docs/live_queue.md).
"""
import os
import sys

import qrcode
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, 'fonts', 'DejaVuSans.ttf')
RED = (227, 38, 47)
INK = (21, 24, 29)
MUTED = (93, 100, 112)

W, H = 2480, 3508          # A4, 300 dpi


def font(size):
    return ImageFont.truetype(FONT, size)


def centered(draw, y, text, size, fill=INK):
    f = font(size)
    width = draw.textlength(text, font=f)
    draw.text(((W - width) / 2, y), text, font=f, fill=fill)
    return y + size


def make(url, out_dir):
    page = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(page)

    # Красная полоса с логотипом
    draw.rectangle((0, 0, W, 420), fill=RED)
    centered(draw, 120, 'РИФ · ШИНОМОНТАЖ', 150, fill='white')

    y = 600
    y = centered(draw, y, 'Встать в очередь', 210) + 60
    y = centered(draw, y, 'Наведите камеру телефона на код', 90, fill=MUTED) + 120

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=40, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    side = 1500
    image = image.resize((side, side), Image.NEAREST)
    page.paste(image, ((W - side) // 2, y))
    y += side + 110

    y = centered(draw, y, 'Номер машины, телефон, диаметр — и вы в очереди.', 70) + 40
    y = centered(draw, y, 'Когда подойдёт ваша, на телефоне появится', 70, fill=MUTED) + 20
    y = centered(draw, y, 'номер поста и схема, куда ехать.', 70, fill=MUTED) + 120
    centered(draw, y, url.replace('https://', ''), 60, fill=MUTED)

    os.makedirs(out_dir, exist_ok=True)
    slug = url.rstrip('/').split('/')[-2] if url.rstrip('/').endswith('/q') else 'queue'
    png = os.path.join(out_dir, f'qr_queue_{slug}.png')
    pdf = os.path.join(out_dir, f'qr_queue_{slug}.pdf')
    page.save(png, dpi=(300, 300))
    page.save(pdf, resolution=300)
    return png, pdf


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for path in make(sys.argv[1], os.path.join(ROOT, 'docs', 'print')):
        print(path)
