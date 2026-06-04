# AIstack — Память проекта

Снэпшот для Claude Desktop / Cowork. Кто-то заходит холодным и должен понимать
контекст без листания истории. Обновлять по факту изменений; что устарело —
сноси, не накапливай.

---

## 1. Что это и зачем

**Продукт:** онлайн-курс «AIstack: от идеи до запуска за 8 недель».
**Бренд:** AIstack, домен `aistackca.com`.
**Аудитория:** соло-фаундеры, эксперты, блогеры Центральной Азии
(Казахстан, Узбекистан, Кыргызстан, Таджикистан).
**УТП:** методология сборки AI-команды из 3 сотрудников; результат курса —
запущенный MVP + комьюнити фаундеров ЦА.

**Даты потока:**
- Старт: 2026-06-25 (четверг)
- Финал: 2026-08-13 (демо-день)
- Early-bird $200 (вместо $300) до 2026-06-10 23:59 Алматы, первые 20 мест

**Тарифы:**
- Самостоятельный — $200 (EB) / $300 (после): ~95 000 ₸ / ~2,4 млн сум (EB) или ~145 000 ₸ / ~3,6 млн сум
- С поддержкой — $500: ~240 000 ₸ / ~6 млн сум
- Персональный — $900: ~430 000 ₸ / ~10,8 млн сум (до 5 мест)

**Позиционирование автора:** Дмитрий Ватютов — **AI Product Coach**, автор курса AIstack
(не «соло-фаундер VYUD AI» — это устаревший фрейм, выпилен 28.05). Ключевой кейс — Garderob (казахстанский ресейл, $8 млн оценка, первая инвестиция европейского фонда в стартап ЦА).

---

## 2. Два репозитория, две роли

### aistack-landing — холодный трафик
- **GitHub:** `github.com/Retyreg/aistack-landing` (public)
- **Локально:** `~/ai-predprinimatel-landing/` (имя папки исторически не совпадает с репо — это тот же проект)
- **Прод:** `https://aistackca.com`
- **Хостинг:** ServerSpace 78.140.246.150 (`aicourse`), Docker + nginx, путь на сервере `/home/deploy/apps/aistack-landing/`
- **Стек:** Next 14 (App Router), TypeScript, Tailwind, shadcn/ui, Resend для писем

### aistack-bot — тёплый трафик
- **GitHub:** `github.com/Retyreg/aistack-bot` (public)
- **Локально:** `~/aistack-bot/`
- **Прод:** Telegram `@aistack_leads_bot` (id 8182205896, имя «AIstack Заявки»)
- **Хостинг:** ishosting 185.115.33.211, Python venv + Docker (только под Postgres) + systemd, путь `/home/deploy/apps/aistack-bot/`
- **Стек:** Python 3.10+, aiogram 3.x, SQLAlchemy 2.0 async, asyncpg, alembic, APScheduler, pydantic-settings

**Почему два хостинга:** ServerSpace в Алматы партиал-блочит Telegram-IP (из 5 проверенных только 1 пускает HTTPS). Жить на `/etc/hosts`-пине — фрагильно (Telegram ротирует пул). ishosting (другой провайдер, другая локация) даёт `HTTP 302 за 77мс` без танцев. Лендинг же на ServerSpace живёт нормально — ему Telegram не нужен.

---

## 3. Структура aistack-landing

### Основные файлы
- `content/landing.ts` — **источник правды для всех текстов и цен**. EARLY_BIRD config + computed-константы на module-load.
- `content/testimonials.json` — 15 отзывов, сортировка: сверху ЦА + фаундеры, ниже enterprise/employees.
- `components/sections/*.tsx` — все секции лендинга (Hero, Author, Pricing, Testimonials, FAQ, etc).
- `app/page.tsx` — главная.
- `app/api/lead/route.ts` — приём заявки.

### EARLY_BIRD механика (`content/landing.ts`)
```ts
EARLY_BIRD = { active, price:200, regular:300, deadline:"2026-06-10T23:59:59+05:00", seats:20, ... }
isEarlyBirdActive() — active && now <= deadline
```
Прод-страница рендерится static (build-time), поэтому **дата проверяется в момент билда**. После 10 июня нужен передеплой (любой push в main), чтобы цена переключилась на $300. Если забыть — `EARLY_BIRD.active = false` вручную.

