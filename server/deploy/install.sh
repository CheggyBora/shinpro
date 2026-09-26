#!/usr/bin/env bash
#
# Развернуть сервер на чистой Ubuntu 22.04/24.04.
#
#     sudo bash deploy/install.sh shinomontazh.ru
#
# Что делает: ставит PostgreSQL и Python, заводит базу и пользователя,
# создаёт .env со свежими ключами, поднимает службу, настраивает nginx
# с бесплатным сертификатом и ежедневные копии базы.
#
# Запускать можно повторно: уже сделанное пропускается, пароли и ключи
# не перегенерируются. Это важно — иначе повторный запуск разлогинил бы
# всех и оборвал обмен с цехом.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"

APP_USER="tire"
APP_DIR="/opt/tire-server"
DB_NAME="tire"
DB_USER="tire"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "Запускать от root: sudo bash deploy/install.sh домен.ру"
[ -n "$DOMAIN" ] || fail "Не указан домен: sudo bash deploy/install.sh домен.ру [почта]"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say "Ставим пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-dev build-essential \
    postgresql postgresql-contrib libpq-dev \
    nginx certbot python3-certbot-nginx \
    ufw rsync

say "Заводим пользователя $APP_USER"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

say "Копируем код в $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude '.git' --exclude '__pycache__' --exclude '*.db' \
    --exclude '.env' --exclude 'venv' \
    "$SOURCE_DIR"/ "$APP_DIR"/
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

say "Готовим окружение Python"
if [ ! -d "$APP_DIR/venv" ]; then
    python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/venv"

say "База данных"
systemctl enable --now postgresql

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
    echo "Пользователь базы уже есть — пароль не трогаем"
    DB_PASSWORD=""
else
    DB_PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
    sudo -u postgres psql -qc "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
fi

sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
    || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"

say "Настройки в $APP_DIR/.env"
if [ -f "$APP_DIR/.env" ]; then
    echo "Файл уже есть — ключи и пароли оставляем как были"
else
    [ -n "$DB_PASSWORD" ] || fail "Пользователь базы есть, а .env нет: впишите SERVER_DATABASE_URL вручную"

    SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

    cat > "$APP_DIR/.env" <<ENV
# Создано deploy/install.sh $(date '+%d.%m.%Y %H:%M')
SERVER_DATABASE_URL=postgresql+psycopg2://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
SERVER_SECRET_KEY=$SECRET_KEY

# Владелец дашборда: впишите свой номер и перезапустите службу
SERVER_OWNER_PHONE=
SERVER_OWNER_NAME=

# Коды входа. Пока провайдер не подключён, код пишется в журнал сервера
SERVER_SMS_PROVIDER=log
SERVER_SMS_API_KEY=
SERVER_SMS_SENDER=

SERVER_SHOP_NAME=Шиномонтаж
SERVER_CORS_ORIGINS=https://$DOMAIN

# Оплата пользования: выключена, пока заказчик один
SERVER_BILLING_ENFORCE=0
ENV
    chmod 600 "$APP_DIR/.env"
    chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
fi

say "Миграции базы"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && set -a && . ./.env && set +a && ./venv/bin/alembic upgrade head"

say "Служба"
install -m 644 "$APP_DIR/deploy/tire-server.service" /etc/systemd/system/tire-server.service
systemctl daemon-reload
systemctl enable --now tire-server
sleep 2
systemctl is-active --quiet tire-server || fail "Служба не поднялась: journalctl -u tire-server -n 50"

say "nginx и сертификат"
sed "s/ДОМЕН/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" > /etc/nginx/sites-available/tire-server
ln -sf /etc/nginx/sites-available/tire-server /etc/nginx/sites-enabled/tire-server
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

if [ -n "$EMAIL" ]; then
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect || \
        echo "Сертификат не выпустился — проверьте, что домен смотрит на этот сервер, и запустите certbot вручную"
else
    echo "Почта не указана — сертификат выпустите сами:"
    echo "    certbot --nginx -d $DOMAIN"
fi

say "Копии базы"
install -m 755 "$APP_DIR/deploy/backup.sh" /usr/local/bin/tire-backup
install -m 644 "$APP_DIR/deploy/tire-backup.service" /etc/systemd/system/tire-backup.service
install -m 644 "$APP_DIR/deploy/tire-backup.timer" /etc/systemd/system/tire-backup.timer
mkdir -p /var/backups/tire
chown "$APP_USER:$APP_USER" /var/backups/tire
systemctl daemon-reload
systemctl enable --now tire-backup.timer

say "Сеть"
ufw allow OpenSSH >/dev/null 2>&1 || true
ufw allow 'Nginx Full' >/dev/null 2>&1 || true
ufw --force enable >/dev/null 2>&1 || true

say "Готово"
cat <<DONE

Сервер поднят: https://$DOMAIN

Что осталось сделать руками:

1. Впишите свой номер в $APP_DIR/.env (SERVER_OWNER_PHONE) и
   перезапустите службу:
       systemctl restart tire-server

2. Заведите шиномонтаж и получите ключ обмена:
       cd $APP_DIR && sudo -u $APP_USER ./venv/bin/python manage.py \\
           add-account "Шиномонтаж «РИФ»"

   Ключ показывается один раз — впишите его в программе цеха:
   Настройки → Обмен с сервером.

3. Проверьте готовность:
       cd $APP_DIR && sudo -u $APP_USER ./venv/bin/python manage.py check

Полезное:
    journalctl -u tire-server -f          журнал сервера
    systemctl restart tire-server         перезапуск
    bash $APP_DIR/deploy/update.sh        обновление после правок
DONE
