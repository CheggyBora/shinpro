"""
Страница отзыва по QR (решение владельца 13.11.2026).

При пробитии наряда приёмщик показывает клиенту QR на экране — тот
сканирует и попадает сюда: название шиномонтажа и крупные кнопки
«Яндекс Карты», «2ГИС», «Отзыв на сайте». Ссылки владелец вписал в
дашборде → «Оформление». Страница без входа.

Программа цеха берёт адрес страницы через /sync/review-link: на адресе
записи организации (koleso.rif-service.ru), а не на служебном.
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.photos import WEB_DIR
from app.database import get_db
from app.models import Account
from app.security import require_sync_key
from app.services import branding, reviews, tenancy

router = APIRouter(tags=['Отзыв по QR'])


def _shop(db, slug):
    shop = tenancy.shop_by_slug(db, slug)
    if shop is None or not shop.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Такого шиномонтажа нет')
    return shop


@router.get('/otzyv/{slug}', response_class=HTMLResponse, include_in_schema=False)
def page(slug: str):
    with open(os.path.join(WEB_DIR, 'review.html'), encoding='utf-8') as source:
        return source.read()


@router.get('/public/review/{slug}', include_in_schema=False)
def data(slug: str, db: Session = Depends(get_db)):
    shop = _shop(db, slug)
    account = db.get(Account, shop.account_id) if shop.account_id else None
    brand = branding.brand_of(db, account, shop)
    links = reviews.links_of(account)
    return {'name': brand['name'], 'color': brand['color'],
            'links': [{'key': key, 'title': reviews.TITLES[key], 'url': url} for key, url in links.items()]}


@router.get('/sync/review-link', summary='Адрес страницы отзыва для QR')
def link(request: Request, shop=Depends(require_sync_key), db: Session = Depends(get_db)):
    account = db.get(Account, shop.account_id) if shop.account_id else None
    host = tenancy.our_names(account).get('lk') if account is not None else None
    if not host:
        host = (request.headers.get('x-forwarded-host') or request.headers.get('host') or '').split(',')[0].strip()
    return {'url': f'https://{host}/otzyv/{shop.slug}',
            'has_links': bool(reviews.links_of(account))}
