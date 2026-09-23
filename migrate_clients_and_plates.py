#!/usr/bin/env python3
"""
Миграция базы: единый вид госномеров и один клиент вместо дублей.

Что делает:
  1. Делает резервную копию базы (всегда, до любых изменений).
  2. Добавляет колонки cars.client_id и clients.created_at, индексы.
  3. Приводит все госномера к единому виду и склеивает задвоившиеся машины.
  4. Приводит телефоны к единому виду и склеивает задвоившихся клиентов.
  5. Убирает служебные записи клиентов вида "Хранение (...)".
  6. Закрепляет машины за клиентами по истории нарядов.
  7. Переводит даты старых записей из всемирного времени в местное.

Запуск:
    python migrate_clients_and_plates.py --dry-run   # только показать, что будет
    python migrate_clients_and_plates.py             # применить
    python migrate_clients_and_plates.py --tz-hours 3   # задать сдвиг вручную

Скрипт можно запускать повторно: при втором запуске он ничего не меняет.
"""
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import normalize_plate, normalize_phone


def find_db_path():
    """Найти файл базы там же, где его ищет само приложение."""
    env_url = os.getenv('DATABASE_URL', '')
    if env_url and not env_url.startswith('sqlite'):
        print("База не SQLite (задан DATABASE_URL). Миграция рассчитана на SQLite.")
        sys.exit(1)

    if env_url.startswith('sqlite:///'):
        return env_url[len('sqlite:///'):]

    app_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(app_dir, 'tire_shop.db')


def make_backup(db_path):
    """
    Снять резервную копию базы.

    Копируем средствами самой SQLite, а не файл целиком. В режиме WAL
    свежие записи лежат в отдельном файле журнала, и обычное копирование
    .db даёт копию БЕЗ последних данных — а то и вовсе без таблиц.
    Для защитной копии перед миграцией это недопустимо.
    """
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f'tire_shop_before_migration_{stamp}.db')

    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()

    return backup_path


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


# ----------------------------------------------------------------------
# Шаги миграции
# ----------------------------------------------------------------------

def add_schema(conn, report):
    """Добавить недостающие колонки и индексы."""
    if not column_exists(conn, 'cars', 'client_id'):
        conn.execute("ALTER TABLE cars ADD COLUMN client_id INTEGER REFERENCES clients(id)")
        report.append("Добавлена колонка cars.client_id")

    if not column_exists(conn, 'clients', 'created_at'):
        conn.execute("ALTER TABLE clients ADD COLUMN created_at DATETIME")
        report.append("Добавлена колонка clients.created_at")

    # Расходники и время услуг
    if not column_exists(conn, 'services', 'consumable_cost'):
        conn.execute("ALTER TABLE services ADD COLUMN consumable_cost FLOAT DEFAULT 0 NOT NULL")
        report.append("Добавлена колонка services.consumable_cost (себестоимость расходников)")

    if not column_exists(conn, 'services', 'duration_minutes'):
        conn.execute("ALTER TABLE services ADD COLUMN duration_minutes INTEGER DEFAULT 0 NOT NULL")
        report.append("Добавлена колонка services.duration_minutes (время выполнения)")

    if not column_exists(conn, 'services', 'max_discount_percent'):
        conn.execute("ALTER TABLE services ADD COLUMN max_discount_percent "
                     "INTEGER DEFAULT 100 NOT NULL")
        report.append("Добавлена колонка services.max_discount_percent (макс. скидка)")

    if not column_exists(conn, 'work_order_items', 'consumable_cost'):
        conn.execute("ALTER TABLE work_order_items ADD COLUMN consumable_cost FLOAT DEFAULT 0 NOT NULL")
        report.append("Добавлена колонка work_order_items.consumable_cost (снимок себестоимости)")

    if not column_exists(conn, 'work_order_items', 'discount_manual'):
        conn.execute("ALTER TABLE work_order_items ADD COLUMN discount_manual "
                     "BOOLEAN DEFAULT 0 NOT NULL")
        report.append("Добавлена колонка work_order_items.discount_manual (ручная скидка)")

    for column in ('consumables_amount', 'salary_base'):
        if not column_exists(conn, 'work_orders', column):
            conn.execute(f"ALTER TABLE work_orders ADD COLUMN {column} FLOAT DEFAULT 0")
            report.append(f"Добавлена колонка work_orders.{column}")

    # Старым нарядам проставляем базу для зарплаты равной сумме:
    # расходники тогда не учитывались, и задним числом менять начисления нельзя
    updated = conn.execute("""
        UPDATE work_orders SET salary_base = total_amount
        WHERE status = 'paid' AND (salary_base IS NULL OR salary_base = 0)
          AND total_amount > 0
    """).rowcount
    if updated:
        report.append(f"Старым оплаченным нарядам проставлена база для ЗП: {updated}")

    # Планирование времени работ
    if not column_exists(conn, 'shifts', 'open_posts'):
        conn.execute("ALTER TABLE shifts ADD COLUMN open_posts INTEGER DEFAULT 2 NOT NULL")
        report.append("Добавлена колонка shifts.open_posts (постов в смене)")

    if not column_exists(conn, 'cars', 'wheels_assembled'):
        conn.execute("ALTER TABLE cars ADD COLUMN wheels_assembled BOOLEAN")
        report.append("Добавлена колонка cars.wheels_assembled (колёса в сборе)")

    for column, sql_type in (('planned_minutes', 'INTEGER DEFAULT 0'),
                             ('started_at', 'DATETIME'),
                             ('finished_at', 'DATETIME'),
                             ('paused_at', 'DATETIME'),
                             ('paused_minutes', 'INTEGER DEFAULT 0')):
        if not column_exists(conn, 'work_orders', column):
            conn.execute(f"ALTER TABLE work_orders ADD COLUMN {column} {sql_type}")
            report.append(f"Добавлена колонка work_orders.{column}")

    # Возврат, сторно и гарантийная переделка
    for column, sql_type in (('refunded_amount', 'FLOAT DEFAULT 0'),
                             ('refunded_at', 'DATETIME'),
                             ('refund_reason', 'VARCHAR(500)'),
                             ('refund_type', 'VARCHAR(20)'),
                             ('is_warranty', 'BOOLEAN DEFAULT 0')):
        if not column_exists(conn, 'work_orders', column):
            conn.execute(f"ALTER TABLE work_orders ADD COLUMN {column} {sql_type}")
            report.append(f"Добавлена колонка work_orders.{column}")

    # Таблицу записей create_all создаст сама при запуске программы,
    # здесь только индексы на случай, если она уже есть
    if table_exists(conn, 'appointments'):
        conn.execute("CREATE INDEX IF NOT EXISTS ix_appointments_scheduled "
                     "ON appointments(scheduled_at)")

    conn.execute("CREATE INDEX IF NOT EXISTS ix_clients_phone ON clients(phone)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_cars_client_id ON cars(client_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_cars_license_plate ON cars(license_plate)")


