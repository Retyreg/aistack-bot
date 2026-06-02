# ТЗ — Telegram бот-воронка для AIstack

Документ для реализации. Скармливается Claude Code как спека. Копирайт сюда не дублируется — берётся из двух готовых файлов:

- **Тексты воронки** (welcome, прогрев, оффер, пуши, дожим) → `docs/funnel-texts.md`
- **Лид-магнит, 3 набора промптов** → `docs/lead-magnet.md`

При реализации перенести их в `texts/messages.py` и `texts/prompts.py`.

---

## 1. Цель

Телеграм-нативная воронка для тёплой аудитории курса AIstack: канал/YouTube → бот. Вход — диагностика «какого AI-сотрудника нанять первым» → выдача лид-магнита → прогрев → оффер с лестницей тарифов → бронь в боте → уведомление автору (счёт выставляется вручную).

**Жёсткие даты потока** (зашить в конфиг): early-bird $200 до **2026-06-10**, старт **2026-06-25**, демо-день 2026-08-13. Таймзона аудитории — **Asia/Almaty** (UTC+5).

**Оплата:** ручная. Бот фиксирует бронь и шлёт автору уведомление в личку. Платёжных интеграций НЕТ.

---

## 2. Стек

- Python 3.11+
- **aiogram 3.x** (long polling, не webhook — проще на VPS)
- **PostgreSQL** + SQLAlchemy 2.0 (async, `asyncpg`) + Alembic (миграции)
- **APScheduler** (`AsyncIOScheduler`) — отложенные касания и пуши по датам
- FSM storage: `MemoryStorage` (FSM используется только транзитно — диагностика и захват контакта; при рестарте пользователь просто повторяет шаг). Redis — опциональный апгрейд, заложить интерфейс, но не обязателен.
- `pydantic-settings` или `python-dotenv` для конфига

`requirements.txt`: aiogram>=3.4, SQLAlchemy[asyncio]>=2.0, asyncpg, alembic, APScheduler>=3.10, pydantic-settings, python-dotenv, pytz/tzdata.

---

## 3. Структура проекта

```
aistack-bot/
  bot.py                  # entrypoint: Bot, Dispatcher, routers, scheduler start, polling
  config.py               # Settings из .env
  db/
    models.py             # SQLAlchemy модели Lead, Event
    session.py            # async engine + sessionmaker, get_session()
  handlers/
    start.py              # /start + deep-link, welcome
    diagnostic.py         # 3 вопроса, подсчёт сегмента, выдача результата + лид-магнита
    offer.py              # оффер, выбор тарифа, "остался вопрос"
    booking.py            # захват контакта (FSM), бронь
    admin.py              # /stats, /paid, /lead, /broadcast (gated по ADMIN_IDS)
    common.py             # /stop (отписка), fallback
  keyboards/
    inline.py             # все инлайн-клавиатуры + callback_data
  texts/
    messages.py           # ВСЕ тексты воронки (из файла с текстами)
    prompts.py            # 3 набора промптов (из файла лид-магнита)
  services/
    funnel.py             # segment calc, переходы стадий, расчёт расписания дрипа
    scheduler.py          # APScheduler: drip sweep + броадкасты по датам
    analytics.py          # лог событий, агрегаты для /stats
    notify.py             # уведомления автору в личку
  migrations/             # alembic
  .env.example
  README.md
  systemd/aistack-bot.service
```

---

## 4. Конфиг (.env)

```
BOT_TOKEN=
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/aistack
ADMIN_IDS=11111111
TIMEZONE=Asia/Almaty
EARLYBIRD_DEADLINE=2026-06-10
COURSE_START=2026-06-25
LANDING_URL=https://aistackca.com
LANDING_SELF=https://aistackca.com/#lead-self
LANDING_SUPPORTED=https://aistackca.com/#lead-supported
LANDING_PERSONAL=https://aistackca.com/#lead-personal
AUTHOR_CONTACT=@vatyutov
```

---

## 5. Схема БД

### Таблица `leads`

| поле | тип | примечание |
|---|---|---|
| id | bigserial PK | |
| telegram_id | bigint UNIQUE NOT NULL | |
| username | varchar NULL | |
| first_name | varchar NULL | |
| source | varchar NULL | из deep-link payload |
| segment | varchar NULL | `marketer` / `ops` / `product` |
| diagnostic_answers | jsonb NULL | `{"q1":"marketer","q2":"ops","q3":"marketer"}` |
| diagnostic_completed_at | timestamptz NULL | |
| funnel_stage | varchar NOT NULL DEFAULT 'new' | см. перечисление ниже |
| next_touch | smallint NOT NULL DEFAULT 0 | номер следующего касания прогрева (1..4) |
| next_action_at | timestamptz NULL | когда отправить следующее касание дрипа |
| last_touch_at | timestamptz NULL | |
| tariff | varchar NULL | `self` / `supported` / `personal` |
| contact_name | varchar NULL | |
| contact_phone | varchar NULL | |
| booked_at | timestamptz NULL | |
| paid_at | timestamptz NULL | проставляется вручную командой /paid |
| is_subscribed | boolean NOT NULL DEFAULT true | false = /stop, дрип и пуши не шлём |
| created_at | timestamptz NOT NULL DEFAULT now() | |
| updated_at | timestamptz NOT NULL DEFAULT now() | |

**funnel_stage** (перечисление): `new` → `diagnostic_done` → `warming` → `offered` → `booked` → `paid` · отдельно `lost`.

### Таблица `events`

| поле | тип |
|---|---|
| id | bigserial PK |
| telegram_id | bigint NOT NULL |
| event_type | varchar NOT NULL |
| meta | jsonb NULL |
| created_at | timestamptz NOT NULL DEFAULT now() |

`event_type`: `start`, `diagnostic_start`, `diagnostic_complete`, `leadmagnet_sent`, `touch_sent` (meta: `{"n":1}`), `offer_shown`, `tariff_clicked` (meta: `{"tariff":"self"}`), `contact_captured`, `booked`, `paid`, `unsubscribed`, `question_asked`.

---

## 6. FSM состояния

```python
class DiagnosticFlow(StatesGroup):
    q1 = State()
    q2 = State()
    q3 = State()

class BookingFlow(StatesGroup):
    waiting_for_contact = State()
```

---

## 7. Потоки и контракты — см. полный текст в исходном промте

Краткий перечень шагов: /start (upsert + welcome) → diagnostic (3 вопроса → сегмент → результат + лид-магнит) → drip 1-4 (планировщик) → offer (выбор тарифа) → booking (FSM захват контакта, уведомление автору) → /stop, fallback. Полные контракты — в оригинальном промте, перенос сюда — позже.

## 8. Планировщик

`drip_sweep` каждые 15 минут, броадкасты по абсолютным датам (09.06 пуш, 10.06 переключение цены, 11.06 пост-EB, 23.06 last call). Расписание дрипа сжимается под дедлайн EARLYBIRD_DEADLINE.

## 11. Деплой (ServerSpace VPS)

Python venv, `pip install -r requirements.txt`, alembic upgrade head, systemd unit `systemd/aistack-bot.service` с auto-restart. Один экземпляр polling (несколько = конфликт).

## 13. Критерии приёмки — см. оригинал, шаг 7 итерации.

## 14. Реализация инкрементально

Шаги: каркас → диагностика → scheduler+drip → оффер+бронь → броадкасты+цена → админ+метрики → edge cases.
