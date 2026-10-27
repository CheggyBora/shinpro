# Правила записи и кабинета клиента: общие для всех адресов организаций.
# Подключаются из блоков, которые пишет tire-domains (deploy/domains.sh).

add_header X-Robots-Tag "noindex, nofollow" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header Referrer-Policy "same-origin" always;

client_max_body_size 10m;
proxy_read_timeout 60s;
proxy_connect_timeout 10s;

location ^~ /.well-known/acme-challenge/ {
    root /var/www/tire-acme;
}

location = / {
    limit_req zone=tire_common burst=40 nodelay;
    proxy_pass http://127.0.0.1:8000/z;
    include /etc/nginx/proxy_params;
}

location /auth/code {
    limit_req zone=tire_codes burst=3 nodelay;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/proxy_params;
}

location = /d { return 404; }
location /staff/ { return 404; }
location /dashboard/ { return 404; }

location / {
    limit_req zone=tire_common burst=40 nodelay;
    proxy_pass http://127.0.0.1:8000;
    include /etc/nginx/proxy_params;
}

location /docs { return 404; }
location /redoc { return 404; }
location /openapi.json { return 404; }

access_log /var/log/nginx/tire-orgs-access.log;
error_log /var/log/nginx/tire-orgs-error.log;
