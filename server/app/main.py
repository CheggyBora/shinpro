"""
Сервер приложения клиентов.

Запуск для разработки:

    python -m uvicorn app.main:app --reload

Описание всех запросов открывается на /docs — по нему же удобно
проверять сервер руками, не собирая приложение.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(name)s  %(message)s',
    datefmt='%d.%m.%Y %H:%M:%S')

log = logging.getLogger('tire_server')


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # О недостающих настройках говорим сразу и громко: сервер,
    # поднятый наполовину, хуже не поднятого — он делает вид,
    # что работает
    # Первый владелец дашборда. Завести его из самого дашборда нельзя:
    # заводить людей имеет право только владелец, а его ещё нет
    if settings.OWNER_PHONE:
        from app.database import SessionLocal
        from app.services.staff_service import StaffService

        session = SessionLocal()
        try:
            owner = StaffService(session).ensure_owner(
                settings.OWNER_PHONE, settings.OWNER_NAME)
            if owner is None:
                log.warning('SERVER_OWNER_PHONE не похож на номер телефона')
        except Exception as e:
            log.error('Не удалось завести владельца дашборда: %s', e)
        finally:
            session.close()

    problems = settings.warnings()
    if problems:
        log.warning('Сервер запущен с ограничениями:')
        for problem in problems:
            log.warning('  · %s', problem)

    log.info('Сервер готов')
    yield
    log.info('Сервер остановлен')


app = FastAPI(
    title='Шиномонтаж — сервер приложения',
    description='Запись, хранение шин, история визитов и очередь '
                'для мобильного приложения клиента.',
    version='1.0.0',
    lifespan=lifespan,
)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

from app.api import (auth, booking, storage, history, queue, sync, public,  # noqa: E402
                     staff)

app.include_router(auth.router)
app.include_router(booking.router)
app.include_router(storage.router)
app.include_router(history.router)
app.include_router(queue.router)
app.include_router(sync.router)
app.include_router(staff.router)
app.include_router(public.router)


# ----------------------------------------------------------------------
# Страница записи по ссылке
# ----------------------------------------------------------------------
import os  # noqa: E402

from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')


@app.get('/z', response_class=HTMLResponse, include_in_schema=False)
def booking_page():
    """
    Страница записи. Короткий адрес — её отправляют в переписке,
    и «/z» помещается даже в SMS.
    """
    path = os.path.join(WEB_DIR, 'booking.html')
    with open(path, encoding='utf-8') as page:
        return HTMLResponse(page.read())


@app.get('/z/logo.jpg', include_in_schema=False)
def booking_logo():
    """Логотип шиномонтажа. Нет файла — страница просто обойдётся без него."""
    path = os.environ.get('SERVER_LOGO_PATH') or os.path.join(WEB_DIR, 'logo.jpg')
    if not os.path.exists(path):
        return HTMLResponse(status_code=404, content='')
    return FileResponse(path, media_type='image/jpeg',
                        headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/health', tags=['Служебное'], summary='Жив ли сервер')
def health():
    """Проверка для мониторинга: отвечает ли сервер и видит ли базу."""
    from app.database import SessionLocal
    from sqlalchemy import text

    database_ok = True
    try:
        db = SessionLocal()
        db.execute(text('SELECT 1'))
        db.close()
    except Exception as e:
        log.error('База недоступна: %s', e)
        database_ok = False

    return {'ok': database_ok, 'database': database_ok}
