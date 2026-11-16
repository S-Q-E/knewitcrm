# RECON — TCS Property Management demo

Фаза 0. Код не менялся. Репозиторий: `/home/quanysh/tcs_automation/tcs_demo`,
ветка `tcs-demo` (от `main`, коммит `c7326ad`). Оригинал `knewitcrm/` не тронут.

## 0. Базовая линия

Postgres: `docker compose up -d`, контейнер `tcs_demo-db-1`
(`postgres:16-alpine`, порт 5432, БД `knewit` / `knewit`).

| Проверка | Результат |
| --- | --- |
| `ruff check backend scripts` | OK |
| `ruff format --check backend scripts` | OK, 169 files |
| `pytest -q` | **1 failed, 257 passed** (13:08) |
| `npm run typecheck` | OK |
| `npm run lint` | OK |
| `npm test` | OK, 16 files / 52 tests |
| `npm run build` | OK (warning: chunk > 500 kB) |

Падает `backend/tests/test_contacts_data.py::test_duplicates_and_merge`:
`StopIteration` при поиске phone-группы дублей. Отдельно тест проходит,
весь файл `test_contacts_data.py` проходит (9 passed). Причина —
предсуществующая флакистость: `_wa()` в тесте делает
`7999` + 8 случайных hex-символов; если все 8 — цифры, whatsapp даёт 12 цифр,
а телефон — 11, и `contact_keys()` выбирает более длинный whatsapp-ключ,
поэтому телефонная пара не группируется. Вероятность ≈ `(10/16)^8 ≈ 2%`.
К TCS-демо отношения не имеет. Предложенный минимальный фикс: укоротить
`_wa()` до 10 цифр (`f"79{uuid.uuid4().hex[:8]}@c.us"`) либо задавать телефон
детерминированно. По указанию пользователя считаем это известной базовой
линией и продолжаем.

---

## 1. Как CRM строит контакт и телефон из `whatsapp_id`

### 1.1 Синхронизация бота

`backend/app/workers/sync_worker.py`:

- `_LEAD_SELECT` читает из `knewit_leads`:
  `whatsapp_id, name, current_stage, previous_stage, status, direction, goal,
  experience_level, preferred_format, preferred_time, trial_datetime,
  last_objection`.
  Поля `phone`, `lead_data`, `source`, `client_name` не читаются.
- Контакт создаётся в `_sync_batch` (около строк 375–386):

  ```python
  CrmContact(
      whatsapp_id=whatsapp_id,
      name=lead.get("name"),
      source=CONTACT_SOURCE_BOT,   # "bot"
      custom={name: lead.get(name) for name in CUSTOM_FIELDS},
      last_bot_name=lead.get("name"),
  )
  ```

  `phone` и `email` не заполняются. То есть у лида из Telegram
  `crm_contacts.phone` остаётся `NULL`, а единственный идентификатор —
  `whatsapp_id = "tg:<chat_id>"`.
- Сделка создаётся там же (около строк 445–455): `title = name or whatsapp_id`,
  `trial_at = lead.trial_datetime`, `custom = {6 полей бота}`,
  `status/stage` — через `_resolve_target`.
- `_sync_contact_name` обновляет имя только если менеджер его не менял
  (сравнение с `last_bot_name`).
- `_sync_deal_trial` обновляет `deal.trial_at` только при реальном изменении
  значения бота; `NULL` от бота не затирает ручное значение.
- `_load_funnel` берёт воронку с `is_default = true` (иначе первую по `sort`),
  этапы сопоставляет по `bot_stage_key` / `bot_status_key`.
  `_resolve_target`: `status = "КЛИЕНТ"` → `won`, `status = "ОТКАЗ"` → `lost`,
  иначе этап по `current_stage`; неизвестный этап → первый `open`.
- `deal.trial_at` — это и есть `knewit_leads.trial_datetime`; в UI называется
  «Пробный урок» (Phase 1 → «Viewing»).

### 1.2 `normalize.py` и дубли

`backend/app/services/normalize.py`:

```python
normalize_phone("+7 (701) 000-11-22") == "77010001122"
normalize_phone("8 701 000 11 22")   == "77010001122"
normalize_whatsapp("79991234567@c.us") == "79991234567"
normalize_whatsapp("tg:123456789")     == "123456789"   # сейчас
```

