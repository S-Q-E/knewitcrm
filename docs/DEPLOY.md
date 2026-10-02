# Деплой на Railway (Шаг 15)

Один Docker-контейнер: Python sirve API + собранный SPA, воркеры крутятся
внутри процесса (asyncio-задачи, advisory-lock). Два окружения: **staging**
и **production** — отдельные Railway-сервисы и отдельные БД.

## 1. Окружения

| | Staging | Production |
|---|---|---|
| Назначение | Проверка релизов перед продом | Рабочая CRM менеджеров |
| Ветка/тег | `develop` (авто) | Тег `v*` (авто) или ручной запуск |
| Postgres | Отдельный Railway Postgres (свой, пустой) | Продовая БД n8n (общая с ботом!) |
| Bot-таблицы | Seed из `tests/fixtures/` (см. ниже) | Живые `knewit_*` (только чтение + `bot_bridge`) |
| `APP_ENV` | `staging` | `production` |

Staging **никогда** не подключается к продовой БД n8n: staging-backfill
создаёт контакты/сделки, а `bot_bridge` пишет в `knewit_leads` /
`knewit_events` / `knewit_messages` — на проде это затронуло бы живых
клиентов (см. D24).

Поднять staging-БД из фикстур (одноразово, локально с проброшенным URL):

```bash
psql "$STAGING_DATABASE_URL" -f tests/fixtures/knewit_schema.sql
psql "$STAGING_DATABASE_URL" -f tests/fixtures/seed.sql
# crm_*-таблицы создадут миграции при первом старте контейнера.
```

## 2. Переменные окружения

Задавать в Railway → Service → Variables. Значения с секретами — только
через интерфейс Railway (или Reference Variables), никогда в репозиторий.

| Переменная | Staging | Production | Комментарий |
|---|---|---|---|
| `DATABASE_URL` | Reference на staging-Postgres | Reference на прод-Postgres n8n | Внутренний адрес (`postgres.railway.internal`), см. п. 3 |
| `SECRET_KEY` | Случайные 64 hex-символа | Другие случайные 64 hex-символа | `openssl rand -hex 32`; нужен тулзам, сессии — opaque-токены (D6/D9) |
| `APP_ENV` | `staging` | `production` | Имя попадает в Sentry-environment |
| `COOKIE_SECURE` | `true` | `true` | Куки только по HTTPS; `false` — только локально |
| `ALLOWED_ORIGINS` | URL staging-домена | URL prod-домена | Пусто = только same-origin (SPA раздаётся тем же контейнером) |
| `ADMIN_EMAIL` | Email первого админа | Email первого админа | Только первый запуск, потом игнорируется |
| `ADMIN_PASSWORD` | Временный пароль (мин. 10 симв.) | Временный пароль (мин. 10 симв.) | Только первый запуск — **удалить сразу после** (п. 5) |
| `N8N_SEND_WEBHOOK_URL` | Staging-вебхук n8n (или пусто) | Production-вебхук `.../webhook/crm-send-message` | Пусто = отправка падает в `failed` с подсказкой |
| `N8N_WEBHOOK_SECRET` | Секрет staging | Секрет production | Тот же, что `$env.N8N_WEBHOOK_SECRET` в n8n (см. `docs/n8n/README.md`) |
| `DEFAULT_TIMEZONE` | `Asia/Almaty` | `Asia/Almaty` | Границы суток в аналитике |
| `DEFAULT_CURRENCY` | `KZT` | `KZT` | Валюта сумм по умолчанию |
| `LOG_LEVEL` | `INFO` | `WARNING` | JSON-логи; `DEBUG` только для разбора инцидента |
| `SENTRY_DSN` | (опц., свой проект) | (опц., свой проект) | Пусто = Sentry выключен и на бэке, и на фронте |
| `METRICS_TOKEN` | Случайный токен | Случайный токен | Bearer для `/api/metrics`; пусто = 404 |
| `TRUSTED_PROXY_HOPS` | `1` | `1` | Один прокси — сам Railway |
| `PORT` | — | — | Выставляет сам Railway, не задавать |

Фронтендовый `VITE_SENTRY_DSN` вшивается **на этапе сборки** (`npm run build`
в Dockerfile): для staging/production нужны разные сборки — это ещё одна
причина держать два отдельных сервиса, а не один с переключением.

