"""
QR для отзыва (решение владельца 13.11.2026): при пробитии приёмщик
нажимает «QR для отзыва», поворачивает экран к клиенту — тот сканирует
камерой и попадает на страницу с кнопками «Яндекс Карты», «2ГИС»,
«Отзыв на сайте». Ссылки владелец вписывает в дашборде → «Оформление».

Адрес страницы программа берёт у сервера и помнит: нет связи — QR всё
равно покажем по прошлому адресу.
"""
import tkinter as tk
from tkinter import messagebox

import styles

URL_KEY = 'review_page_url'


def review_url(db):
    """Адрес страницы отзыва. (адрес, есть ли ссылки) — или (None, False)."""
    from services.settings_service import SettingsService
    from services.sync_service import SyncService, SyncError
    settings = SettingsService(db)
    try:
        answer = SyncService(db)._call('GET', '/sync/review-link')
        url = answer.get('url')
        if url:
            settings.set(URL_KEY, url)
        return url, bool(answer.get('has_links'))
    except (SyncError, Exception):
        url = settings.get(URL_KEY)
        return (url, True) if url else (None, False)


def qr_image(url, size=420):
    """Картинка QR для окна (PIL → Tk)."""
    import qrcode
    from PIL import ImageTk
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=10)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color='black', back_color='white').convert('RGB')
    image = image.resize((size, size))
    return ImageTk.PhotoImage(image)


def show(parent, db):
    url, has_links = review_url(db)
    if not url:
        messagebox.showinfo('QR для отзыва', 'Нет связи с сервером, а адреса страницы отзыва программа '
                                             'ещё не знает. Проверьте обмен (Настройки → «Связь»).',
                            parent=parent)
        return None
    if not has_links:
        messagebox.showinfo('QR для отзыва', 'Ссылки на отзывы не вписаны: дашборд → «Оформление» → '
                                             '«Ссылки на отзывы».', parent=parent)
        return None
    from services.company_service import get_company
    window = tk.Toplevel(parent)
    window.title('Отзыв')
    window.configure(bg='#ffffff')
    window.transient(parent.winfo_toplevel())
    name = get_company(db).name or ''
    tk.Label(window, text=f'Спасибо, что заехали{" в «" + name + "»" if name else ""}!', bg='#ffffff',
             fg='#0f172a', font=(styles.DEFAULT_FONT, 20, 'bold')).pack(padx=30, pady=(24, 4))
    tk.Label(window, text='Наведите камеру телефона на код — оставьте отзыв', bg='#ffffff',
             fg='#475569', font=(styles.DEFAULT_FONT, 14)).pack(padx=30)
    # Окно целиком на экране: QR по высоте монитора
    picture = qr_image(url, size=max(240, min(420, window.winfo_screenheight() - 330)))
    label = tk.Label(window, image=picture, bg='#ffffff')
    label.image = picture
    label.pack(padx=30, pady=16)
    styles.create_button(window, 'Закрыть', window.destroy, 'Secondary.TButton').pack(pady=(0, 20))
    window.url = url
    styles.center_window(window, parent.winfo_toplevel())
    window.lift()
    return window
