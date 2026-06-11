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
  assets/                 # бинарные материалы (PDF лид-магнита) — едут на сервер через git
  migrations/             # alembic
  docs/                   # SPEC.md + исходники текстов
```

## Лид-магнит с вебинара (промт + реплей)

С вебинар-источников (`src_webinar`, `src_ig`, `src_tt`, `src_shorts` и любой
`src_yt*` — см. `is_webinar_source` в `config.py`) `/start` сразу отдаёт PDF
`assets/AIstack-competitor-analysis-prompt.pdf` + кнопку на запись эфира, затем
мостик в диагностику. Промт идемпотентен (повторный `/start` его не дублирует).

- `REPLAY_URL` в `.env` — ссылка на Unlisted-запись эфира (дефолт совпадает с прод).
  На сервере прописать в `/home/deploy/apps/aistack-bot/.env`.
- PDF лид-магнита **обязателен** в `assets/` и коммитится в репо (на сервер
  попадает через `git reset --hard`). Без файла webinar-ветка падает на отправке.

## Деплой

Систем-unit в `systemd/aistack-bot.service`, разворачиваем в `/opt/aistack-bot/` на том же VPS, что и лендинг. CI/CD — после шага 7.