`contact_keys(phone, whatsapp_id, email)`:

- считает `from_phone = normalize_phone(phone)`;
- считает `from_wa = normalize_whatsapp(whatsapp_id)`;
- берёт **самый длинный** кандидат длиной ≥ 7 как phone-ключ;
- email — `strip().lower()`.

Используется только в `backend/app/services/duplicates.py::find_duplicate_groups`.
То есть `tg:123456789` сейчас участвует в поиске дублей как «телефон»
`123456789`. После Phase 1.4 (`normalize_whatsapp` возвращает `""` для `tg:`)
phone-ключ будет строиться только из `crm_contacts.phone`.

Поиск контактов — отдельная функция `backend/app/routers/contacts.py:43`
(`re.sub(r"\D", "", ...)`), применяется только к колонке `phone`; по
`whatsapp_id` идёт обычный `ILIKE`. Экспорт в `routers/data_exchange.py`
импортирует эту же `normalize_phone`. Поиск диалогов использует `ILIKE` по
`crm_conversation_state.whatsapp_id`, без нормализации.

### 1.3 Где `tg:...` сейчас показывается как телефон/идентификатор

| Место | Что видно |
| --- | --- |
| `frontend/src/lib/format.ts::formatPhone` | fallback на цифры `whatsapp_id`: `tg:123456789` → `+123456789`; для 11 цифр с `7` — формат `+7 ...` |
| `frontend/src/components/deals/card.tsx` | телефон на карточке сделки через `formatPhone(contactPhone, contactWhatsappId)` |
| `frontend/src/components/deals/detail.tsx` | блок «Данные от бота»: `WhatsApp: tg:123456789` |
| `frontend/src/pages/contact.tsx` | строка контакта: `phone · email · whatsapp_id · source`, где `whatsapp_id` — сырой `tg:...` |
| `frontend/src/pages/contacts.tsx` | колонка «WhatsApp» показывает сырой `c.whatsapp_id` |
| `frontend/src/pages/dialogs.tsx` | при отсутствии `contact_phone` показывает сырой `whatsapp_id` |
| `backend/app/services/duplicates.py` | phone-группа дублей по цифрам `tg:` (см. 1.2) |
| CSV/XLSX export | `whatsapp_id` выгружается как есть |

Для Phase 1.4 минимально нужно:

1. В `normalize_whatsapp`: `if local.startswith("tg:"): return ""` (до
   `normalize_phone`) + тест.
2. В `formatPhone` не использовать `whatsappId`, начинающийся с `tg:`, как
   телефон (вернуть `null`, если нет `phone`). Иначе карточка сделки продолжит
   показывать `+123456789`.
3. Проверить, что после этого `tg:` не попадает в phone-группы дублей.
4. Решить, что показывать вместо телефона: сырой `tg:...`, «Chat», или ничего.
   В target явно не задано; минимальный вариант — не показывать как телефон.

Дополнительно: `formatPhone` форматирует только 11-значные номера с `7`.
Американские `+1 215 555 01xx` (10 цифр) будут показаны как `+12155550100`.
Для демо это косметика, но при переводе на USD/США стоит поправить.

---

## 2. Какие поля `knewit_leads` видны в карточке контакта и сделки

`CUSTOM_FIELDS` в `sync_worker.py`:

```python
("direction", "goal", "experience_level", "preferred_format",
 "preferred_time", "last_objection")
```

Эти шесть полей пишутся и в `crm_contacts.custom`, и в `crm_deals.custom`
(`_merge_bot_custom`; ручные ключи менеджера сохраняются).

