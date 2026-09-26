#!/usr/bin/env bash
#
# Обновить сервер после правок в коде.
#
#     bash /opt/tire-server/deploy/update.sh
#
# Копия базы — до всего остального: если миграция окажется неудачной,
# будет к чему вернуться.
set -euo pipefail

APP_DIR="/opt/tire-server"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Копия базы"
/usr/local/bin/tire-backup

say "Зависимости"
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

say "Миграции"
sudo -u tire bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && ./venv/bin/alembic upgrade head"

say "Перезапуск"
systemctl restart tire-server
sleep 2

if systemctl is-active --quiet tire-server; then
    echo "Сервер работает"
else
    echo "Сервер не поднялся — смотрите журнал:" >&2
    echo "    journalctl -u tire-server -n 50" >&2
    exit 1
fi
