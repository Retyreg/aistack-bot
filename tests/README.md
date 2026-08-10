# Проверки

Три скрипта без внешних зависимостей (никакого pytest — в проекте его нет).
Каждый печатает построчный отчёт и выходит с ненулевым кодом при провале.

| файл | что покрывает | нужна БД |
|---|---|---|
| `test_logic.py` | сборка роутеров, арифметика стадий напоминаний, клэмпинг при поздней регистрации, форматирование текстов, отсутствие вбитых руками дат | нет |
| `test_db.py` | `/sources` по периодам и null-меткам, полная цепочка напоминаний, протухшие касания, `/stop`, `/webinars` | да |
| `test_audit.py` | аудит от падения LLM до доставки вердикта (как есть и после правки) | да |
| `test_llm_retry.py` | повтор на пустом `content`, отсутствие повтора на HTTP-ошибке | нет |

## Запуск

```bash
docker compose up -d
alembic upgrade head
.venv/bin/python tests/test_logic.py
.venv/bin/python tests/test_db.py
.venv/bin/python tests/test_audit.py
.venv/bin/python tests/test_llm_retry.py
```

`test_db.py` и `test_audit.py` **пишут в БД** из `DATABASE_URL`. Гоняй их на
локальной базе из `docker-compose.yml` (дефолт) или подставь свою через
`TEST_DATABASE_URL`. На прод-базу не наводить.

База должна быть в **UTF8** (`postgres:16-alpine` из compose — по умолчанию
да). На кластере в SQL_ASCII `test_audit.py` падает на кириллице в JSONB —
это про кодировку базы, а не про код.

Между прогонами чистить:

```bash
psql "$DB" -c "truncate leads, events, audit_requests, webinar_registrations restart identity;"
```

Polling эти проверки не поднимают: Telegram заменён заглушкой `FakeBot`.
Это осознанно — в боевом `.env` живой `BOT_TOKEN`, и второй поллер на том же
токене положил бы прод в `TelegramConflictError`.