| Поле `knewit_leads` | Куда попадает | Где видно |
| --- | --- | --- |
| `name` | `crm_contacts.name`, `crm_deals.title` | карточка контакта, карточка/список сделок, диалоги |
| `whatsapp_id` | `crm_contacts.whatsapp_id`, `crm_conversation_state.whatsapp_id` | контакт, диалоги, блок «Данные от бота», чат |
| `status` | `crm_deals.status` (`open/won/lost`) + этап | воронка/карточка сделки |
| `current_stage` / `previous_stage` | `crm_deals.stage_id`, история этапов | воронка, таймлайн |
| `direction` | `contact.custom`, `deal.custom` | «Данные от бота» в карточке сделки |
| `goal` | `contact.custom`, `deal.custom` | «Данные от бота» |
| `experience_level` | `contact.custom`, `deal.custom` | «Данные от бота» |
| `preferred_format` | `contact.custom`, `deal.custom` | «Данные от бота» |
| `preferred_time` | `contact.custom`, `deal.custom` | «Данные от бота» |
| `last_objection` | `contact.custom`, `deal.custom` | «Данные от бота» + топ возражений в аналитике |
| `trial_datetime` | `crm_deals.trial_at` (+ `last_bot_trial_at`) | карточка сделки («Пробный урок»), карточка на доске |
| `phone` | **не переносится** | нигде в CRM |
| `lead_data` (`budget_usd`, `unit`, `pets`) | **не переносится** | нигде в CRM |

Важные следствия:

- Блок «Данные от бота» в `frontend/src/components/deals/detail.tsx`
  (`BOT_FIELDS`) читает `contact.custom`, а не `deal.custom`.
  `BOT_FIELDS`: `direction`, `goal`, `experience_level`, `preferred_format`,
  `preferred_time`, `last_objection`.
- Карточка контакта (`pages/contact.tsx`) показывает `name`, `phone`, `email`,
  `source`, `whatsapp_id` и **только те custom-поля, для которых есть
  определения в `crm_custom_fields`**. Шесть полей бота на странице контакта
  по умолчанию не видны (определений для них нет), но видны в сделке.
- `lead_data` в Phase 2 можно заполнить в `knewit_leads`, но CRM его не
  отобразит без изменения `sync_worker`/UI, чего target не требует.
- `phone` в Phase 2 можно заполнить в `knewit_leads` (555-01xx), но
  `crm_contacts.phone` останется `NULL`; в CRM телефона не будет. Это
  ограничение текущего синка, а не seed-скрипта.

---

## 3. `crm_settings`

Модель `backend/app/models/common.py:94`:

```python
class CrmSetting(Base):
    __tablename__ = "crm_settings"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONB, nullable=False
    )
```

В миграции `0003_domain.py` — ровно две колонки: `key text primary key`,
`value jsonb not null`. Отдельных `created_at/updated_at` нет.

Фактические ключи после миграций (проверено `SELECT key, value FROM crm_settings`):

| Ключ | Значение | Смысл |
| --- | --- | --- |
| `analytics_managers_visible` | `true` | показывать менеджерам аналитику |
| `auto_pause_on_manager` | `false` | ставить бота на паузу при передаче менеджеру |
| `auto_pause_on_manual_reply` | `true` | пауза после ручного ответа менеджера |
| `deal_assignment` | `{"mode": "unassigned", "last_index": -1}` | режим назначения сделок |
| `paused_alert_hours` | `6` | порог уведомления о долгой паузе бота |
| `realtime_poller.cursors` | `{"event_id": ..., "message_id": ...}` | курсоры realtime-воркера |
| `sync_worker.last_full_synced_at` | ISO-строка | маркер полного синка |
| `sync_worker.last_synced_at` | ISO-строка | маркер инкрементального синка |
| `unanswered_after_minutes` | `10` | порог «Unanswered» в минутах |

Дефолты в коде: `unanswered_after_minutes = 10` (`services/unanswered.py`),
`paused_alert_hours = 6` (`services/paused.py`), остальные — в
`routers/settings.py` и `schemas/settings.py`.

Для Phase 2 шаг D: писать `unanswered_after_minutes` как **JSON-число** `2`,
например `INSERT ... VALUES ('unanswered_after_minutes', '2'::jsonb)` или
параметром с `CAST(:value AS jsonb)`. `threshold_minutes()` принимает только
`int` (не `bool`) в диапазоне 1..1440; строка `"2"` не подойдёт.

---

## 4. Как создаются пользователи и менеджеры

