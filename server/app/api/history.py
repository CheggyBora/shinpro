"""История визитов и рекомендации мастера."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Client, Visit
from app.schemas import VisitOut
from app.security import current_client
from app.utils import normalize_plate

router = APIRouter(prefix='/history', tags=['История'])


def _to_public(visit):
    services = []
    if visit.services:
        services = [line.strip() for line in visit.services.split('\n')
                    if line.strip()]

    return VisitOut(
        id=visit.id,
        at=visit.visited_at,
        license_plate=visit.license_plate,
        total_amount=visit.total_amount,
        services=services,
        recommendations=visit.recommendations,
        is_warranty=visit.is_warranty)


@router.get('', response_model=List[VisitOut], summary='Мои визиты')
def visits(license_plate: Optional[str] = Query(
               None, description='Показать только по этой машине'),
           limit: int = Query(50, le=200),
           client: Client = Depends(current_client),
           db: Session = Depends(get_db)):
    # Удалённый наряд клиенту не показываем: в цеху его вычеркнули,
    # и в кабинете он не должен висеть как состоявшийся визит
    query = db.query(Visit).filter(Visit.client_id == client.id,
                                   Visit.is_deleted.is_(False))

    plate = normalize_plate(license_plate)
    if plate:
        query = query.filter(Visit.license_plate == plate)

    rows = query.order_by(Visit.visited_at.desc()).limit(limit).all()
    return [_to_public(row) for row in rows]


@router.get('/recommendations', response_model=List[VisitOut],
            summary='Только визиты с рекомендациями мастера')
def recommendations(limit: int = Query(20, le=100),
                    client: Client = Depends(current_client),
                    db: Session = Depends(get_db)):
    """
    Что советовал мастер в прошлые разы.

    Отдельный список нужен, потому что рекомендация — единственное,
    ради чего клиент открывает историю месяцы спустя: «мне что-то
    говорили про задние колодки, а что?»
    """
    rows = db.query(Visit).filter(
        Visit.client_id == client.id,
        Visit.is_deleted.is_(False),
        Visit.recommendations.isnot(None),
        Visit.recommendations != '',
    ).order_by(Visit.visited_at.desc()).limit(limit).all()

    return [_to_public(row) for row in rows]


@router.get('/photos', summary='Фото из цеха')
def photos(limit: int = Query(30, le=100),
           client: Client = Depends(current_client),
           db: Session = Depends(get_db)):
    """
    Снимки, которые прислал мастер.

    Клиент видит их в кабинете: уведомление он мог пропустить, а
    фотография грыжи на боковине нужна ему, когда он решает, менять
    колесо или ездить дальше.

    Ссылку на сам файл отдаём подписанной одноразовым ключом: картинки
    лежат на диске, и открытый адрес означал бы, что чужое фото можно
    посмотреть, подобрав номер.
    """
    from app.models import OrderPhoto
    from app.security import photo_key

    rows = db.query(OrderPhoto).filter(
        OrderPhoto.client_id == client.id,
        OrderPhoto.sent_at.isnot(None)).order_by(
        OrderPhoto.created_at.desc()).limit(limit).all()

    return [{
        'id': row.id,
        'at': row.created_at,
        'license_plate': row.license_plate,
        'comment': row.comment,
        'url': f'/history/photo/{row.id}?key={photo_key(row.id, client.id)}',
    } for row in rows]


@router.get('/photo/{photo_id}', include_in_schema=False)
def photo_file(photo_id: int, key: str = '', db: Session = Depends(get_db)):
    """
    Сам снимок. Ключ в ссылке проверяем сами, без входа по токену:
    браузер подставляет адрес картинки в <img>, а туда заголовок
    с токеном не положить.
    """
    import os

    from fastapi import HTTPException, status
    from fastapi.responses import FileResponse

    from app.models import OrderPhoto
    from app.security import photo_key
    from app.services import photos as photo_service

    row = db.query(OrderPhoto).filter(OrderPhoto.id == photo_id).first()
    if row is None or row.client_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Фото не найдено')

    if key != photo_key(row.id, row.client_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail='Нельзя')

    path = photo_service.full_path(row)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail='Файл не найден')

    return FileResponse(path, media_type='image/jpeg',
                        headers={'Cache-Control': 'private, max-age=86400'})
