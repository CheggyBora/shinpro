import os
import sys
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Определяем абсолютный путь к базе данных
# Для .exe - рядом с исполняемым файлом
# Для скрипта - в корне проекта
def get_app_dir():
    if getattr(sys, 'frozen', False):
        # Если запущен как .exe (PyInstaller)
        return os.path.dirname(sys.executable)
    # Если запущен как скрипт
    return os.path.dirname(os.path.abspath(__file__))


def get_database_path():
    db_path = os.path.join(get_app_dir(), 'tire_shop.db')
    return f'sqlite:///{db_path}'

# Используем переменную окружения или автоматически определённый путь
DATABASE_URL = os.getenv('DATABASE_URL', get_database_path())

IS_SQLITE = DATABASE_URL.startswith('sqlite')


def get_db_file_path():
    """
    Путь к файлу базы, если база SQLite. Для PostgreSQL возвращает None.
    Нужен для резервного копирования.
    """
    if not IS_SQLITE:
        return None
    return DATABASE_URL[len('sqlite:///'):]


if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _setup_sqlite(dbapi_connection, connection_record):
        """
        Настройки надёжности SQLite.

        WAL (журнал упреждающей записи) — главное: при внезапном отключении
        питания или зависании база остаётся целой, вместо того чтобы
        превратиться в повреждённый файл.
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            # NORMAL в связке с WAL — обычный компромисс между скоростью
            # и надёжностью, данные при падении программы не теряются
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Ждём освобождения базы, а не падаем сразу с "database is locked"
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={
            "connect_timeout": 10,
            "sslmode": "require"
        }
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        return db
    finally:
        pass

def init_db():
    from models import (Employee, WorkShift, Client, Car, Service, WorkOrder,
                        WorkOrderItem, SalaryTransaction, Settings, TireStorage,
                        Shift, AuditLog, Appointment,
                        BookingPosts)
    Base.metadata.create_all(bind=engine)