- Первый администратор — из env при старте:
  `backend/app/services/bootstrap.py::ensure_bootstrap_admin`.
  Условия: заданы `ADMIN_EMAIL` и `ADMIN_PASSWORD`, пароль ≥ 10 символов,
  в БД ещё нет ни одного администратора. Имя — `Administrator`.
- Роли: `admin` и `manager` (`schemas/users.py`, `models/auth.py`).
  По умолчанию при создании — `manager`.
- Дальше администратор создаёт пользователей:
  `POST /api/users` (`routers/users.py`), поля `email`, `name`, `password`,
  `role`. Пароль ≥ 10 символов. Email нормализуется в lower-case.
- В UI: `Settings → Пользователи` (`frontend/src/pages/settings_system.tsx`),
  модалка «Новый пользователь», роль «Администратор/Менеджер»; API-хуки —
  `frontend/src/api/settings.ts` (`useAdminUsers`, `useCreateUser`,
  `useUpdateUser`).
- `PATCH /api/users/{id}` меняет имя, роль, активность, сбрасывает пароль.
  Нельзя разжаловать/деактивировать последнего активного администратора.
- Менеджеры для назначения/round-robin берутся из активных пользователей
  (`users.is_active = true`); `GET /api/users` для менеджера отдаёт только
  `id + name`.
- `crm_conversation_state.assigned_to` и `crm_deals.owner_id` ссылаются на
  `crm_users.id`; для демо нужно создать двух менеджеров (HUMAN_TODO).

---

## 5. Видимые пользователю русские строки на бэкенде

Полный grep `backend/app/**/*.py` по кириллице даёт 7 файлов. Разбор:

| Файл:строка | Строка | Видимость / действие |
| --- | --- | --- |
| `services/analytics.py:435` | `"Без причины"` | fallback `lost_by_reason` в API → перевести |
| `services/timeline.py:522` | `"Клиент"` | `author_name` входящего сообщения → перевести |
| `services/timeline.py:524` | `"Бот"` | `author_name` сообщения бота → перевести |
| `services/timeline.py:526` | `"Менеджер"` | `author_name` ответа менеджера → перевести |
| `routers/data_exchange.py:301` | `"внутренняя ошибка импорта"` | текст ошибки импорта → перевести |
| `routers/data_exchange.py:382` | `"импорт прерван перезапуском сервера"` | текст ошибки импорта → перевести |
| `models/pipelines.py:25-27` | `"КЛИЕНТ"`, `"ОТКАЗ"`, `"МЕНЕДЖЕР"` | **константы статусов, не трогать** |
| `services/funnel_seed.py` | названия этапов/причин | legacy-воронка, по target не переводить |
| `services/assignment.py` | только docstrings | не видно пользователю |
| `workers/sync_worker.py` | только комментарии/docstrings | не видно пользователю |

`services/notifications.py` и `services/login_limits.py` кириллицы не содержат
(в target упомянуты «и др.», но фактически там нет пользовательских строк).

Отдельно: в БД после миграций лежит legacy-воронка «Продажи Knewit» с русскими
названиями этапов. Она видна в UI, пока TCS-воронка не станет default. Phase 2
создаёт «TCS Leasing» и снимает `is_default` у остальных; сама legacy-воронка
остаётся в БД (её не удаляем).

---

## 6. Как сгенерирован `frontend/src/api/types.ts`

Файл auto-generated, шапка:

```
This file was auto-generated by openapi-typescript.
Do not make direct changes to the file.
```

Генерация — `frontend/package.json`:

```json
"gen:api": "PY=../.venv/bin/python; [ -x \"$PY\" ] || PY=python3; \"$PY\" ../scripts/export_openapi.py openapi.json && openapi-typescript openapi.json -o src/api/types.ts"
```

- `scripts/export_openapi.py` поднимает `create_app().openapi()` без БД
  (dummy env) и пишет `frontend/openapi.json`.
- `openapi-typescript` 7.13.0 превращает его в `src/api/types.ts`.
- `frontend/eslint.config.js` игнорирует `openapi.json` и `src/api/types.ts`.
- Часть API-модулей написана руками: например, `frontend/src/api/analytics.ts`
  содержит собственные интерфейсы (`BotStats`, `AnalyticsOverview`), а не
  только `components["schemas"]`. При добавлении `after_hours` в Phase 3 нужно
  обновить **и** `backend/app/schemas/analytics.py`, **и** `types.ts`
  (через `npm run gen:api`), **и** `frontend/src/api/analytics.ts`.