### Pricing.tsx — рендер EB-оверлея
Доп. поля у плана: `priceStrikethrough` (зачёркнутая старая цена) и `pricePlate` («Цена первого потока · первые 20 мест · до 10 июня»). Рендерится только для self-тарифа в EB-период.

### Author.tsx
Парсер `**жирного**` для inline-эмфаза (Garderob, $8 млн). Остальная разметка/Tailwind — не трогать, любая правка копирайта = только текст в `landing.ts`.

### CI/CD лендинга
- `.github/workflows/deploy.yml` — на push в main: build gate (`npm run build`) → SSH в `deploy@78.140.246.150` → `git pull` → `docker compose up -d --build` → smoke (`curl aistackca.com` + grep маркеров).
- Секреты в GitHub: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` (это `~/.ssh/aistack_ci_ed25519` без passphrase).

---

## 4. Структура aistack-bot

### Раскладка
```
aistack-bot/
  bot.py                 — entrypoint, Dispatcher, scheduler start, dp.error
  config.py              — Settings (pydantic-settings + NoDecode для ADMIN_IDS)
  db/
    models.py            — Lead, Event
    session.py           — async engine + SessionLocal
  handlers/
    start.py             — /start с deep-link
    diagnostic.py        — 3 вопроса → сегмент → лид-магнит
    offer.py             — клики тарифов
    booking.py           — захват контакта (FSM), вопрос (FSM)
    admin.py             — /stats /lead /paid /broadcast (gated AdminOnly)
    common.py            — /stop, fallback, stale_callback
  keyboards/inline.py    — welcome_kb, q1/q2/q3_kb, offer_kb, book_now_self_eb_kb
  texts/
    messages.py          — ВСЕ user-facing строки
    prompts.py           — 3 набора по 4 промпта (лид-магнит)
  services/
    funnel.py            — calc_segment, drip_mode, render_offer
    scheduler.py         — drip_sweep + register_broadcasts
    broadcasts.py        — push_earlybird_closing / post / last_call
    notify.py            — send_admin
    analytics.py         — funnel_snapshot, format_stats
  tools/
    demo.py              — wipe/reset/nudge для записи демо
    force_broadcast.py   — ручной запуск броадкаста (без остановки polling)
  migrations/            — alembic (0001_initial.py — leads + events)
  systemd/aistack-bot.service
  .github/workflows/deploy.yml
  docs/
    SPEC.md              — оригинальное ТЗ
    funnel-texts.md      — исходные тексты воронки
    lead-magnet.md       — исходные тексты промптов
    PROJECT_MEMORY.md    — этот файл
```

### Схема БД (`migrations/0001_initial.py`)
**leads:** `id, telegram_id (unique), username, first_name, source, segment, diagnostic_answers (jsonb), diagnostic_completed_at, funnel_stage, next_touch, next_action_at, last_touch_at, tariff, contact_name, contact_phone, booked_at, paid_at, is_subscribed, created_at, updated_at`

**events:** `id, telegram_id, event_type, meta (jsonb), created_at`

`funnel_stage`: `new → diagnostic_done → warming → offered → booked → paid` (+ `lost`).

`event_type`: `start, diagnostic_start, diagnostic_complete, leadmagnet_sent, touch_sent, offer_shown, tariff_clicked, contact_captured, booked, paid, unsubscribed, question_asked, broadcast_sent`.

---

## 5. Воронка — поведение и расписание

### Маршрут лида
```
канал/YT → /start [?start=src_X]
  → upsert лида, source записывается ОДИН РАЗ (повторный /start не перезаписывает)
  → welcome + кнопка «Погнали»
  → диагностика 3 вопроса (inline-кнопки):
    Q1 «что тормозит» / Q2 «куда время» / Q3 «что освободит»
    ответы → {q1,q2,q3} ∈ {marketer, ops, product}
  → calc_segment (большинство, тай-брейк product > marketer > ops)
  → результат сегмента (A/B/C тексты) + 4 промпта + P.S.
  → next_touch=1, next_action_at = +interval (см. drip_mode)
  → drip_sweep (каждые DRIP_INTERVAL_MINUTES, дефолт 15):
    касание 1 → 2 → 3 → 4=оффер
  → оффер с 4 кнопками: 3 тарифа + «Остался вопрос»
  → self/supported → FSM waiting_for_contact → парс name+phone → booked + notify admin
  → personal → call invite + notify admin «🔥 горячий лид»
  → ask → FSM waiting_for_question → пересылка автору в личку
