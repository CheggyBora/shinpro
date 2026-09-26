#!/usr/bin/env bash
#
# Копия базы сервера. Запускается таймером раз в сутки.
#
# Копия на том же диске спасает от ошибки в программе и от «удалили не
# то», но не от потери самого сервера. Если задан SERVER_BACKUP_RSYNC —
# копия уезжает ещё и туда.
set -euo pipefail

APP_DIR="/opt/tire-server"
BACKUP_DIR="/var/backups/tire"
KEEP_DAYS=30

set -a
# shellcheck disable=SC1091
. "$APP_DIR/.env"
set +a

mkdir -p "$BACKUP_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"
FILE="$BACKUP_DIR/tire_$STAMP.sql.gz"

# Разбираем строку подключения: pg_dump хочет поля по отдельности
URL="${SERVER_DATABASE_URL:-}"
if [ -z "$URL" ]; then
    echo "В .env нет SERVER_DATABASE_URL — копировать нечего" >&2
    exit 1
fi

if [[ "$URL" == sqlite* ]]; then
    # База разработки: копируем файл средствами самой SQLite, иначе в
    # копию не попадут последние записи из журнала
    DB_FILE="${URL#sqlite:///}"
    sqlite3 "$DB_FILE" ".backup '$BACKUP_DIR/tire_$STAMP.db'"
    gzip -f "$BACKUP_DIR/tire_$STAMP.db"
    FILE="$BACKUP_DIR/tire_$STAMP.db.gz"
else
    CLEAN="${URL#*://}"
    CREDENTIALS="${CLEAN%%@*}"
    HOSTPART="${CLEAN#*@}"

    PGUSER="${CREDENTIALS%%:*}"
    PGPASSWORD="${CREDENTIALS#*:}"
    PGHOSTPORT="${HOSTPART%%/*}"
    PGDATABASE="${HOSTPART#*/}"
    PGDATABASE="${PGDATABASE%%\?*}"
    PGHOST="${PGHOSTPORT%%:*}"
    PGPORT="${PGHOSTPORT#*:}"
    [ "$PGPORT" = "$PGHOST" ] && PGPORT=5432

    export PGPASSWORD
    pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
        --no-owner --no-privileges | gzip > "$FILE"
fi

chmod 600 "$FILE"
echo "Копия готова: $FILE ($(du -h "$FILE" | cut -f1))"

# Старые копии убираем, иначе диск кончится ровно в тот день, когда
# копия понадобится
find "$BACKUP_DIR" -name 'tire_*' -type f -mtime "+$KEEP_DAYS" -delete

# Копия наружу: адрес вида user@host:/путь/
if [ -n "${SERVER_BACKUP_RSYNC:-}" ]; then
    if rsync -a --quiet "$FILE" "$SERVER_BACKUP_RSYNC"; then
        echo "Копия отправлена: $SERVER_BACKUP_RSYNC"
    else
        echo "Копию наружу отправить не удалось" >&2
    fi
fi
