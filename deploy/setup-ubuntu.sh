#!/usr/bin/env bash
# Сервер с нуля одной командой: Ubuntu 24.04, от root.
#   bash setup-ubuntu.sh ваш-домен.ru
# Что делает: Docker + firewall + автообновления → код в /opt/gruzspecservice → .env для прода
# (берёт ваш локальный .env из /root/gruzspec.env, если вы его туда скопировали) → make prod-up → проверка HTTPS.
# Повторный запуск безопасен: обновит код и перезапустит, секреты и базу не тронет.
set -euo pipefail

DOMAIN="${1:-}"
REPO="${REPO:-https://github.com/Volsogin/gruzspecservice.git}"
DIR="${DIR:-/opt/gruzspecservice}"
ENV_SRC="${ENV_SRC:-/root/gruzspec.env}"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }

[ -n "$DOMAIN" ] || die "Укажите домен: bash $0 ваш-домен.ru"
[ "$(id -u)" = 0 ] || die "Запустите от root: sudo bash $0 $DOMAIN"
. /etc/os-release
[ "${ID:-}" = ubuntu ] || die "Скрипт для Ubuntu (24.04), а здесь ${PRETTY_NAME:-неизвестная ОС}"

say "Пакеты и автообновления безопасности"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq ca-certificates curl git make ufw unattended-upgrades dnsutils python3 >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true

if ! command -v docker >/dev/null 2>&1; then
  say "Docker Engine (официальный репозиторий)"
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
systemctl enable --now docker >/dev/null

say "Firewall: открыты только SSH, 80 и 443"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443 >/dev/null
ufw --force enable >/dev/null

say "Код: $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone -q "$REPO" "$DIR"
fi
cd "$DIR"

say ".env для продакшена"
if [ ! -f .env ]; then
  if [ -f "$ENV_SRC" ]; then cp "$ENV_SRC" .env; echo "взят ваш $ENV_SRC"; else cp .env.example .env; echo "взят .env.example — ключи потом допишите в $DIR/.env"; fi
  FIRST_RUN=1
else
  FIRST_RUN=0
fi
chmod 600 .env
DOMAIN="$DOMAIN" FIRST_RUN="$FIRST_RUN" python3 - <<'PY'
import os, re, secrets
from pathlib import Path

p = Path(".env")
text = p.read_text(encoding="utf-8")
domain = os.environ["DOMAIN"]
first = os.environ["FIRST_RUN"] == "1"

def get(key):
    m = re.search(rf"^{key}=(.*)$", text, re.M)
    return m.group(1).strip() if m else ""

def put(key, value):
    global text
    line = f"{key}={value}"
    if re.search(rf"^#?\s*{key}=", text, re.M):
        text = re.sub(rf"^#?\s*{key}=.*$", line, text, count=1, flags=re.M)
    else:
        text += f"\n{line}\n"

url = f"https://{domain}"
for k, v in {
    "APP_ENV": "prod", "DOMAIN": domain, "PUBLIC_BASE_URL": url, "API_BASE_URL": url, "CORS_ORIGINS": url,
    "LOG_JSON": "true",
    "TELEGRAM_PROXY_URL": "",  # прокси v2rayN есть только на ноутбуке; сервер ходит в Telegram напрямую
}.items():
    put(k, v)
if not get("SECRET_KEY"):
    put("SECRET_KEY", secrets.token_urlsafe(48))
if not get("ADMIN_TOKEN"):
    put("ADMIN_TOKEN", secrets.token_urlsafe(24))
# Пароль БД задаётся один раз, при первом запуске (база создаётся с ним)
if first and get("POSTGRES_PASSWORD") in ("", "gruzspec_local_dev"):
    put("POSTGRES_PASSWORD", secrets.token_urlsafe(24))
for k in ("API_BIND", "API_PORT", "FRONTEND_DIST_DIR", "DATABASE_URL"):
    text = re.sub(rf"^{k}=.*\n?", "", text, flags=re.M)
p.write_text(text, encoding="utf-8")
PY

say "Проверка DNS"
SERVER_IP="$(curl -4 -fsS --max-time 5 https://ifconfig.me || true)"
DNS_IP="$(dig +short A "$DOMAIN" | tail -1)"
echo "IP сервера: ${SERVER_IP:-?}   $DOMAIN → ${DNS_IP:-нет записи}"
if [ -n "$SERVER_IP" ] && [ "$SERVER_IP" != "$DNS_IP" ]; then
  echo "⚠ A-запись $DOMAIN пока не указывает на этот сервер. Сайт поднимется, но HTTPS-сертификат"
  echo "  Caddy получит, только когда DNS обновится (Cloudflare: A @ → $SERVER_IP, серое облако)."
fi

say "Сборка и запуск (первый раз 3–5 минут)"
make prod-up

say "Ночной бэкап базы (03:30, хранится 14 дней)"
cat > /etc/cron.d/gruzspec-backup <<CRON
30 3 * * * root cd $DIR && make prod-backup >/dev/null 2>&1 && find $DIR/backups -name '*.sql.gz' -mtime +14 -delete
CRON

say "Ждём HTTPS"
for _ in $(seq 1 40); do
  if curl -fsS --max-time 5 "https://$DOMAIN/healthz" >/dev/null 2>&1; then OK=1; break; fi
  sleep 5
done
echo
if [ "${OK:-0}" = 1 ]; then
  echo "✅ Готово: https://$DOMAIN"
else
  echo "⏳ HTTPS ещё не отвечает (обычно ждёт DNS). Проверить позже:  curl https://$DOMAIN/healthz"
  echo "   Логи:  cd $DIR && make prod-logs"
fi
echo "   Админка: https://$DOMAIN/admin"
echo "   Пароль админки (ADMIN_TOKEN):  grep ^ADMIN_TOKEN $DIR/.env"
echo "   Обновить после новых коммитов:  cd $DIR && git pull && make prod-up"