```

### drip_mode (services/funnel.py)
Считается из дельты между моментом диагностики и `EARLYBIRD_DEADLINE` в TZ Asia/Almaty:
- `≥5 дней` → `full`: 4 касания, интервал 24ч
- `2–4 дня` → `compressed`: 4 касания, 12ч
- `<2 дней` → `ultra`: касания 1+2+3 СКЛЕЕНЫ в одно (`WARMING_COMBINED`), потом оффер через 6ч
- `после дедлайна` → `post`: оффер сразу через 30мин, цена $300

### Броадкасты (services/broadcasts.py)
Регистрируются как DateTrigger при старте бота, считаются из `EARLYBIRD_DEADLINE`/`COURSE_START`:
- `push_earlybird_closing` — EB_DEADLINE - 1 день, 19:00 Алматы. Текст «завтра $200 закрывается» + кнопка `Забронировать за $200` (TariffChoice code="self")
- `push_post_earlybird` — EB_DEADLINE + 1 день, 12:00. «Поезд не ушёл», полный набор тарифов с $300
- `push_last_call` — COURSE_START - 2 дня, 19:00. «Финальный заход»

Идемпотентность: per-lead per-kind, окно 24ч. Тех, кому уже отправили — пропускаем. Throttle 20 msg/sec. TelegramForbiddenError → `is_subscribed=false`. Аудитория всегда `funnel_stage NOT IN (booked, paid) AND is_subscribed`.

### Цена $200 ↔ $300 переключается автоматом
`funnel.is_early_bird_active()` смотрит текущую дату относительно `EARLYBIRD_DEADLINE`. `render_offer(now)` рендерит правильный шаблон + соответствующую клавиатуру. Никаких отдельных задач на 10 июня — это делается на лету в момент рендера.

### Edge cases (handled)
- Повторный `/start` — `source` НЕ перезаписывается; `funnel_stage` НЕ откатывается на warming если лид уже в offered/booked/paid (это в `diagnostic.on_q3`)
- Юзер заблокировал бота — `dp.error()` ловит `TelegramForbiddenError`, выставляет `is_subscribed=false`, бот не падает
- Старые inline-кнопки (после рестарта) — `stale_callback` в common.py отвечает тостом «эта кнопка устарела»
- Мусорный ввод контакта — `parse_contact` глотает любой текст (если телефона regex не находит — всё уходит в `contact_name`, телефон null)
- Лид не дошёл до оффера к COURSE_START — drip_sweep тихо пропускает

---

## 6. Сервера и доступы

### ishosting — bot
- IP: `185.115.33.211`
- ОС: Ubuntu 22.04.5 LTS, Python 3.10.12, Docker 29.1.3
- Пользователь: `deploy` (с NOPASSWD sudo, в группе `docker`)
- SSH-ключ: `~/.ssh/aistack_ci_ed25519` (без passphrase, тот же что для landing CI/CD)
- Postgres 16-alpine в Docker, имя контейнера `aistack-bot-postgres`, порт 5433:5432, volume `aistack-bot-pg`, пароль рандомный в .env
- systemd-юнит: `aistack-bot.service`, User=deploy, EnvironmentFile=`/home/deploy/apps/aistack-bot/.env`, ExecStart=`/home/deploy/apps/aistack-bot/.venv/bin/python bot.py`
- Polling один экземпляр; перезагрузка VPS — systemd поднимет автоматом

### ServerSpace — landing
- IP: `78.140.246.150` (`aicourse`)
- ОС: Ubuntu 24.04, Python 3.12, Docker
- Пользователь: `deploy`
- Hostingt landing через `docker-compose.prod.yml` (Next 14 app + nginx + certbot)
- Тот же SSH-ключ `aistack_ci_ed25519`
- **На этом сервере бот ранее тоже стоял** — сейчас systemd disabled + остановлен. Postgres-контейнер и репо `/home/deploy/apps/aistack-bot` остались (можно снести)

### GitHub
- `Retyreg/aistack-landing` — лендинг, public
- `Retyreg/aistack-bot` — бот, public (приватный изначально создавался, потом сделан public чтобы сервер мог cloneить без креденшелов; секретов в коде нет, .env гитигнорится)
- gh CLI на маке авторизован под Retyreg

### Telegram
- BOT_TOKEN: в `.env` локально (`~/aistack-bot/.env`) и на сервере (`/home/deploy/apps/aistack-bot/.env`). Получен через @BotFather, бот `@aistack_leads_bot`.
- ADMIN_IDS: `5701645456` (telegram_id Дмитрия). Все админ-команды (/stats /lead /paid /broadcast) и уведомления о бронях уходят на этот id.

### Где НЕТ хранения секретов
- В git репо — никогда (gitignore: `.env`, `.env.*`)
- В этом MEMORY-файле — только пути, не значения

---

## 7. CI/CD

### Бот (aistack-bot)
`.github/workflows/deploy.yml`:
1. **build gate**: setup-python@v5 3.10, `pip install -r requirements.txt`, `python -m compileall` по всем модулям
2. **deploy**: ssh в `deploy@185.115.33.211` → `git fetch + reset --hard origin/main` → `.venv/bin/pip install -r requirements.txt` → `alembic upgrade head` → `sudo systemctl restart aistack-bot` → `is-active`
3. **smoke**: `journalctl -u aistack-bot --since "60 seconds ago" | grep "Run polling for bot"`

Триггер: `push: branches: [main]` или manual `workflow_dispatch`.
Концарренси: `deploy-prod`, без cancel — последовательные деплои не отменяются.

Секреты в репо: `VPS_HOST=185.115.33.211`, `VPS_USER=deploy`, `VPS_SSH_KEY=<содержимое aistack_ci_ed25519>`.
Host-key пиним прямо в workflow (известный отпечаток сервера) — без TOFU.

### Лендинг (aistack-landing)
Та же логика, но deploy = `docker compose up -d --build`. Хост `78.140.246.150`. Те же секреты.

### Авто-деплой за ~1 минуту
Push в main → workflow стартует через ~5 сек, build gate ~30с, deploy + restart ~20с, smoke ~5с. До этого `git pull` на сервере был ручной — больше не нужен.

---

## 8. Ключевые архитектурные решения (с обоснованием)

| Решение | Почему |
|---|---|
| Long polling (а не webhook) | Простота, без TLS на боте, без открытых портов |
| MemoryStorage для FSM | Диагностика/бронь — короткие транзитные потоки, рестарт = юзер повторит шаг. Redis заложен как опция, но не нужен на старте |
| Postgres в Docker (не нативно) | Изолированная версия 16-alpine, тот же подход что в dev, легко сносить/обновлять |
| Per-lead per-broadcast dedup через events.meta | Идемпотентность даже при рестарте в окне misfire_grace_time |
| pydantic-settings `NoDecode` для `ADMIN_IDS` | pydantic-settings v2 пытается распарсить `list[int]` как JSON; `ADMIN_IDS=5701645456` (без [ ]) тихо становится `[]`. NoDecode пропускает значение в `field_validator` как строку |
| User=deploy в systemd | /home/deploy имеет права 750, root не в группе deploy → EnvironmentFile не читался. Запуск под deploy решает + это банально безопаснее |
| PYTHONUNBUFFERED=1 в systemd | Без него Python буферит stdout, в journald логи появляются с большой задержкой |
| Tariff value — строковые ID (self/supported/personal), не суммы | Конвенция лендинга; цены динамически переключаются ($200↔$300), а лид/метрика лукапит по ID |
| Markdown `**жирный**` в текстах | Минимальный inline-парсер для эмфаза (Garderob, $8 млн), не тащить markdown-либ |
| Move bot от ServerSpace на ishosting | DPI у казахстанского провайдера блочит почти все Telegram-IP. `/etc/hosts`-пин на одну рабочую IP — фрагильно. ishosting (тот же геo, другой провайдер) даёт чистый коннект |

---

## 9. Хронология работ (большие вехи)

| Дата | Что сделано |
|---|---|
| 2026-05-22 | Лендинг aistackca.com развёрнут на ServerSpace (Docker + nginx + Let's Encrypt) |
| 2026-05-28 | Секция Testimonials (7 отзывов), CI/CD landing (push → SSH → docker rebuild) |
| 2026-05-29 | Полный rewrite авторского блока (AI Product Coach, Garderob), новые цены, EARLY_BIRD config |
| 2026-05-30 | Видео-блок: смена YouTube embed URL |
| 2026-05-31 | +8 новых отзывов (5 с фото, 3 заглушка с инициалами), пересортировка по ЦА + фаундерам |
| 2026-06-02 | Бот: шаги 1-7 реализованы локально, end-to-end проверены. Деплой на ServerSpace упал на блокировке Telegram. Миграция на ishosting. CI/CD для бота поднят |
| 2026-06-03 | Демо-сценарий для видео (`tools/demo.py` — wipe/nudge/reset), запись |

---

## 10. Открытые задачи

- **ServerSpace cleanup**: aistack-bot systemd disabled, но Postgres-контейнер `aistack-bot-postgres` и `/home/deploy/apps/aistack-bot/` ещё лежат. Можно `docker rm -f aistack-bot-postgres && docker volume rm aistack-bot_aistack-bot-pg && rm -rf ~/apps/aistack-bot` под deploy
- **Persona $900 после клика**: `tariff_clicked` логируется, `lead.tariff='personal'` ставится, но `funnel_stage` остаётся `offered` (брони через бота нет — только созвон). После оплаты — `/paid <id>` руками
- **Deep-link источники в каналах**: t.me/aistack_leads_bot`?start=src_channel` (закреп Telegram), `?start=src_yt` (описание YouTube), `?start=src_yt_<video>` (конкретное видео) — раздать в реальные каналы
- **Запасной канал на случай блокировки ishosting**: если когда-нибудь Telegram перестанет открываться — можно поднять MTProxy или вернуться на схему `/etc/hosts`-пин (149.154.167.220 был рабочим на ServerSpace)
- **Postgres backup**: пока нет автоматики. Лиды накапливаются — стоит поставить хотя бы `docker exec aistack-bot-postgres pg_dump` по крону в S3/object storage
- **Метрики `/stats` через 1+ неделю реального трафика**: формулы конверсий проверены на 1 лиде; нужно убедиться что по 100+ работает (сложных запросов нет, но всё же)

---

## 11. Часто нужные команды

### Локально
```bash
# Лендинг dev
cd ~/ai-predprinimatel-landing && npm run dev

