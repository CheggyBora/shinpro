"""
Отзывы клиентов (решение владельца 13.11.2026).

Только с пометкой: приёмщик при оплате наряда ставит галочку
«Предложить оставить отзыв». Через пару часов после оплаты клиенту —
в Telegram или уведомлением кабинета — «спасибо» и ссылки, куда
оставить отзыв: Яндекс Карты, 2ГИС, сайт. Ссылки владелец вписывает в
дашборде → «Оформление».

Пауза — чтобы человек успел доехать: просьба об отзыве у кассы
раздражает, а вечером того же дня — уместна.
"""
import json
from datetime import timedelta

from app.models import Account, KIND_REVIEW
from app.utils import now as shop_now

DELAY = timedelta(hours=2)
TITLES = {'yandex': 'Яндекс Карты', 'gis': '2ГИС', 'site': 'Наш сайт'}


def links_of(account):
    try:
        data = json.loads(account.review_links or '{}') if account is not None else {}
    except ValueError:
        data = {}
    return {key: (data.get(key) or '').strip() for key in TITLES if (data.get(key) or '').strip()}


def set_links(db, account, links):
    clean = {}
    for key in TITLES:
        value = (links.get(key) or '').strip()
        if value and not value.startswith(('http://', 'https://')):
            value = 'https://' + value
        if value:
            clean[key] = value[:500]
    account.review_links = json.dumps(clean, ensure_ascii=False) if clean else None
    db.commit()
    return links_of(account)


def text_for(shop_name, links):
    parts = [f'<a href="{url}">{TITLES[key]}</a>' for key, url in links.items()]
    return (f'<b>Спасибо, что заехали в «{shop_name}»!</b>\n'
            f'Будем благодарны за отзыв — это займёт минуту:\n' + ' · '.join(parts))


def plan(db, shop, visit, client):
    """Поставить «спасибо и ссылки» клиенту наряда — один раз на наряд."""
    from app.services import notices
    account = db.get(Account, shop.account_id) if shop.account_id else None
    links = links_of(account)
    visit.review_planned_at = shop_now()
    if client is None or not links:
        return None
    return notices.add(db, client, KIND_REVIEW, text_for(shop.name, links),
                       send_at=shop_now() + DELAY, about='visit', about_id=visit.id)
