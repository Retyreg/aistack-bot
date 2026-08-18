#!/usr/bin/env bash
# Развёртывание aistack-bot на чистом Ubuntu-сервере (без переноса данных).
# Идемпотентно: можно запускать повторно. Запускать ОТ ROOT на новом сервере.
#
# Секреты НЕ хардкодим — передаём при запуске:
#   BOT_TOKEN=123:ABC ADMIN_IDS=12345678 bash bootstrap_new_server.sh
# Пароль БД можно передать своим (DB_PASSWORD=...), иначе сгенерируется случайный.
#
# Что делает: пакеты + Docker (Postgres) + юзер deploy + git clone (public repo)
#   + .env + venv + alembic upgrade + systemd-юнит + sudoers + запуск бота.
set -euo pipefail

: "${BOT_TOKEN:?Передай BOT_TOKEN=... (токен у @BotFather)}"
: "${ADMIN_IDS:?Передай ADMIN_IDS=... (твой telegram_id, узнать у @userinfobot)}"
REPLAY_URL="${REPLAY_URL:-https://youtu.be/lsA4xftUMCk}"
# Пароль БД: если не передан — генерируем случайный (32 буквенно-цифровых).
# Только [A-Za-z0-9] — пароль уходит внутрь URL DATABASE_URL, спецсимволы
# пришлось бы percent-кодировать.
DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | cut -c1-32)}"

APP_USER=deploy
APP_HOME="/home/${APP_USER}"
APP_DIR="${APP_HOME}/apps/aistack-bot"
REPO="https://github.com/Retyreg/aistack-bot.git"

echo "==> 1/9 system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git python3-venv python3-dev ca-certificates curl gnupg

echo "==> 2/9 Docker (для Postgres)"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable --now docker

echo "==> 3/9 user ${APP_USER}"
id -u "${APP_USER}" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "${APP_USER}"
usermod -aG docker "${APP_USER}"

echo "==> 4/9 clone/update repo (public)"
# Каталог и git-операции — от имени deploy (он владелец репо), иначе git
# 2.34+ ругается 'dubious ownership' при запуске от root.
install -d -o "${APP_USER}" -g "${APP_USER}" "${APP_HOME}/apps"
if [ -d "${APP_DIR}/.git" ]; then
  sudo -u "${APP_USER}" git -C "${APP_DIR}" fetch origin main
  sudo -u "${APP_USER}" git -C "${APP_DIR}" reset --hard origin/main
else
  sudo -u "${APP_USER}" git clone "${REPO}" "${APP_DIR}"
fi

echo "==> 5/9 .env (не перезатираю существующий)"
if [ ! -f "${APP_DIR}/.env" ]; then
  cat > "${APP_DIR}/.env" <<EOF
BOT_TOKEN=${BOT_TOKEN}
POSTGRES_PASSWORD=${DB_PASSWORD}
DATABASE_URL=postgresql+asyncpg://aistack:${DB_PASSWORD}@localhost:5433/aistack
ADMIN_IDS=${ADMIN_IDS}
TIMEZONE=Asia/Almaty
EARLYBIRD_DEADLINE=2026-06-10
COURSE_START=2026-06-25
LANDING_URL=https://aistackca.com
LANDING_SELF=https://aistackca.com/#lead-self
LANDING_SUPPORTED=https://aistackca.com/#lead-supported
LANDING_PERSONAL=https://aistackca.com/#lead-personal
AUTHOR_CONTACT=@vatyutov
DRIP_INTERVAL_MINUTES=15
REPLAY_URL=${REPLAY_URL}
EOF
  echo "    .env создан"
else
  echo "    .env уже есть — пропускаю (проверь REPLAY_URL вручную)"
fi
chown -R "${APP_USER}:${APP_USER}" "${APP_HOME}/apps"

echo "==> 6/9 Postgres (docker compose)"
docker compose -f "${APP_DIR}/docker-compose.yml" up -d
# подождать готовности БД
for i in $(seq 1 30); do
  if docker exec aistack-bot-postgres pg_isready -U aistack -d aistack >/dev/null 2>&1; then
    echo "    postgres ready"; break
  fi
  sleep 1
done

echo "==> 7/9 venv + зависимости"
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/.venv"
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "${APP_USER}" "${APP_DIR}/.venv/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"

echo "==> 8/9 alembic upgrade head"
sudo -u "${APP_USER}" bash -c "cd '${APP_DIR}' && .venv/bin/alembic upgrade head"

echo "==> 9/9 systemd + sudoers + запуск"
cp "${APP_DIR}/systemd/aistack-bot.service" /etc/systemd/system/aistack-bot.service
cat > /etc/sudoers.d/aistack-bot-deploy <<EOF
${APP_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart aistack-bot, /usr/bin/systemctl is-active aistack-bot
EOF
chmod 0440 /etc/sudoers.d/aistack-bot-deploy
systemctl daemon-reload
systemctl enable aistack-bot
systemctl restart aistack-bot
sleep 5

echo "================= РЕЗУЛЬТАТ ================="
systemctl is-active aistack-bot && echo "СЕРВИС АКТИВЕН ✅" || echo "СЕРВИС НЕ ПОДНЯЛСЯ ❌"
echo "--- последние логи ---"
journalctl -u aistack-bot --no-pager -n 25
echo "============================================"
echo "Готово. Проверь бота: отправь /start в Telegram."