---

## 7. Тесты с русскими строками

### Backend (`backend/tests`, 21 файл)

| Файл | Кол-во строк | Что это |
| --- | ---: | --- |
| `test_9d_partb.py` | 6 | тела сообщений, CSV-данные, проверка README |
| `test_analytics.py` | 18 | legacy-этапы/статусы, причины, имена этапов в ответах |
| `test_automation_isolation.py` | 1 | `НОВЫЙ_ЛИД` |
| `test_board_new_on_top.py` | 3 | `НОВЫЙ_ЛИД`, докстринг |
| `test_bot_bridge.py` | 9 | `НОВЫЙ_ЛИД`, `ЗАПИСЬ` |
| `test_contacts_data.py` | 4 | «Иван» в CSV/поиске |
| `test_contacts.py` | 4 | «Айгерим» в имени/поиске |
| `test_deals.py` | 1 | `НОВЫЙ_ЛИД` |
| `test_deploy.py` | 1 | «Откат» (данные) |
| `test_dialogs_pagination.py` | 1 | `НОВЫЙ_ЛИД` |
| `test_dialogs.py` | 2 | `НОВЫЙ_ЛИД` |
| `test_hardening.py` | 2 | CSV «Импорт», `НОВЫЙ_ЛИД` |
| `test_notify.py` | 6 | `НОВЫЙ_ЛИД`, `МЕНЕДЖЕР`, `ЗАПИСЬ` |
| `test_outbox.py` | 23 | русские тексты сообщений, `НОВЫЙ_ЛИД` |
| `test_owner_sync.py` | 1 | `НОВЫЙ_ЛИД` |
| `test_realtime.py` | 2 | `НОВЫЙ_ЛИД`, `ЗАПИСЬ` |
| `test_settings.py` | 1 | `НОВЫЙ_ЛИД` в `bot-stages` |
| `test_sync.py` | 23 | legacy-этапы, «Клиент», «Отказ», «Запись», имена |
| `test_timeline.py` | 3 | `НОВЫЙ_ЛИД`, `author_name == "Бот"` |
| `test_views.py` | 1 | комментарий «чужое» |
| `test_visibility_matrix.py` | 5 | русские тела сообщений |

Важно: большинство backend-тестов используют кириллицу как **legacy-ключи
этапов/статусов** (`НОВЫЙ_ЛИД`, `ЗАПИСЬ`, `КЛИЕНТ`, `ОТКАЗ`, `МЕНЕДЖЕР`) или
как тестовые данные. Их нельзя убрать, не меняя константы/воронку. Проверки
видимых ярлыков, которые сломаются после перевода: `test_timeline.py`
(`author_name == "Бот"`), `test_sync.py` (`"Клиент"`, `"Отказ"`, `"Запись"`,
`"Новый лид"`), `test_analytics.py` (имена legacy-этапов и `"Без причины"` —
последнее только если тест его проверяет), `test_settings.py` (`bot-stages`
ключи — не ярлыки). Полный grep по `backend/tests` останется с кириллицей;
критерий Phase 1 разумно применять к `backend/app`, а не к тестовым фикстурам.

### Frontend (`frontend/src/**/*.test.ts(x)`, 8 файлов)

| Файл | Кол-во строк | Что проверяет |
| --- | ---: | --- |
| `api/stream.test.tsx` | 1 | текст уведомления «Новое сообщение в вашем диалоге» |
| `components/deals/board.test.tsx` | 3 | кнопка «Показать ещё» |
| `components/deals/timeline.test.tsx` | 10 | «менеджер», «бот», «входящее», русские имена/тексты |
| `components/dialogs/composer.test.tsx` | 13 | label «Сообщение клиенту», кнопка «Отправить», alert про бота |
| `components/realtime-status.test.tsx` | 3 | «Онлайн», «Резервный опрос», «Нет соединения» |
| `lib/format.test.ts` | 1 | `initials("Айгерим Тестова")` |
| `lib/quick_replies.test.ts` | 5 | русские шаблоны быстрых ответов |
| `pages/contacts.test.ts` | 1 | поиск «иван» |