# Бот dev (Postgres в docker compose)
cd ~/aistack-bot
docker compose up -d
source .venv/bin/activate
alembic upgrade head
python bot.py
```

### Сервер бота (ishosting)
```bash
# SSH
ssh -i ~/.ssh/aistack_ci_ed25519 deploy@185.115.33.211

# На сервере
sudo systemctl status aistack-bot
sudo journalctl -u aistack-bot -f
sudo systemctl restart aistack-bot

# БД
docker exec aistack-bot-postgres psql -U aistack -d aistack

# Демо-режим (DRIP_INTERVAL_MINUTES=1 на время съёмки)
sed -i 's/^DRIP_INTERVAL_MINUTES=.*/DRIP_INTERVAL_MINUTES=1/' .env
sudo systemctl restart aistack-bot
.venv/bin/python -m tools.demo wipe 5701645456
.venv/bin/python -m tools.demo nudge 5701645456

# Возврат в прод
sed -i 's/^DRIP_INTERVAL_MINUTES=.*/DRIP_INTERVAL_MINUTES=15/' .env
sudo systemctl restart aistack-bot
```

### Сервер лендинга (ServerSpace)
```bash
ssh -i ~/.ssh/aistack_ci_ed25519 deploy@78.140.246.150
cd ~/apps/aistack-landing
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f app
```

### Принудительный броадкаст (на боте)
```bash
ssh -i ~/.ssh/aistack_ci_ed25519 deploy@185.115.33.211 \
  "cd ~/apps/aistack-bot && .venv/bin/python -m tools.force_broadcast earlybird_closing"
# Чтобы повторно запустить в течение 24ч (дедуп):
# DELETE FROM events WHERE event_type='broadcast_sent';
```

---

## 12. Что НЕ делать

- **Не запускать локальный `python bot.py` пока systemd на ishosting активен** — Telegram запрещает два polling-клиента на один токен, один из них будет получать `TelegramConflictError` в бесконечном цикле
- **Не править `EARLY_BIRD.active` в лендинге без передеплоя** — страница static, изменение применится только после нового build. Простой `git pull` без build не сработает (CI/CD делает оба шага)
- **Не коммитить `.env`** — gitignore стоит, но всё равно проверь `git status` перед `git add`
- **Не использовать `git add -A` слепо** — у обоих проектов есть data/ и leads.jsonl, которые могут оказаться нежелательными в коммите
- **Не запускать миграции вручную поверх прода** без alembic — используй `alembic upgrade head`, не raw SQL. CI/CD уже это делает.
- **Не хранить SSH-ключи в репо** даже в формате .pub
