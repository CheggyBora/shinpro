"""
Комплект привезли со склада (решение владельца 13.11.2026).

Приёмщик нажимает «Приехало» в программе цеха — клиенту приходит:
«Колёса приехали. Не забудьте: вы записаны на 16.11 в 10:00». В
Telegram или уведомлением кабинета — как остальные напоминания.
"""
from app.models import KIND_ARRIVED, Appointment
from app.services import notices, shop_settings
from app.utils import now as shop_now
from app.services.tasks import set_title


def _appointment(db, row):
    """Запись клиента, к которой везли комплект: ближайшая впереди."""
    if row.client_id is None:
        return None
    return db.query(Appointment).filter(
        Appointment.client_id == row.client_id, Appointment.shop_id == row.shop_id,
        Appointment.status == 'scheduled', Appointment.scheduled_at >= shop_now()).order_by(
        Appointment.scheduled_at).first()


def text_for(shop_name, row, when):
    what = set_title(row)
    text = f'<b>Колёса приехали</b> в «{shop_name}»: {what}.'
    if when is not None and when >= shop_now():
        clock = '' if when.hour == 0 and when.minute == 0 else f' в {when:%H:%M}'
        text += f'\nНе забудьте: вы записаны на {when:%d.%m}{clock}. Ждём вас!'
    else:
        text += '\nМожно приезжать.'
    return text


def tell_client(db, shop, row):
    client = row.client
    if client is None:
        return None
    appointment = _appointment(db, row)
    when = appointment.scheduled_at if appointment is not None else row.requested_for
    name = shop_settings.get(db, 'shop_name', shop=shop) or shop.name or 'Шиномонтаж'
    return notices.add(db, client, KIND_ARRIVED, text_for(name, row, when),
                       about='storage', about_id=row.id)
