#!/usr/bin/env bash
#
# Завести на сервере приёмник для git push.
#
#     sudo bash deploy/setup-git.sh
#
# После этого обновление сервера выглядит так — с вашего компьютера,
# из папки проекта:
#
#     git push server main
#
# Сервер сам заберёт код, разложит его, снимет копию базы, прогонит
# миграции и перезапустится.
#
# Запускать можно повторно: перехватчик просто перезапишется.
set -euo pipefail

REPO=/opt/tire.git
HOOK_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/post-receive"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "Запускать от root: sudo bash deploy/setup-git.sh"
[ -f "$HOOK_SOURCE" ] || fail "Не найден $HOOK_SOURCE"

say "Ставим git"
export DEBIAN_FRONTEND=noninteractive
command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git; }
command -v rsync >/dev/null || apt-get install -y -qq rsync

say "Заводим репозиторий $REPO"
if [ ! -d "$REPO" ]; then
    git init --bare --initial-branch=main "$REPO" >/dev/null
    echo "Создан"
else
    echo "Уже есть — оставляем как есть"
fi

say "Ставим перехватчик"
install -m 755 "$HOOK_SOURCE" "$REPO/hooks/post-receive"

say "Готово"
cat <<DONE

На вашем компьютере, один раз, из папки проекта:

    git remote add server ssh://root@АДРЕС-СЕРВЕРА$REPO
    git push server main

Дальше каждое обновление — просто:

    git push server main

DONE