После перевода нужно обновить как минимум: `stream.test`, `board.test`,
`timeline.test`, `composer.test`, `realtime-status.test`. Остальные содержат
русские **данные** (имена, шаблоны) — их можно заменить на английские
эквиваленты, чтобы пройти `grep -rnP "[А-Яа-яЁё]" frontend/src` и не менять
смысл теста. `quick_replies` — пользовательские шаблоны; в демо их можно
оставить русскими, но критерий требует пустой grep, поэтому заменить.

---

## 8. Инвентарь кириллицы во фронтенде (не тесты)

`grep -rcP "[А-Яа-яЁё]" frontend/src` даёт 42 файла. По группам:

**Страницы (11):**
`analytics.tsx` 84, `contacts.tsx` 75, `tasks.tsx` 28, `settings_profile.tsx` 24,
`contact.tsx` 22, `dialogs.tsx` 18, `settings.tsx` 10, `deals.tsx` 6,
`login.tsx` 6, `stubs.tsx` 4, `deal.tsx` 1.

**Компоненты (15):**
`deals/timeline.tsx` 49, `deals/detail.tsx` 34, `deals/list.tsx` 27,
`deals/modals.tsx` 22, `deals/filters.tsx` 15, `layout.tsx` 14,
`bell.tsx` 13, `dialogs/chat-panel.tsx` 12, `deals/card.tsx` 10,
`dialogs/composer.tsx` 7, `realtime-status.tsx` 6, `deals/board.tsx` 4,
`deals/column.tsx` 4, `toast.tsx` 2, `realtime-status.test.tsx` 3 (тест).

**API/lib (9):**
`api/timeline.ts` 6, `api/settings.ts` (DEFAULT_PREFS / формат дат) 1,
`api/client.ts` 2, `api/stream.ts` 1, `api/analytics.ts` 1,
`app.tsx` 1, `lib/format.ts` (локаль/валюта) 1.

**Тесты (8):** см. раздел 7.

Плюс `frontend/index.html`: `<html lang="ru">`, `<title>KnewIT CRM</title>`.

Порядок перевода из target: `layout.tsx`, `login.tsx`, `app.tsx`, `deals.tsx`,
`deals/*`, `dialogs.tsx`, `dialogs/*`, `tasks.tsx`, `contacts.tsx`,
`contact.tsx`, `deal.tsx`, `bell.tsx`, `analytics.tsx`, `settings*.tsx`,
остальное. После каждого файла — typecheck + lint, тесты — по мере падений.

Особые места:

- `frontend/src/lib/format.ts`: `ru` из `date-fns/locale`, `Intl.NumberFormat
  ("ru-KZ")`, `Intl.DateTimeFormat("ru-KZ")`, default currency `"KZT"`.
  Phase 1: `en-US`/`USD`, USD как `$`, даты — английский формат.
- `frontend/src/api/settings.ts`: `DEFAULT_PREFS = { timezone:
  "Asia/Almaty", sound: true }`, `formatInTimezone(..., "ru-RU")`.
- `frontend/src/pages/settings_profile.tsx`: `TIMEZONES = ["Asia/Almaty",
  "Asia/Aqtobe", "Asia/Aqtau", "Europe/Moscow", "UTC"]`.
- `frontend/src/pages/analytics.tsx`: свой `formatMoney` с `currency === "KZT"
  ? "₸" : currency`; `Intl.NumberFormat("ru-RU")`; сортировка `localeCompare(...,
  "ru")`.
- `frontend/src/pages/tasks.tsx`: `toLocaleDateString("ru-RU", ...)`.
- `frontend/src/pages/contacts.tsx`: `autoMapping` принимает русские заголовки
  CSV (`имя`, `телефон`, `почта`, `источник`). Это не видимый текст, но
  критерий «grep пусто» требует убрать/заменить; саму логику импорта можно
  оставить, добавив английские алиасы.

---

## 9. Жёсткие KZT / Asia/Almaty

