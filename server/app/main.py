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

    # Первая точка: аккаунт и ключ обмена из настроек
    from app.database import SessionLocal as _Session
    from app.services import tenancy

    session = _Session()
    try:
        shop = tenancy.bootstrap(session)
        if shop is not None:
            log.info('Заведена первая точка: %s (%s)', shop.name, shop.slug)
    except Exception as e:
        log.error('Не удалось завести первую точку: %s', e)
    finally:
        session.close()

    # Первый владелец дашборда. Завести его из самого дашборда нельзя:
    # заводить людей имеет право только владелец, а его ещё нет
    if settings.OWNER_PHONE:
        from app.database import SessionLocal
        from app.services.staff_service import StaffService

        session = SessionLocal()
        try:
            # Владелец заводится в том аккаунте, который создан выше:
            # без аккаунта учётка повиснет ни на чём
            from app.services import tenancy as _tenancy

            # Владелец — того, кто держит сервер. account_for при
            # второй организации отказал бы: адреса у запуска нет
            home = _tenancy.home_account(session)
            account_id = home.id if home is not None else None

            # Без заказчика владельца не заводим вовсе. Иначе учётка
            # повиснет ни на чём: войти по ней можно, а данных не
            # видно — дашборд отбирает их по заказчику, которого у
            # неё нет. А когда заказчик появится, при следующем
            # запуске заведётся вторая учётка с тем же телефоном, и
            # какая из них ответит на входе — как повезёт
            if account_id is None:
                log.warning('Владелец дашборда не заведён: сначала нужен '
                            'заказчик — manage.py add-account "Название"')
            else:
                owner = StaffService(session, account_id).ensure_owner(
                    settings.OWNER_PHONE, settings.OWNER_NAME)
                if owner is None:
                    log.warning('SERVER_OWNER_PHONE не похож на номер телефона')
        except Exception as e:
            log.error('Не удалось завести владельца дашборда: %s', e)
        finally:
            session.close()

    # О недостающих настройках говорим сразу и громко: сервер,
    # поднятый наполовину, хуже не поднятого — он делает вид,
    # что работает
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

