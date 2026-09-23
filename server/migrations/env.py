"""
Как alembic находит базу и схему.

Адрес базы берётся из тех же настроек, что и у сервера: держать его
ещё и в alembic.ini — значит однажды обновить одно место и забыть про
второе, а потом мигрировать не ту базу.
"""
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER_DIR)

from app.config import settings          # noqa: E402
from app.database import Base            # noqa: E402
import app.models                        # noqa: E402,F401  таблицы регистрируются импортом

config = context.config
config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)

# Настройки журнала из alembic.ini применяем только при запуске из
# командной строки. Когда миграции гонит сам сервер, трогать журнал
# нельзя: fileConfig выключает уже настроенные логгеры, и сервер
# замолкает ровно в тот момент, когда его надо слушать
if (config.config_file_name is not None
        and config.attributes.get('configure_logger', True)):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    """Собрать SQL, не подключаясь к базе: для ручной проверки правок."""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        # SQLite не умеет менять колонку на месте: alembic делает это
        # через пересоздание таблицы. На PostgreSQL не мешает
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            # Замечать смену типа колонки, а не только появление новых
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
