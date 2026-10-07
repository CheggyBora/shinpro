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
                        WorkOrderItem, SalaryTransaction, SalaryPayout,
                        Settings, TireStorage, Shift, AuditLog, Appointment,
                        BookingPosts, PaintOption)
    Base.metadata.create_all(bind=engine)
    add_missing_columns()
    fill_storage_deadlines()
    classify_services()
    seed_paint_options()


def fill_storage_deadlines():
    """
    Проставить срок комплектам, принятым до того, как срок появился.

    Колонку add_missing_columns() добавит, но пустую, и у всего, что
    уже лежит на складе, срока не будет — значит владельцам никто не
    напомнит. Заполняем один раз, только пустые поля.

    Падать здесь нельзя: не посчитался срок — программа всё равно
    должна открыться, остальное от этого не зависит.
    """
    from sqlalchemy.orm import Session

    try:
        from services.tire_storage_service import TireStorageService

        with Session(engine) as session:
            filled = TireStorageService(session).fill_missing_deadlines()
            if filled:
                print(f'Проставлен срок хранения: комплектов {filled}')
    except Exception as e:
        print(f'Не удалось проставить сроки хранения: {e}')


def seed_paint_options():
    """
    Завести дополнения к покраске, если их ещё нет.

    Калькулятор должен считать с первого запуска, а не показывать
    пустой список. Цены там условные — шиномонтаж заменит своими.

    Падать нельзя: без калькулятора программа работает.
    """
    from sqlalchemy.orm import Session

    try:
        from services.paint_service import PaintService

        with Session(engine) as session:
            added = PaintService(session).ensure_defaults()
            if added:
                print(f'Калькулятор покраски: заведено дополнений {added}')
    except Exception as e:
        print(f'Не удалось завести дополнения к покраске: {e}')


def classify_services():
    """
    Разделить прайс на основные услуги и допродажи — один раз.

    До этой версии деления не было, и всё лежало вперемешку. Правило
    простое: съём, шиномонтаж, балансировка, мойка — основное, остальное
    предложил мастер. Разметка нужна дашборду: по доле допов видно,
    работает приёмка или просто крутит колёса.

    Делается однократно, как и сроки хранения: дальше вид правится
    руками в прайс-листе, и перебивать правку списком слов нельзя.

    Падать здесь нельзя: не разметился прайс — программа всё равно
    должна открыться, на работу цеха это не влияет.
    """
    from sqlalchemy.orm import Session

    try:
        from models import Settings
        from services.service_kind import looks_main

        marker = 'services_classified'

        with Session(engine) as session:
            done = session.query(Settings).filter(
                Settings.key == marker).first()
            if done is not None and done.value == '1':
                return

            from models import Service

            changed = 0
            for row in session.query(Service).all():
                extra = not looks_main(row.name)
                if bool(row.is_extra) != extra:
                    row.is_extra = extra
                    changed += 1

            if done is None:
                session.add(Settings(key=marker, value='1'))
            else:
                done.value = '1'

            session.commit()
            if changed:
                print(f'Прайс размечен: услуг помечено допродажами {changed}')
    except Exception as e:
        print(f'Не удалось разметить прайс: {e}')


def add_missing_columns():
    """
    Дописать в существующие таблицы колонки, появившиеся в новой версии.

    create_all() создаёт недостающие таблицы, но не трогает те, что уже
    есть: добавили поле в модель — в рабочей базе его не будет, и
    программа упадёт при первом же запросе. Раньше это чинили скриптами
    миграции вручную. Для шиномонтажа, у которого стоит .exe и нет
    Python, такой способ не работает: человек просто обновит программу
    и получит сломанную базу.

    Добавляем только новые колонки. Ничего не переименовываем, не
    удаляем и не переносим данные — такие правки по-прежнему делаются
    отдельными скриптами, где есть резервная копия и проверка.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    try:
        existing_tables = set(inspector.get_table_names())
    except Exception as e:
        # Без списка таблиц доводку не сделать, но и падать нельзя:
        # программа должна открыться и сказать о беде человеку
        print(f"Не удалось прочитать схему базы: {e}")
        return

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        have = {column['name'] for column in inspector.get_columns(table.name)}

        for column in table.columns:
            if column.name in have:
                continue

            kind = column.type.compile(dialect=engine.dialect)
            clause = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {kind}'

            # NOT NULL без значения по умолчанию SQLite не примет: в уже
            # существующих строках это поле пустое. Колонка добавляется
            # необязательной — данные важнее строгости схемы
            default = getattr(column.default, 'arg', None)
            if default is not None and not callable(default):
                clause += f' DEFAULT {_sql_literal(default)}'

            try:
                with engine.begin() as connection:
                    connection.execute(text(clause))
                print(f"В таблицу {table.name} добавлена колонка {column.name}")
            except Exception as e:
                print(f"Не удалось добавить {table.name}.{column.name}: {e}")


def _sql_literal(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"
