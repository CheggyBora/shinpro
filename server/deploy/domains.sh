#!/usr/bin/env bash
#
# Адреса организаций: завести свои домены в nginx и выпустить
# сертификаты. Таймер tire-domains, раз в 5 минут, от root.
#
# Что должно работать, говорит база (manage.py domains-plan): наши
# поддомены каждой организации и свои домены, вписанные в дашборде.
# Владелец ничего не запускает: вписал адрес, сделал запись у
# регистратора — через несколько минут адрес работает.
#
# Сертификат не выпустился — повторяем не раньше чем через час: Let's
# Encrypt после пяти неудач в час на одно имя закрывает его на час сам.
set -euo pipefail

APP_DIR="/opt/tire-server"
CONF_DIR="/etc/nginx/tire"
ACME_DIR="/var/www/tire-acme"
STATE_DIR="/var/lib/tire-domains"
RETRY_SECONDS=3600

mkdir -p "$CONF_DIR" "$ACME_DIR" "$STATE_DIR"
touch "$CONF_DIR/lk-names.conf" "$CONF_DIR/admin-names.conf"

manage() {
    sudo -u tire "$APP_DIR/venv/bin/python" "$APP_DIR/manage.py" "$@"
}

# Имя попадает в файл nginx — пропускаем только буквы, цифры, точки и
# дефисы. Дашборд проверяет то же самое, это вторая стена
NAME_RE='^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$'

PLAN="$(manage domains-plan)"

lk_names=()
admin_names=()
while IFS=$'\t' read -r role name kind; do
    [ -n "${name:-}" ] || continue
    [[ "$name" =~ $NAME_RE ]] || continue
    # Наши поддомены nginx узнаёт по шаблону, в списки — только свои
    [ "$kind" = "own" ] || continue
    case "$role" in
        lk) lk_names+=("$name") ;;
        admin) admin_names+=("$name") ;;
    esac
done <<< "$PLAN"

# Записать список имён. 0 — файл изменился
write_names() {
    local file="$1"
    shift
    if [ $# -gt 0 ]; then
        printf 'server_name %s;\n' "$*" > "$file.new"
    else
        : > "$file.new"
    fi
    if cmp -s "$file.new" "$file"; then
        rm -f "$file.new"
        return 1
    fi
    cp -f "$file" "$file.bak"
    mv -f "$file.new" "$file"
    return 0
}

changed=0
if write_names "$CONF_DIR/lk-names.conf" "${lk_names[@]}"; then changed=1; fi
if write_names "$CONF_DIR/admin-names.conf" "${admin_names[@]}"; then changed=1; fi

if [ "$changed" = 1 ]; then
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        echo "Списки адресов обновлены"
    else
        # Сломанный nginx уронил бы всё сразу, вместе с lk. и admin. —
        # возвращаем прежние списки и ждём, пока разберутся
        mv -f "$CONF_DIR/lk-names.conf.bak" "$CONF_DIR/lk-names.conf"
        mv -f "$CONF_DIR/admin-names.conf.bak" "$CONF_DIR/admin-names.conf"
        echo "Новые адреса nginx не принял — оставлены прежние" >&2
    fi
fi

# Сообщить в базу, что вышло. Только когда что-то поменялось: каждый
# вызов — запуск Python, а адресов может быть много
report() {
    local name="$1" status="$2" note="$3"
    local file="$STATE_DIR/$name.status"
    if [ -f "$file" ] && [ "$(cat "$file")" = "$status $note" ]; then
        return 0
    fi
    if manage domain-status "$name" "$status" "$note" >/dev/null 2>&1; then
        printf '%s' "$status $note" > "$file"
    fi
}

MY_IPS=" $(hostname -I 2>/dev/null) "
SITES_DIR="$CONF_DIR/sites"
mkdir -p "$SITES_DIR"

# Блок https для адреса с сертификатом. 0 — файл новый или изменился
write_site() {
    local name="$1" role="$2"
    local file="$SITES_DIR/$name.conf"
    cat > "$file.new" <<SITE
# Пишет tire-domains (deploy/domains.sh) — руками не править
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $name;
    ssl_certificate /etc/letsencrypt/live/$name/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$name/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    include $CONF_DIR/$role.inc;
}
SITE
    if cmp -s "$file.new" "$file"; then
        rm -f "$file.new"
        return 1
    fi
    mv -f "$file.new" "$file"
    return 0
}

declare -A wanted=()
sites_changed=0
written=()

while IFS=$'\t' read -r role name kind; do
    [ -n "${name:-}" ] || continue
    [[ "$name" =~ $NAME_RE ]] || continue
    case "$role" in lk|admin) ;; *) continue ;; esac

    if [ ! -f "/etc/letsencrypt/live/$name/fullchain.pem" ]; then
        # Запись у регистратора ещё не появилась — сертификат не выпустить
        pointed=0
        for ip in $(getent ahostsv4 "$name" 2>/dev/null | awk '{print $1}' | sort -u); do
            case "$MY_IPS" in *" $ip "*) pointed=1 ;; esac
        done
        if [ "$pointed" = 0 ]; then
            report "$name" waiting "Запись в настройках домена ещё не видна"
            continue
        fi

        failed="$STATE_DIR/$name.failed"
        if [ -f "$failed" ] && [ $(( $(date +%s) - $(stat -c %Y "$failed") )) -lt "$RETRY_SECONDS" ]; then
            continue
        fi

        report "$name" waiting "Выпускаем сертификат"
        if ! certbot certonly --webroot -w "$ACME_DIR" -d "$name" \
                --non-interactive --agree-tos --keep-until-expiring \
                --deploy-hook "systemctl reload nginx" > "$STATE_DIR/$name.log" 2>&1; then
            touch "$failed"
            report "$name" error "Сертификат не выпустился, повторим через час"
            echo "Сертификат не выпустился: $name (подробности в $STATE_DIR/$name.log)" >&2
            continue
        fi
        rm -f "$failed"
        echo "Сертификат выпущен: $name"
    fi

    wanted["$name.conf"]=1
    if write_site "$name" "$role"; then
        sites_changed=1
        written+=("$SITES_DIR/$name.conf")
    fi
    report "$name" active "Работает"
done <<< "$PLAN"

# Адрес отключили в дашборде — убираем и его блок. Сертификат не
# трогаем: подключат обратно — не придётся выпускать заново
for file in "$SITES_DIR"/*.conf; do
    [ -e "$file" ] || continue
    if [ -z "${wanted[$(basename "$file")]:-}" ]; then
        mv -f "$file" "$file.off"
        sites_changed=1
    fi
done

if [ "$sites_changed" = 1 ]; then
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx
        echo "Адреса https обновлены"
    else
        # Новые блоки — в сторону: с неисправным файлом nginx не
        # поднимется после перезагрузки сервера, и вместе с адресами
        # организаций лягут lk. и admin.
        echo "Блоки https nginx не принял — новые отложены:" >&2
        nginx -t 2>&1 | tail -n 5 >&2 || true
        for file in "${written[@]}"; do
            mv -f "$file" "$file.failed"
        done
        if nginx -t >/dev/null 2>&1; then
            systemctl reload nginx
        fi
        exit 1
    fi
fi
