"""
Отзывы клиентов (решения владельца 13.11.2026).

Площадки — свой список организации: название и ссылка (Яндекс Карты,
2ГИС, Google Карты, Авито, сайт — любые). Владелец ведёт его в дашборде
→ «Оформление» → «Площадки для отзывов».

Два пути к клиенту:
  · QR при пробитии — приёмщик показывает код на экране, клиент
    сканирует и попадает на страницу с кнопками площадок (api/review.py);
  · галочка «Предложить оставить отзыв» при оплате — через час в личном
    кабинете клиента появляется карточка «Оставьте отзыв», а если он
    подключён к боту или уведомлениям — ещё и сообщение.

Пауза — чтобы человек успел уехать: просьба у кассы раздражает.
"""
import json
from datetime import timedelta

from app.models import Account, KIND_REVIEW
from app.utils import now as shop_now

DELAY = timedelta(hours=1)
# Карточка в кабинете висит, пока клиент её не закрыл, но не дольше
SHOW_DAYS = 14
LIMIT = 8
# Подсказки в дашборде — чтобы не вспоминать, как пишется
SUGGESTED = ['Яндекс Карты', '2ГИС', 'Google Карты', 'Отзыв на сайте', 'Авито', 'ВКонтакте']
# Старый формат (13.11.2026, до своего списка): ключ → название
_OLD_TITLES = {'yandex': 'Яндекс Карты', 'gis': '2ГИС', 'site': 'Наш сайт'}


def _url(value):
    value = (value or '').strip()
    if value and not value.startswith(('http://', 'https://')):
        value = 'https://' + value
    return value[:500]


def links_of(account):
    """Площадки организации: [{'title', 'url'}] в порядке владельца."""
    try:
        data = json.loads(account.review_links or '[]') if account is not None else []
    except ValueError:
        data = []
    if isinstance(data, dict):
        data = [{'title': _OLD_TITLES.get(key, key), 'url': url} for key, url in data.items()]
    result = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and (item.get('url') or '').strip():
            result.append({'title': (item.get('title') or 'Отзыв').strip()[:60],
                           'url': _url(item.get('url'))})
    return result[:LIMIT]


def set_links(db, account, links):
    """Сохранить площадки. Принимает список [{'title', 'url'}] (или старый словарь)."""
    if isinstance(links, dict):
        links = [{'title': _OLD_TITLES.get(key, key), 'url': url} for key, url in links.items()]
    clean = []
    for item in links or []:
        if not isinstance(item, dict):
            continue
        url = _url(item.get('url'))
        if not url:
            continue
        clean.append({'title': ((item.get('title') or '').strip() or 'Отзыв')[:60], 'url': url})
    account.review_links = json.dumps(clean[:LIMIT], ensure_ascii=False) if clean else None
    db.commit()
    return links_of(account)


def text_for(shop_name, links):
    parts = [f'<a href="{item["url"]}">{item["title"]}</a>' for item in links]
    return (f'<b>Спасибо, что заехали в «{shop_name}»!</b>\n'
            f'Будем благодарны за отзыв — это займёт минуту:\n' + ' · '.join(parts))


def plan(db, shop, visit, client):
    """Галочка при оплате: через час — карточка в кабинете и сообщение."""
    from app.services import notices
    account = db.get(Account, shop.account_id) if shop.account_id else None
    links = links_of(account)
    visit.review_planned_at = shop_now()
    if client is None or not links:
        return None
    return notices.add(db, client, KIND_REVIEW, text_for(shop.name, links),
                       send_at=shop_now() + DELAY, about='visit', about_id=visit.id)


def for_client(db, client):
    """Карточка «Оставьте отзыв» в кабинете: последний наряд с галочкой."""
    from app.models import Shop, Visit
    now = shop_now()
    visit = db.query(Visit).filter(
        Visit.client_id == client.id, Visit.ask_review.is_(True),
        Visit.review_closed_at.is_(None), Visit.is_deleted.is_(False),
        Visit.review_planned_at.isnot(None),
        Visit.review_planned_at <= now - DELAY,
        Visit.review_planned_at >= now - timedelta(days=SHOW_DAYS)).order_by(
        Visit.review_planned_at.desc()).first()
    if visit is None:
        return None
    shop = db.get(Shop, visit.shop_id)
    account = db.get(Account, shop.account_id) if shop is not None and shop.account_id else None
    links = links_of(account)
    if not links:
        return None
    return {'visit_id': visit.id, 'shop': shop.name if shop else '', 'links': links}


def close_for_client(db, client, visit_id):
    from app.models import Visit
    visit = db.query(Visit).filter(Visit.id == visit_id, Visit.client_id == client.id).first()
    if visit is not None and visit.review_closed_at is None:
        visit.review_closed_at = shop_now()
        db.commit()
    return {'ok': True}