## 3. Подключение БД n8n и права (production)

CRM делит продовый Postgres с ботом. Схема `knewit_*` принадлежит n8n
(правило 1): CRM запрещено её менять, триггеры запрещены, пишет только
`bot_bridge.py` (UPDATE трёх колонок лида + INSERT события/сообщения).

### 3.1. Отдельная роль `crm_app` (наименьшие права)

Выполнить **владельцем продовой БД** (один раз):

```sql
-- Роль приложения. Пароль сгенерировать: openssl rand -base64 24.
CREATE ROLE crm_app WITH LOGIN PASSWORD '<сгенерировать>' NOSUPERUSER NOCREATEDB NOCREATEROLE;

GRANT CONNECT ON DATABASE "<prod_db>" TO crm_app;
GRANT USAGE, CREATE ON SCHEMA public TO crm_app;
-- CREATE ON SCHEMA нужен миграциям: новые таблицы crm_* создаёт crm_app
-- и автоматически ими владеет (полные права без дополнительных GRANT).

-- Чтение бота (дашборды, диалоги, аналитика, sync-worker).
GRANT SELECT ON knewit_leads, knewit_messages, knewit_events, knewit_followups TO crm_app;

-- Запись бота — ровно то, что делает bot_bridge.py (см. D3/D6), не больше:
-- update_bot_stage: current_stage/previous_stage/updated_at лида...
GRANT UPDATE (current_stage, previous_stage, updated_at) ON knewit_leads TO crm_app;
-- ...+ INSERT manual_stage_change в события; insert_outgoing_message: INSERT сообщения.
GRANT INSERT ON knewit_events, knewit_messages TO crm_app;
-- Серийные ключи новых строк событий/сообщений (имена уточнить: \ds knewit_*):
GRANT USAGE, SELECT ON SEQUENCE knewit_events_id_seq, knewit_messages_id_seq TO crm_app;
```

`DATABASE_URL` production собирается с этой ролью:

```
postgresql://crm_app:<пароль>@postgres.railway.internal:5432/<prod_db>
```

В Railway — через Reference Variable на продовый Postgres, но с заменой
пользователя/пароля на `crm_app` (Reference подставляет владельца —
переписать вручную согласно SQL выше).

### 3.2. Проверка прав

```sql
-- От имени crm_app (psql "postgresql://crm_app@..."):
SELECT * FROM knewit_leads LIMIT 1;          -- ok
SELECT * FROM crm_users LIMIT 1;              -- ok после миграций
CREATE TABLE crm_probe (id serial PRIMARY KEY); DROP TABLE crm_probe;  -- ok
ALTER TABLE knewit_leads ADD COLUMN x text;   -- ДОЛЖНО упасть (permission denied)
DROP TABLE knewit_messages;                   -- ДОЛЖНО упасть
```

Негативные проверки обязательны: доказывают, что приложение физически не
может повредить схему бота, даже при баге.

## 4. Домен и HTTPS

Railway → Service → Settings → Networking → Generate Domain (или Custom
Domain + CNAME). HTTPS выпускается автоматически; `COOKIE_SECURE=true`
требует именно HTTPS (иначе браузер не отдаст сессию и логин закольцуется).
HSTS-заголовок уже выставляется бэкендом (D22).
`ALLOWED_ORIGINS` — только прод-домен (или пусто при same-origin).

## 5. Первый запуск (порядок)

1. Задеплоить сервис с переменными из п. 2, включая `ADMIN_EMAIL` /
   `ADMIN_PASSWORD`. В логах: `alembic ... upgrade head` → применение
   миграций `0001...0018`, затем `uvicorn ... --workers 2`.
2. `GET /api/health` → `{"ok":true}` (это же дёргает Railway-healthcheck).
3. Залогиниться под `ADMIN_EMAIL` / `ADMIN_PASSWORD`, сменить пароль.
4. **Удалить `ADMIN_PASSWORD`** из переменных и передеплоить (переменные
   с пустым значением игнорируются — bootstrap срабатывает только при
   нуле админов, D9).
5. Backfill: в логах sync-worker `sync cycle done leads=N ...` — контакты
   и сделки подъехали из `knewit_leads`. Проверить канбан глазами.
6. Воркеры: в логах `outbox cycle done`, `notify cycle done`, realtime
   `realtime poller started from message_id=...`.