def merge_cars(conn, report):
    """Нормализовать номера и склеить машины, оказавшиеся одинаковыми."""
    cars = conn.execute("SELECT id, license_plate FROM cars ORDER BY id").fetchall()

    # normalized -> [id, ...] в порядке возрастания id
    groups = {}
    for car_id, plate in cars:
        normalized = normalize_plate(plate)
        if not normalized:
            continue  # мусорный номер не трогаем
        groups.setdefault(normalized, []).append((car_id, plate))

    merged = 0
    renamed = 0

    for normalized, members in groups.items():
        survivor_id, survivor_plate = members[0]
        losers = members[1:]

        for loser_id, loser_plate in losers:
            # Переносим наряды на выжившую машину
            conn.execute("UPDATE work_orders SET car_id = ? WHERE car_id = ?",
                         (survivor_id, loser_id))
            # Если у дубля был владелец, а у выжившего нет — сохраняем владельца
            conn.execute("""
                UPDATE cars SET client_id = (SELECT client_id FROM cars WHERE id = ?)
                WHERE id = ? AND client_id IS NULL
            """, (loser_id, survivor_id))
            conn.execute("DELETE FROM cars WHERE id = ?", (loser_id,))
            merged += 1
            report.append(f"  Склеены машины: «{loser_plate}» -> «{normalized}»")

        if survivor_plate != normalized:
            conn.execute("UPDATE cars SET license_plate = ? WHERE id = ?",
                         (normalized, survivor_id))
            renamed += 1

    if renamed:
        report.append(f"Приведено к единому виду номеров: {renamed}")
    if merged:
        report.append(f"Склеено задвоившихся машин: {merged}")


