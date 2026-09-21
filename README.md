# KnewIT CRM — дашборд для WhatsApp-бота

Веб-CRM для мониторинга диалогов AI-агента с клиентами. Читает данные
напрямую из той же Postgres, что использует ваш n8n workflow
(`knewit_leads`, `knewit_messages`, `knewit_events`, `knewit_followups`).

## Что внутри

**Backend:** FastAPI + asyncpg  
**Frontend:** ванильный JS + CSS (без сборки)  
**БД:** Postgres (тот же инстанс, что и в n8n)  
**Деплой:** один Docker-контейнер, готов под Railway

## Возможности

- 📊 Сводные метрики по лидам (всего / активные / записаны / клиенты)
- 🔍 Поиск по имени или номеру + фильтры по статусу
- 💬 Полная переписка бота с клиентом (входящие/исходящие, этап, время ответа)
- 📈 Timeline событий воронки (переходы, возражения, запись, продажа)
- 🗂 Карточка лида со всеми собранными данными (`direction`, `goal`, `format`, …)
- 🔄 Автообновление каждые 10 секунд

## Переменные окружения

Railway подставит `DATABASE_URL` автоматически, если прилинковать Postgres-плагин
к этому сервису. Если Postgres внешний — задайте один из вариантов:

| Переменная     | Описание                                          |
|----------------|---------------------------------------------------|
| `DATABASE_URL` | Полный DSN (`postgresql://user:pass@host:port/db`) |
| `PGHOST`       | Хост                                              |
| `PGPORT`       | Порт (по умолчанию 5432)                          |
| `PGUSER`       | Пользователь                                      |
| `PGPASSWORD`   | Пароль                                            |
| `PGDATABASE`   | Имя БД (по умолчанию `railway`)                   |
| `PGSSL`        | `true`/`false` — форсировать SSL (auto по умолчанию) |
| `PORT`         | Задаётся Railway автоматически                    |

## Деплой на Railway (2 минуты)

### Способ 1 — из GitHub

1. Запушьте папку проекта в репозиторий GitHub.
2. Railway → **New Project** → **Deploy from GitHub repo** → выберите репо.
3. Railway сам соберёт Docker-образ (`railway.json` + `Dockerfile`).
4. **+ New** → **Database** → **Add PostgreSQL** (если ещё нет — можно
   подключить уже существующий от n8n).
5. Откройте сервис CRM → **Variables** → **+ New Variable** →
   **Add Reference** → выберите `DATABASE_URL` из Postgres-плагина.
6. **Settings → Networking → Generate Domain** — получите публичную ссылку.

### Способ 2 — из локальной папки

```bash
npm i -g @railway/cli
railway login
railway init
railway up
```

## Локальный запуск (для отладки)

```bash
export DATABASE_URL="postgresql://user:pass@localhost:5432/knewit"
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

Откройте http://localhost:8000

## Структура БД

CRM **только читает**, никаких миграций не выполняет — предполагается, что
схема уже создана вашим n8n воркфлоу (нода `SETUP: применить SQL-схему`).

Используются таблицы:

- `knewit_leads`     — состояние лида
- `knewit_messages`  — все сообщения (in/out)
- `knewit_events`    — события воронки
- `knewit_followups` — очередь напоминаний (только для справки)

## API (для интеграций)

| Method | Endpoint                                  |
|--------|-------------------------------------------|
| GET    | `/api/health`                             |
| GET    | `/api/stats`                              |
| GET    | `/api/leads?search=&status=&stage=&limit=`|
| GET    | `/api/leads/{whatsapp_id}`                |
| GET    | `/api/leads/{whatsapp_id}/messages`       |
| GET    | `/api/leads/{whatsapp_id}/events`         |
| GET    | `/api/funnel`                             |

Все эндпоинты возвращают JSON, доступны без авторизации. Если нужно закрыть —
добавьте Basic Auth middleware в `backend/main.py` или спрячьте сервис за
Railway Private Network.