7. Прогнать `scripts/smoke.sh` против нового домена (п. 7).
8. Настроить бэкапы (п. 6) и проверить восстановление на scratch-БД.
9. Подключить n8n по `docs/n8n/README.md` (send-воркфлоу + гейт `bot_paused`).

## 6. Бэкапы

Полная инструкция — `docs/BACKUP.md` (`scripts/backup.sh`: nightly
`pg_dump -Fc` + ротация 7 daily / 4 weekly + restore-процедура).
На Railway два варианта:

- **Cron-сервис в том же проекте:** отдельный сервис из этого же
  репозитория с командой `scripts/backup.sh` и примонтированным Volume
  (`BACKUP_DIR` на volume), расписание — Railway Cron. Оффсайт-копии —
  rclone на S3 (см. BACKUP.md, шифровать: дампы содержат PII).
- **Внешний хост** с cron и `DATABASE_URL` через публичный прокси-адрес
  Postgres (`PGSSL=1` обязателен наружу).

Staging бэкапить не нужно (восстанавливается из фикстур за минуту).

## 7. Smoke-проверка

```bash
BASE_URL="https://crm-staging.up.railway.app" \
SMOKE_EMAIL="admin@example.com" SMOKE_PASSWORD="..." \
scripts/smoke.sh
# Полный путь с отправкой (доставит реальное сообщение в ТЕСТОВЫЙ чат):
SEND_TEST_MESSAGE=1 TEST_WHATSAPP_ID="79990000001@c.us" scripts/smoke.sh
```

Проверяет: `/api/health` (200 + DB up), логин (сессия + CSRF), список
сделок, SSE-пролог `connected` за 10 секунд и — по флагу — постановку
сообщения в outbox (202). Любой шаг при ошибке роняет скрипт с `FAIL`
и кодом 1 — годится как post-deploy gate в CI/CD и для ручной проверки.

## 8. Откат

- **Код:** Railway → Deployments → предыдущий успешный деплой → Redeploy.
  Контейнер при старте сам догонит миграции (`upgrade head` идемпотентен).
- **Миграции — только обратно-совместимые** (правило expand → migrate →
  contract): новая колонка — `NULL`-able или с default; переименование —
  в два релиза (добавить новую + писать в обе → перевести чтение →
  удалить старую); удаление колонки — минимум через релиз после того,
  как код перестал её читать. Нарушение правила ломает откат: старый код
  под новой схемой падает.
- **Откат схемы** (когда контракт-миграция всё же вышла): одноразово
  `railway run --service crm-production alembic -c backend/alembic.ini downgrade -1`
  — только после остановки сервиса (scale 0), только на один шаг, только
  если downgrade-миграция существует и протестирована локально.
- **Данные:** восстановление из `pg_dump` по `docs/BACKUP.md`
  (stop writes → drop/create → `pg_restore --single-transaction` →
  проверка `crm_alembic_version` + счётчиков → scale up).

## 9. CI/CD (GitHub Actions)

`.github/workflows/ci.yml`: lint + backend-тесты + frontend-гейты + e2e
(на каждый push/PR) плюс:

- `docker-build` — сборка образа без пуша (ловит сломанный Dockerfile
  до Railway).
- `deploy-staging` — автодеплой из ветки `develop` (`environment: staging`).
- `deploy-production` — по тегу `v*` **или** ручным запуском
  (`workflow_dispatch`), `environment: production` — аппрув релиза
  настраивается в GitHub (Settings → Environments → Required reviewers).

Секреты/переменные репозитория (Settings → Secrets and variables → Actions):

| Имя | Тип | Назначение |
|---|---|---|
| `RAILWAY_TOKEN` | Secret | Токен аккаунта Railway (Account Settings → Tokens) |
| `RAILWAY_PROJECT_ID` | Variable | ID проекта Railway |
| `RAILWAY_SERVICE_STAGING` | Variable | Имя staging-сервиса |
| `RAILWAY_SERVICE_PRODUCTION` | Variable | Имя production-сервиса |

Релиз production: `git tag v1.2.0 && git push origin v1.2.0` → CI собирает,
деплоит, затем прогнать `smoke.sh` против прод-домена вручную. Откат —
п. 8. Ветку `develop` создать из `main` один раз:
`git checkout -b develop && git push -u origin develop`.
