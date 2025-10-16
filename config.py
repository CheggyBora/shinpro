import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Определяем абсолютный путь к базе данных
# Для .exe - рядом с исполняемым файлом
# Для скрипта - в корне проекта
def get_database_path():
    if getattr(sys, 'frozen', False):
        # Если запущен как .exe (PyInstaller)
        # База данных создаётся рядом с .exe файлом
        app_dir = os.path.dirname(sys.executable)
    else:
        # Если запущен как скрипт
        app_dir = os.path.dirname(os.path.abspath(__file__))
    
    db_path = os.path.join(app_dir, 'tire_shop.db')
    return f'sqlite:///{db_path}'

# Используем переменную окружения или автоматически определённый путь
DATABASE_URL = os.getenv('DATABASE_URL', get_database_path())

if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    from models import Employee, WorkShift, Client, Car, Service, WorkOrder, WorkOrderItem, SalaryTransaction, Settings
    Base.metadata.create_all(bind=engine)
