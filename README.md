# aistack-bot

Telegram-воронка для курса [AIstack](https://aistackca.com). Спека — `docs/SPEC.md`.

## Стек

Python 3.11+, aiogram 3.x, PostgreSQL + SQLAlchemy 2.0 (async), Alembic, APScheduler. Long polling, FSM на MemoryStorage.

## Локальный запуск (dev)

```bash
cd ~/aistack-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Postgres в контейнере
docker compose up -d

# Конфиг
cp .env.example .env
# заполнить BOT_TOKEN (получить у @BotFather, лучше тестовый) и ADMIN_IDS (свой telegram_id, узнать у @userinfobot)

# Миграции
alembic upgrade head

# Запуск
python bot.py
```

Отправь боту `/start` в Telegram → должно прийти приветствие с кнопкой «Погнали →».

## Дорожная карта (по разделу 14 спеки)

- [x] Шаг 1 — скелет: config, db/models, session, bot.py, alembic, /start + welcome
- [ ] Шаг 2 — диагностика (3 вопроса) + выдача лид-магнита
- [ ] Шаг 3 — scheduler + drip_sweep + касания 1–4 → оффер
- [ ] Шаг 4 — выбор тарифа + бронь + уведомления автору
- [ ] Шаг 5 — броадкасты по датам + переключение цены $200/$300
- [ ] Шаг 6 — админ-команды + метрики
- [ ] Шаг 7 — edge cases + прогон по критериям приёмки (раздел 13)

## Структура

```
aistack-bot/
  bot.py                  # entrypoint
  config.py               # Settings из .env
  db/                     # SQLAlchemy модели + async session
  handlers/               # /start, /stop, fallback (шаг 1); диагностика и оффер — далее
  keyboards/              # инлайн-клавиатуры
  texts/                  # копирайт воронки + промпты лид-магнита
  services/               # notify, funnel logic, scheduler
  migrations/             # alembic
  docs/                   # SPEC.md + исходники текстов
```

## Деплой

Систем-unit в `systemd/aistack-bot.service`, разворачиваем в `/opt/aistack-bot/` на том же VPS, что и лендинг. CI/CD — после шага 7.
