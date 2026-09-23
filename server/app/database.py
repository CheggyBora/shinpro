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
    """Создать недостающие таблицы."""
    from app import models  # noqa: F401 — регистрирует таблицы в Base

    Base.metadata.create_all(bind=engine)
