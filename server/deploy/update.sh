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

say "Адреса организаций"
# У каждой организации свой адрес записи и дашборда (решение владельца
# 27.10.2026): koleso.ДОМЕН, koleso-admin.ДОМЕН и свои домены. Шаблон
# nginx ставится один раз и правки не требует; новые адреса и
# сертификаты заводит таймер tire-domains. Не вышло — раскатку не
# останавливаем: lk. и admin. работают и без этого
setup_orgs() {
    local base
    base="$(sudo -u tire bash -c "cd '$APP_DIR' && ./venv/bin/python manage.py platform-domain" | tail -n 1)"
    if ! [[ "$base" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then
        echo "Домен сервера не определился — адреса организаций пропущены"
        return 0
    fi

    mkdir -p /etc/nginx/tire/sites /var/www/tire-acme /var/lib/tire-domains
    touch /etc/nginx/tire/lk-names.conf /etc/nginx/tire/admin-names.conf
    # Общие правила для блоков https, которые пишет tire-domains
    install -m 644 "$SRC_DIR/deploy/nginx-orgs-lk.inc" /etc/nginx/tire/lk.inc
    install -m 644 "$SRC_DIR/deploy/nginx-orgs-admin.inc" /etc/nginx/tire/admin.inc

    # Файл называется после tire-server, чтобы nginx читал его вторым:
    # первый блок на порту становится блоком «по умолчанию», и им
    # должен остаться lk., а не шаблон организаций
    # Две черты: одну съедает sed, в nginx доходит «rif-service\.ru»
    local escaped="${base//./\\\\.}"
    sed -e "s/ДОМЕН_РЕГ/$escaped/g" "$SRC_DIR/deploy/nginx-orgs.conf" \
        > /etc/nginx/sites-available/tire-server-orgs.new
    mv -f /etc/nginx/sites-available/tire-server-orgs.new /etc/nginx/sites-available/tire-server-orgs
    ln -sf /etc/nginx/sites-available/tire-server-orgs /etc/nginx/sites-enabled/tire-server-orgs

    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
    else
        rm -f /etc/nginx/sites-enabled/tire-server-orgs
        echo "Шаблон адресов организаций nginx не принял — снят, остальное не тронуто" >&2
        nginx -t 2>&1 | tail -n 3 >&2 || true
        return 0
    fi

    install -m 755 "$SRC_DIR/deploy/domains.sh" /usr/local/bin/tire-domains
    install -m 644 "$SRC_DIR/deploy/tire-domains.service" /etc/systemd/system/tire-domains.service
    install -m 644 "$SRC_DIR/deploy/tire-domains.timer" /etc/systemd/system/tire-domains.timer
    systemctl daemon-reload
    systemctl enable --now tire-domains.timer >/dev/null 2>&1
    echo "Адреса организаций: *.$base"
}
setup_orgs || echo "Адреса организаций не настроились — раскатка продолжается" >&2

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
