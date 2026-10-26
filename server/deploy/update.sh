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
# Свежий код, доступный на запись только root. Всё, что выполняется с
# правами root, берём отсюда, а не из рабочей папки службы
SRC_DIR="/opt/tire-src/server"
[ -d "$SRC_DIR" ] || SRC_DIR="$APP_DIR"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Копия базы"
# Сам скрипт копии — тоже из свежего кода (он читает .env службы как
# текст, не выполняя)
install -m 755 "$SRC_DIR/deploy/backup.sh" /usr/local/bin/tire-backup
/usr/local/bin/tire-backup

say "Зависимости"
# От имени службы: окружение Python принадлежит ей, и запускать его
# файлы от root нельзя
sudo -u tire "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# Перехватчик раскатки ставится в /opt/tire.git один раз, копией. Его
# правки (например, что не стирать при раскатке) иначе не доехали бы
# до сервера никогда — обновляем копию из свежего кода
if [ -d /opt/tire.git/hooks ] && [ -f "$SRC_DIR/deploy/post-receive" ]; then
    # Через новый файл и переименование: старый перехватчик сейчас
    # выполняется, и переписывать его на месте нельзя — bash дочитывает
    # скрипт по ходу работы
    install -m 755 "$SRC_DIR/deploy/post-receive" /opt/tire.git/hooks/post-receive.new
    mv -f /opt/tire.git/hooks/post-receive.new /opt/tire.git/hooks/post-receive
fi

say "Миграции"
sudo -u tire bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && ./venv/bin/alembic upgrade head"

say "Модели распознавания номеров"
# Скачиваются один раз (~13 МБ) в $APP_DIR/plate-models. Не вышло —
# раскатку не останавливаем: номер с фото тогда вписывают руками
sudo -u tire bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && ./venv/bin/python manage.py plate-models" \
    || echo "Модели не скачались — повторится при первом снимке"

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