def merge_clients(conn, report):
    """Нормализовать телефоны и склеить клиентов с одинаковым номером."""
    clients = conn.execute(
        "SELECT id, name, phone FROM clients ORDER BY id"
    ).fetchall()

    groups = {}
    for client_id, name, phone in clients:
        normalized = normalize_phone(phone)
        if not normalized:
            continue  # без телефона опознать клиента нельзя
        groups.setdefault(normalized, []).append((client_id, name))

    merged = 0
    renamed = 0

    for normalized, members in groups.items():
        # Выживает клиент с именем (он информативнее), иначе самый первый
        with_name = [m for m in members if m[1] and m[1].strip()]
        survivor_id, survivor_name = (with_name or members)[0]

        merged_here = 0
        for loser_id, loser_name in members:
            if loser_id == survivor_id:
                continue
            conn.execute("UPDATE work_orders SET client_id = ? WHERE client_id = ?",
                         (survivor_id, loser_id))
            conn.execute("UPDATE cars SET client_id = ? WHERE client_id = ?",
                         (survivor_id, loser_id))
            conn.execute("DELETE FROM clients WHERE id = ?", (loser_id,))
            merged_here += 1

        merged += merged_here

        current_phone = conn.execute(
            "SELECT phone FROM clients WHERE id = ?", (survivor_id,)
        ).fetchone()[0]
        if current_phone != normalized:
            conn.execute("UPDATE clients SET phone = ? WHERE id = ?",
                         (normalized, survivor_id))
            renamed += 1

        if merged_here:
            report.append(
                f"  Клиент «{survivor_name or 'без имени'}» ({normalized}): "
                f"было записей {len(members)}, осталась 1"
            )

    if renamed:
        report.append(f"Приведено к единому виду телефонов: {renamed}")
    if merged:
        report.append(f"Удалено дублей клиентов: {merged}")


def drop_service_clients(conn, report):
    """
    Убрать служебные записи клиентов, созданные приёмкой шин на хранение.

    Раньше на каждую приёмку в таблицу клиентов падала запись вида
    "Хранение (Шины с дисками)" — это не клиент, а подпись для чека.
    """
    rows = conn.execute(
        "SELECT id FROM clients WHERE name LIKE 'Хранение (%'"
    ).fetchall()
    if not rows:
        return

    ids = [row[0] for row in rows]
    placeholders = ','.join('?' * len(ids))
    conn.execute(f"UPDATE work_orders SET client_id = NULL WHERE client_id IN ({placeholders})", ids)
    conn.execute(f"UPDATE cars SET client_id = NULL WHERE client_id IN ({placeholders})", ids)
    conn.execute(f"DELETE FROM clients WHERE id IN ({placeholders})", ids)
    report.append(f"Удалено служебных записей «Хранение (...)»: {len(ids)}")


def link_cars_to_clients(conn, report):
    """
    Закрепить машины за клиентами по истории: берём клиента из самого
    свежего наряда по этой машине.
    """
    linked = conn.execute("""
        UPDATE cars
        SET client_id = (
            SELECT wo.client_id FROM work_orders wo
            WHERE wo.car_id = cars.id AND wo.client_id IS NOT NULL
            ORDER BY wo.created_at DESC, wo.id DESC
            LIMIT 1
        )
        WHERE client_id IS NULL
          AND EXISTS (
            SELECT 1 FROM work_orders wo
            WHERE wo.car_id = cars.id AND wo.client_id IS NOT NULL
          )
    """).rowcount

    if linked:
        report.append(f"Закреплено машин за клиентами: {linked}")


# Колонки, которые раньше заполняла сама SQLite (CURRENT_TIMESTAMP),
# то есть по всемирному времени UTC. Всё остальное время программа
# записывала по местным часам, поэтому в базе оказались две разные шкалы.
UTC_COLUMNS = [
    ('work_orders', 'created_at'),
    ('employees', 'created_at'),
    ('shifts', 'start_time'),
    ('work_shifts', 'start_time'),
    ('salary_transactions', 'transaction_date'),
    ('tire_storage', 'accepted_date'),
    ('tire_storage', 'created_at'),
]

UTC_SHIFT_MARKER = 'migration_utc_shift_done'


def local_utc_offset_hours():
    """На сколько часов местное время опережает всемирное (для Москвы это 3)."""
    offset = datetime.now().astimezone().utcoffset()
    return int(round(offset.total_seconds() / 3600)) if offset else 0


