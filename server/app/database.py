"""
Подключение к базе сервера.

На боевом сервере это PostgreSQL, при разработке — SQLite рядом
с кодом. Разницу берёт на себя SQLAlchemy, в остальном коде она
не всплывает.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

connect_args = {}
if settings.DATABASE_URL.startswith('sqlite'):
    # SQLite по умолчанию запрещает работу из другого потока,
    # а FastAPI обрабатывает запросы именно так
    connect_args['check_same_thread'] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    # Соединение может протухнуть за ночь простоя, а клиент получит
    # ошибку на ровном месте — проверяем перед выдачей из пула
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """Сессия на один запрос. Закрывается всегда, даже при ошибке."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Привести базу к текущей схеме — миграциями alembic.

    Раньше здесь был create_all: он создаёт недостающие таблицы, но не
    трогает существующие. На боевом сервере это означало бы, что новая
    колонка просто не появится, а запросы начнут падать после первого
    же обновления.

    Миграции решают это иначе: каждая правка схемы записана шагом, и
    база проходит их по порядку до текущего состояния. На пустой базе
    шаги создают её целиком — отдельный путь для разработки не нужен.
    """
    import os

    from alembic import command
    from alembic.config import Config

    from app import models  # noqa: F401 — регистрирует таблицы в Base

    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = Config(os.path.join(server_dir, 'alembic.ini'))
    config.set_main_option('script_location',
                           os.path.join(server_dir, 'migrations'))
    config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)

    # Тихо: при каждом запуске сервера и каждом тесте нам не нужен
    # вывод alembic, а о беде скажет исключение
    config.attributes['configure_logger'] = False

    command.upgrade(config, 'head')
