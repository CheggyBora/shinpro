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
    query = db.query(Visit).filter(Visit.client_id == client.id)

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
        Visit.recommendations.isnot(None),
        Visit.recommendations != '',
    ).order_by(Visit.visited_at.desc()).limit(limit).all()

    return [_to_public(row) for row in rows]