def shift_utc_timestamps(conn, report, hours=None):
    """
    Перевести старые записи из всемирного времени в местное.

    Раньше часть дат ставила SQLite по UTC, а часть — программа по местным
    часам. Из-за этого дата создания наряда отличалась от даты оплаты
    на величину часового пояса, а длительность смены считалась неверно.

    Шаг выполняется один раз: отметка о выполнении хранится в settings.
    """
    done = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (UTC_SHIFT_MARKER,)
    ).fetchone()
    if done:
        return

    if hours is None:
        hours = local_utc_offset_hours()

    if hours == 0:
        report.append("Часовой пояс — всемирное время, сдвиг дат не требуется")
    else:
        sign = '+' if hours > 0 else '-'
        modifier = f"{sign}{abs(hours)} hours"
        total = 0

        for table, column in UTC_COLUMNS:
            if not table_exists(conn, table) or not column_exists(conn, table, column):
                continue
            # datetime(col) вернёт NULL для значения, которое не разбирается
            # как дата — такие строки не трогаем
            changed = conn.execute(
                f"UPDATE {table} SET {column} = datetime({column}, ?) "
                f"WHERE {column} IS NOT NULL AND datetime({column}) IS NOT NULL",
                (modifier,)
            ).rowcount
            total += changed

        if total:
            report.append(f"Даты старых записей сдвинуты на {hours} ч "
                          f"(из всемирного времени в местное): {total}")

    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (UTC_SHIFT_MARKER, datetime.now().isoformat(timespec='seconds'))
    )


def guess_assembled_wheels(conn, report):
    """
    Предзаполнить признак «колёса в сборе» по записям хранения.

    Если клиент сдавал на хранение «Шины с дисками», значит у него
    есть второй комплект на своих дисках — заполнять вручную не нужно.
    Уже заполненные значения не трогаем.
    """
    if not table_exists(conn, 'tire_storage'):
        return

    updated = conn.execute("""
        UPDATE cars SET wheels_assembled = 1
        WHERE wheels_assembled IS NULL
          AND EXISTS (
            SELECT 1 FROM tire_storage ts
            WHERE ts.car_number = cars.license_plate
              AND ts.storage_type LIKE '%с дисками%'
          )
    """).rowcount

    if updated:
        report.append(f"Проставлен признак «колёса в сборе» по хранению: {updated}")


def normalize_storage_plates(conn, report):
    """Привести к единому виду номера в записях хранения шин."""
    if not table_exists(conn, 'tire_storage'):
        return

    rows = conn.execute("SELECT id, car_number FROM tire_storage").fetchall()
    changed = 0
    for storage_id, car_number in rows:
        normalized = normalize_plate(car_number)
        if normalized and normalized != car_number:
            conn.execute("UPDATE tire_storage SET car_number = ? WHERE id = ?",
                         (normalized, storage_id))
            changed += 1

    if changed:
        report.append(f"Приведено к единому виду номеров в хранении шин: {changed}")


def stats(conn):
    def count(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        'машин': count("SELECT COUNT(*) FROM cars"),
        'клиентов': count("SELECT COUNT(*) FROM clients"),
        'нарядов': count("SELECT COUNT(*) FROM work_orders"),
        'машин с владельцем': count("SELECT COUNT(*) FROM cars WHERE client_id IS NOT NULL")
        if column_exists(conn, 'cars', 'client_id') else 0,
    }


def main():
    dry_run = '--dry-run' in sys.argv

    # Сдвиг часового пояса можно задать вручную: --tz-hours 3
    tz_hours = None
    if '--tz-hours' in sys.argv:
        tz_hours = int(sys.argv[sys.argv.index('--tz-hours') + 1])

    db_path = find_db_path()
    if not os.path.exists(db_path):
        print(f"База данных не найдена: {db_path}")
        print("Запустите скрипт из папки с программой.")
        sys.exit(1)

    print(f"База данных: {db_path}")

    if dry_run:
        print("РЕЖИМ ПРЕДПРОСМОТРА — изменения НЕ будут сохранены\n")
    else:
        backup_path = make_backup(db_path)
        print(f"Резервная копия: {backup_path}\n")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")

    before = stats(conn)
    report = []

    try:
        add_schema(conn, report)
        merge_cars(conn, report)
        merge_clients(conn, report)
        drop_service_clients(conn, report)
        link_cars_to_clients(conn, report)
        normalize_storage_plates(conn, report)
        guess_assembled_wheels(conn, report)
        shift_utc_timestamps(conn, report, hours=tz_hours)

        after = stats(conn)

        print("Что сделано:")
        if report:
            for line in report:
                print(f"  {line}" if not line.startswith('  ') else line)
        else:
            print("  Изменений не потребовалось — база уже в нужном виде.")

        print("\nБыло -> стало:")
        for key in before:
            mark = '' if before[key] == after[key] else '   <--'
            print(f"  {key:22} {before[key]:>6} -> {after[key]:>6}{mark}")

        if dry_run:
            conn.rollback()
            print("\nПредпросмотр завершён, база не изменена.")
        else:
            conn.commit()
            print("\nМиграция применена.")

    except Exception as e:
        conn.rollback()
        print(f"\nОШИБКА: {e}")
        print("Изменения отменены, база осталась в прежнем виде.")
        if not dry_run:
            print(f"При необходимости восстановите из копии: {backup_path}")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