class _RequestHost:
    """
    Запоминает адрес, на который зашли: по нему ясно, чей кабинет
    открыт — у каждой организации свой (tenancy.host_target).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return

        from app.services import tenancy as _tenancy
        host = dict(scope.get('headers') or []).get(b'host', b'').decode('latin-1')
        token = _tenancy.REQUEST_HOST.set(host)
        try:
            await self.app(scope, receive, send)
        finally:
            _tenancy.REQUEST_HOST.reset(token)


app.add_middleware(_RequestHost)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

from app.api import (auth, booking, storage, history, queue, sync, public,  # noqa: E402
                     photos, live, tasks, stock, cash,
                     staff, dashboard, telegram, push, branding)

app.include_router(auth.router)
app.include_router(booking.router)
app.include_router(storage.router)
app.include_router(history.router)
app.include_router(queue.router)
app.include_router(sync.router)
app.include_router(staff.router)
app.include_router(dashboard.router)
app.include_router(branding.router)
app.include_router(telegram.router)
app.include_router(push.router)
app.include_router(public.router)
app.include_router(photos.router)
app.include_router(live.router)
app.include_router(live.sync_router)
app.include_router(tasks.sync_router)
app.include_router(tasks.router)
app.include_router(stock.sync_router)
app.include_router(stock.router)
app.include_router(cash.router)


# ----------------------------------------------------------------------
# Страница записи по ссылке
# ----------------------------------------------------------------------
import os  # noqa: E402

from fastapi.responses import (FileResponse, HTMLResponse,  # noqa: E402
                               JSONResponse)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')


@app.get('/z/logo.jpg', include_in_schema=False)
def booking_logo(shop: str = ''):
    """
    Логотип организации, чья страница открыта. Нет своего — 404, и
    страница обойдётся без картинки: чужой логотип хуже, чем никакого.
    """
    from fastapi.responses import Response
    from app.database import SessionLocal
    from app.services import branding

    session = SessionLocal()
    try:
        account, _ = branding.page_account(session, shop)
        found = branding.logo_of(session, account)
    finally:
        session.close()

    if found is None:
        return HTMLResponse(status_code=404, content='')
    data, kind = found
    return Response(content=data, media_type=kind,
                    headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/d', response_class=HTMLResponse, include_in_schema=False)
def dashboard_page():
    """
    Дашборд. Адрес короткий: его набирают с телефона, стоя в цеху.

    Сама страница ничего не решает: что показать, определяют права,
    и сервер отказывает в запросе, а не полагается на спрятанную кнопку.
    """
    path = os.path.join(WEB_DIR, 'dashboard.html')
    with open(path, encoding='utf-8') as page:
        return HTMLResponse(page.read())


@app.get('/d/plates', response_class=HTMLResponse, include_in_schema=False)
def plates_page():
    """Проверка распознавания номеров с телефона владельца (вход — дашборда)."""
    path = os.path.join(WEB_DIR, 'plates.html')
    with open(path, encoding='utf-8') as page:
        return HTMLResponse(page.read())


def _short_name(name, limit=14):
    """Короткое имя под значком: целое слово, без хвостов и кавычек."""
    clean = (name or 'Шиномонтаж').replace('«', '').replace('»', '').strip()
    if len(clean) <= limit:
        return clean

    cut = clean[:limit].rstrip()
    if ' ' in cut:
        cut = cut[:cut.rfind(' ')].rstrip()

    return cut or 'Шиномонтаж'


@app.get('/z/manifest.webmanifest', include_in_schema=False)
def booking_manifest(shop: str = ''):
    """
    Описание для телефона: имя, значок, цвета.

    Благодаря ему телефон предлагает «Добавить на экран», и кабинет
    открывается ярлыком, без адресной строки. Магазины приложений для
    этого не нужны, как и 99 долларов в год.

    Имя берём у точки, а не из настроек сервера: у сети их несколько,
    и ярлык должен называться той, ссылку на которую человек открыл.
    """
    from app.database import SessionLocal
    from app.services import shop_settings, tenancy

    from app.services import branding

    name = settings.SHOP_NAME
    start = '/z'
    color = '#0f172a'
    icons = [{'src': '/z/icon.svg', 'sizes': 'any', 'type': 'image/svg+xml',
              'purpose': 'any maskable'}]

    session = SessionLocal()
    try:
        account, row = branding.page_account(session, shop)
        if row is not None:
            name = shop_settings.title(session, row)
            start = f'/z/{row.slug}'
        if account is not None:
            brand = branding.brand_of(session, account, row)
            name = brand['name'] or name
            if account.brand_color:
                color = brand['color']
            # Значок на экране телефона — логотип организации, если есть
            if account.logo:
                icons = [{'src': f'/z/logo.jpg?shop={row.slug if row else ""}'
                                 f'&v={brand["logo_version"]}',
                          'sizes': '512x512', 'type': 'image/png',
                          'purpose': 'any'}] + icons
    finally:
        session.close()

    return JSONResponse({
        'name': f'{name}: запись и кабинет',
        # Под значком помещается немного, и обрезать надо по слову:
        # «Шиномонтаж «» на экране телефона выглядит поломкой
        'short_name': _short_name(name),
        'description': 'Запись на шиномонтаж, свои шины на хранении '
                       'и история обслуживания',
        'start_url': start,

        # Область — весь адрес. Кабинет живёт на своём поддомене, и
        # ограничивать его частью адреса незачем: с областью /z
        # открытый с корня кабинет считался бы чужой страницей и
        # вываливался из ярлыка в браузер
        'scope': '/',
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#f1f5f9',
        'theme_color': color,
        'lang': 'ru',
        'icons': icons,
    }, headers={'Cache-Control': 'public, max-age=3600'})


@app.get('/sw.js', include_in_schema=False)
def service_worker():
    """
    Файл, который показывает уведомления, когда кабинет закрыт.

    Лежит в корне, а не в `/z`, намеренно: браузер разрешает воркеру
    следить только за адресами внутри своей папки, и из `/z/sw.js` он
    не увидел бы саму страницу `/z` — она на уровень выше. Из корня
    можно ограничиться `/z` при подписке, а вот наоборот нельзя.

    Не кэшируем: иначе исправление в уведомлениях дойдёт до людей
    через сутки, а то и никогда.
    """
    path = os.path.join(WEB_DIR, 'sw.js')
    return FileResponse(path, media_type='application/javascript',
                        headers={'Cache-Control': 'no-cache'})


@app.get('/z/icon.svg', include_in_schema=False)
def booking_icon():
    path = os.path.join(WEB_DIR, 'icon.svg')
    return FileResponse(path, media_type='image/svg+xml',
                        headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/z/{slug}/q', response_class=HTMLResponse, include_in_schema=False)
def live_queue_page(slug: str):
    """
    Живая очередь по QR у въезда: /z/shinomontazh-rif/q. Встать в очередь,
    видеть своё место и узнать, на какой пост ехать.
    """
    path = os.path.join(WEB_DIR, 'live.html')
    with open(path, encoding='utf-8') as page:
        return HTMLResponse(page.read(), headers={'Cache-Control': 'no-cache'})


@app.get('/parking', response_class=HTMLResponse, include_in_schema=False)
def parking_page():
    """3D-схема площадки со стрелками до поста: /parking?client=1#post2."""
    path = os.path.join(WEB_DIR, 'parking.html')
    with open(path, encoding='utf-8') as page:
        return HTMLResponse(page.read(), headers={'Cache-Control': 'no-cache'})


@app.get('/z/{slug}', response_class=HTMLResponse, include_in_schema=False)
def booking_page_of(slug: str):
    """
    Страница записи конкретной точки: /z/shinomontazh-rif.

    Сама страница одна и та же — какая это точка, она узнаёт из адреса
    и спрашивает у сервера. Так одну ссылку можно дать каждой точке
    сети, и клиент попадёт именно туда, куда собирался.
    """
    return booking_page()


@app.get('/z', response_class=HTMLResponse, include_in_schema=False)
def booking_page():
    """
    Страница записи. Короткий адрес — её отправляют в переписке,
    и «/z» помещается даже в SMS.
    """
    path = os.path.join(WEB_DIR, 'booking.html')
    with open(path, encoding='utf-8') as page:
        return HTMLResponse(page.read())


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
