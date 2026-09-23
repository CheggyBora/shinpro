#!/usr/bin/env python3
"""
Очистка рабочих данных: начать с чистого листа.

УДАЛЯЕТ: клиентов, машины, наряды и позиции, начисления зарплаты,
         хранение шин, смены, журнал действий.

СОХРАНЯЕТ: прайс-лист со всеми ценами, себестоимостью расходников
           и длительностями услуг; настройки; PIN-код; сотрудников.

Нумерация нарядов сбрасывается — следующий наряд снова будет №1.

Запуск:
    python clear_working_data.py --dry-run          # только показать, что удалится
    python clear_working_data.py                    # спросит подтверждение
    python clear_working_data.py --yes              # без вопросов
    python clear_working_data.py --with-employees   # заодно удалить сотрудников

Перед удалением всегда делается резервная копия в папке backups.
Файлы чеков в папке receipts не трогаются.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from migrate_clients_and_plates import find_db_path, make_backup, table_exists

# Порядок важен: сначала то, что ссылается на другие таблицы
TABLES_TO_CLEAR = [
    ('work_order_items', 'позиции нарядов'),
    ('salary_transactions', 'начисления зарплаты'),
    ('tire_storage', 'записи хранения шин'),
    ('work_orders', 'наряды'),
    ('cars', 'машины'),
    ('clients', 'клиенты'),
    ('work_shifts', 'смены сотрудников'),
    ('shifts', 'смены'),
    ('audit_log', 'записи журнала действий'),
]

EMPLOYEE_TABLE = ('employees', 'сотрудники')

# Эти таблицы не трогаем никогда: в них настроенный прайс-лист,
# себестоимость расходников, длительности услуг, PIN и настройки
TABLES_TO_KEEP = ['services', 'settings']


def count_rows(conn, table):
    if not table_exists(conn, table):
        return None
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def main():
    dry_run = '--dry-run' in sys.argv
    assume_yes = '--yes' in sys.argv
    with_employees = '--with-employees' in sys.argv

    db_path = find_db_path()
    if not os.path.exists(db_path):
        print(f"База данных не найдена: {db_path}")
        print("Очищать нечего — при первом запуске программа создаст пустую базу.")
        return

    print(f"База данных: {db_path}\n")

    tables = list(TABLES_TO_CLEAR)
    if with_employees:
        tables.append(EMPLOYEE_TABLE)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        print("Будет удалено:")
        total = 0
        for table, title in tables:
            rows = count_rows(conn, table)
            if rows is None:
                continue
            total += rows
            print(f"  {title:28} {rows}")

        print("\nОстанется без изменений:")
        for table in TABLES_TO_KEEP:
            rows = count_rows(conn, table)
            if rows is not None:
                title = 'услуг в прайс-листе' if table == 'services' else 'настроек'
                print(f"  {title:28} {rows}")
        if not with_employees:
            rows = count_rows(conn, 'employees')
            if rows is not None:
                print(f"  {'сотрудников':28} {rows}")

        if total == 0:
            print("\nБаза уже пуста, удалять нечего.")
            return

        if dry_run:
            print("\nРЕЖИМ ПРЕДПРОСМОТРА — ничего не удалено.")
            return

        if not assume_yes:
            print("\nЭто действие необратимо (резервная копия будет создана).")
            answer = input("Удалить перечисленное? Введите «да» для подтверждения: ")
            if answer.strip().lower() not in ('да', 'yes', 'y'):
                print("Отменено, база не изменена.")
                return

        backup_path = make_backup(db_path)
        print(f"\nРезервная копия: {backup_path}")

        for table, title in tables:
            if table_exists(conn, table):
                conn.execute(f"DELETE FROM {table}")

        # Сбрасываем счётчики, чтобы нумерация снова начиналась с единицы
        if table_exists(conn, 'sqlite_sequence'):
            for table, _ in tables:
                conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))

        conn.commit()

        print("\nУдалено. Проверка:")
        for table, title in tables:
            rows = count_rows(conn, table)
            if rows is not None:
                print(f"  {title:28} {rows}")

        services = count_rows(conn, 'services')
        settings = count_rows(conn, 'settings')
        print(f"\nПрайс-лист сохранён: услуг {services}, настроек {settings}.")
        print("Следующий наряд будет под номером 1.")
        print("\nФайлы чеков в папке receipts не тронуты — при совпадении")
        print("номеров новые чеки перезапишут старые файлы.")

    except Exception as e:
        conn.rollback()
        print(f"\nОШИБКА: {e}")
        print("Изменения отменены, база осталась в прежнем виде.")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