| Файл | Строка |
| --- | --- |
| `backend/app/config.py:19-20` | `default_timezone="Asia/Almaty"`, `default_currency="KZT"` |
| `.env.example:7-8` | `DEFAULT_TIMEZONE=Asia/Almaty`, `DEFAULT_CURRENCY=KZT` |
| `docker-compose.yml` | переменные не заданы (нужно добавить) |
| `backend/app/services/analytics.py:1005` | `"currency": "KZT"` в `meta` |
| `backend/app/schemas/deals.py:44` | `DealCreate.currency = "KZT"` |
| `backend/app/models/deals.py:31` | `DEFAULT_CURRENCY = "KZT"` (server_default) |
| `frontend/src/lib/format.ts:4` | `formatMoney(..., currency = "KZT")`, `ru-KZ` |
| `frontend/src/pages/analytics.tsx:67` | `currency === "KZT" ? "₸" : currency` |
| `frontend/src/pages/settings_profile.tsx:20` | список `TIMEZONES` с Азией/Москвой |
| `frontend/src/api/settings.ts:592` | `DEFAULT_PREFS.timezone = "Asia/Almaty"` |

Тесты, которые это фиксируют и потребуют правки:
`backend/tests/test_config.py:64-65`, `backend/tests/test_analytics.py:268`,
`frontend/src/lib/format.test.ts:6-9`, `frontend/src/api/settings.test.ts:27-28`,
`frontend/src/components/deals/board.test.tsx:25`.

---

## 10. Что это значит для следующих фаз (риски/решения)

1. **Телефон бота не доходит до CRM.** `sync_worker` не читает
   `knewit_leads.phone` и не пишет `crm_contacts.phone`. Seed Phase 2 может
   заполнить телефон в боте, но в CRM его не будет. Если для демо нужен телефон
   в карточке — это изменение `sync_worker` (не предусмотрено target) или
   отдельное решение. Пока в CRM останется `whatsapp_id = tg:...`.
2. **`lead_data` не доходит до CRM.** `budget_usd`, `unit`, `pets` будут только
   в `knewit_leads.lead_data`; UI их не покажет. Для демо это ок, если не
   обещать их на экране.
3. **`tg:` как телефон.** После Phase 1.4 нужно поправить не только
   `normalize_whatsapp`, но и `formatPhone` (карточка сделки) — иначе
   `+123456789` останется. Дуэт `contact_keys` перестанет считать `tg:` телефоном.
4. **Флаки `test_duplicates_and_merge`.** Это не блокер, но полный `pytest`
   может иногда падать. Для честной проверки фаз можно перезапускать только
   этот тест или зафиксировать `_wa()` отдельным коммитом (вне TCS-логики).
5. **`types.ts` — generated.** Не редактировать руками; после изменения
   backend-схем запускать `npm run gen:api` и обновлять ручные типы в
   `frontend/src/api/analytics.ts`.
6. **Legacy-воронка.** TCS-воронка станет default, но «Продажи Knewit»
   останется в БД. Если в демо открыть список воронок, русские названия могут
   быть видны. Target разрешает оставить `funnel_seed.py` как есть; при
   необходимости скрыть legacy-воронку — отдельное решение.
7. **`tcs_units` пока нет** (проверено `to_regclass('public.tcs_units')` → NULL).
   Phase 2 создаёт её seed-скриптом, не Alembic.
8. **Цвета для TCS-воронки** можно взять из `funnel_seed.py`:
   `#38BDF8`, `#818CF8`, `#A78BFA`, `#C084FC`, `#E879F9`, `#F472B6`,
   `#FB7185`, `#FBBF24`, `#16A34A` (won), `#EF4444` (lost).
9. **`unanswered_after_minutes`** — JSON-число `2`, не строка.
10. **DEMO-плашка** должна быть в `layout.tsx` на всех страницах; title в
    `frontend/index.html` — «TCS Leasing CRM»; `lang="en"`.

---

## 11. Проверки, которые запускались

```bash
docker compose up -d
.venv/bin/ruff check backend scripts
.venv/bin/ruff format --check backend scripts
.venv/bin/python -m pytest -q
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

Результаты — в разделе 0. Код не изменялся; `RECON.md` — единственный
добавленный файл.
