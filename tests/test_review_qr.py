"""
QR для отзыва при пробитии (решение владельца 13.11.2026).

  · кнопка в окне оплаты открывает большой QR со страницей отзыва;
  · адрес программа берёт у сервера и помнит: нет связи — QR по прошлому;
  · ссылки не вписаны — подсказка, куда их вписать.
"""
import _setup
from _setup import use_temp_db, check, finish

use_temp_db('review_qr')
shown = _setup.silence_dialogs()

import tkinter as tk
from config import init_db, SessionLocal
from services.sync_service import SyncService, SyncError
from ui import review_qr

init_db()
db = SessionLocal()
root = tk.Tk()
answers = [{'url': 'https://rif.rif-service.ru/otzyv/rif', 'has_links': True}]


def fake_call(self, method, path, payload=None, raw=False):
    if not answers:
        raise SyncError('Нет связи с сервером')
    return answers[0]


SyncService._call = fake_call

window = review_qr.show(root, db)
check('окно с QR открылось на адрес страницы отзыва', window is not None
      and window.url == 'https://rif.rif-service.ru/otzyv/rif')
window.destroy()

answers.clear()
window = review_qr.show(root, db)
check('нет связи — QR по запомненному адресу', window is not None
      and window.url == 'https://rif.rif-service.ru/otzyv/rif')
window.destroy()

answers.append({'url': 'https://rif.rif-service.ru/otzyv/rif', 'has_links': False})
window = review_qr.show(root, db)
check('ссылок нет — подсказка про дашборд', window is None and shown
      and 'Оформление' in str(shown[-1]), str(shown[-1:]))

print('\n=== Кнопка в окне оплаты ===')
source = open(review_qr.__file__.replace('review_qr.py', 'order_screen/payment.py'), encoding='utf-8').read()
check('в окне оплаты кнопка «QR для отзыва»', 'QR для отзыва — показать клиенту' in source)

root.destroy()
db.close()
finish()
