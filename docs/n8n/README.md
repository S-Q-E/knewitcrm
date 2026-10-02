# n8n: CRM Send Message + пауза бота (Шаг 9D, часть B)

Операторская инструкция. Код CRM пишет в `knewit_*` только через
`backend/app/services/bot_bridge.py`; всё ниже — чтение или настройка
самого n8n, схему бота не меняет.

## 1. Воркфлоу «CRM Send Message»

Файл: `docs/n8n/crm-send-message.workflow.json`.

### Что делает

```
Webhook POST /webhook/crm-send-message
  {outbox_id, whatsapp_id, text} + header X-CRM-Secret
    → 401 {ok:false} при несовпадении секрета
    → дедупликация по outbox_id (повтор = 200 без второй отправки)
    → отправка через того же WhatsApp-провайдера, что в основном воркфлоу
    → 200 {ok:true, provider_message_id} или {ok:false, error}
```

Контракт со стороны CRM (`workers/outbox_worker.py::post_to_n8n`):

- `POST $N8N_SEND_WEBHOOK_URL`
- заголовок `X-CRM-Secret: $N8N_WEBHOOK_SECRET`
- тело `{"outbox_id": "<uuid>", "whatsapp_id": "<...@c.us>", "text": "..."}`
- успех: HTTP 200 + JSON `{"ok": true, "provider_message_id": "..."}`.
  Поле `provider_message_id` опционально, но желательно (попадает в журнал outbox).
- отказ: HTTP ≥ 400 **или** `{"ok": false, "error": "..."}` **или** не-JSON.
  CRM при этом помечает строку `failed` и ждёт ручного повтора
  (авторетраи только при `ConnectError`, когда запрос точно не дошёл).

### Импорт

1. n8n → Workflows → `⋯` → Import from file → выбрать
   `crm-send-message.workflow.json`.
2. Открыть ноду `Send via WhatsApp (REPLACE)` и заменить её тем же
   способом отправки, что в основном воркфлоу бота: те же credentials,
   тот же API. Сохранить маппинг входов:
   - получатель ← `{{ $json.whatsapp_id }}`
   - текст ← `{{ $json.text }}`
   - референс/клиентский ID ← `{{ $json.outbox_id }}` (нужен для сверки).
3. В окружении n8n задать `N8N_WEBHOOK_SECRET` — тот же, что
   `N8N_WEBHOOK_SECRET` у CRM. В ноде `Check Secret` сравнение идёт
   с `{{ $env.N8N_WEBHOOK_SECRET }}`; ничего секретного в самом
   воркфлоу не хранится.
4. Activate → Production URL вида
   `https://<n8n-host>/webhook/crm-send-message` → прописать в CRM
   как `N8N_SEND_WEBHOOK_URL`.
5. Проверить:
   ```bash
   curl -s -X POST "$N8N_SEND_WEBHOOK_URL" \
     -H 'Content-Type: application/json' \
     -H "X-CRM-Secret: $N8N_WEBHOOK_SECRET" \
     -d '{"outbox_id":"00000000-0000-0000-0000-000000000001","whatsapp_id":"79990000001@c.us","text":"ping"}'
   # → {"ok": true, ...}
   curl -s -X POST "$N8N_SEND_WEBHOOK_URL" \
     -H 'Content-Type: application/json' -H 'X-CRM-Secret: wrong' \
     -d '{"outbox_id":"x","whatsapp_id":"y","text":"z"}' -w ' %{http_code}\n'
   # → {"ok": false, ...} 401
   # повтор первого вызова с тем же outbox_id → 200 без второй отправки
   ```

### Проверка секрета

Нода `Check Secret` пропускает дальше только при двух условиях сразу
(комбинатор AND):

1. заголовок `X-CRM-Secret` **не пуст** (`notEmpty`) — пустой секрет
   отклоняется, даже если `$env.N8N_WEBHOOK_SECRET` тоже пуст (защита
   от незаполненного env с обеих сторон);
2. заголовок **строго равен** `$env.N8N_WEBHOOK_SECRET`
   (case-sensitive сравнение; регистрозависимость отключена быть
   не должна — секрет сравнивается побайтово).

Иначе → `Respond 401` (`{ok:false}`, HTTP 401).

### Дедупликация (основной вариант — Postgres)

Повторный вызов с тем же `outbox_id` не отправляет сообщение второй раз.
Основной механизм — таблица n8n (схему бота не трогаем) + две Postgres-ноды:

```sql
CREATE TABLE IF NOT EXISTS n8n_processed_outbox (
  outbox_id uuid PRIMARY KEY,
  provider_message_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

- `Check Duplicate` (Postgres, `executeQuery`):
  ```sql
  SELECT COUNT(*) AS seen, MAX(provider_message_id) AS provider_message_id
  FROM n8n_processed_outbox WHERE outbox_id = '{{ $json.outbox_id }}'::uuid
  ```
  Агрегат `COUNT` всегда возвращает ровно одну строку, поэтому нода
  `Is Duplicate` срабатывает всегда (пустой SELECT без строк остановил
  бы ветку — классическая ловушка n8n). Каст `::uuid`: CRM всегда
  присылает uuid; мусор вместо uuid роняет запрос в ошибку, а не в
  отправку.
- `Is Duplicate` (IF): `{{ $json.seen }}` > 0 → `Respond Duplicate`
  (`{ok:true, deduped:true, ...}`), иначе → отправка.
- `Mark Sent` (Postgres, `executeQuery`) после успешной отправки:
  ```sql
  INSERT INTO n8n_processed_outbox (outbox_id, provider_message_id) VALUES
    ('{{ $('Check Duplicate').first().json.outbox_id }}'::uuid,
     '{{ $json.provider_message_id }}')
  ON CONFLICT (outbox_id) DO NOTHING
  ```
  `ON CONFLICT DO NOTHING` делает запись идемпотентной при гонках.
  Имя поля с ID провайдера (`provider_message_id`) зависит от вашего
  провайдера — поправьте выражение под ответ вашей ноды отправки.

Порядок в воркфлоу: Webhook → Check Secret → Check Duplicate (Postgres)
→ Is Duplicate → (да) Respond Duplicate / (нет) Send → Mark Sent
(Postgres) → Respond OK. Работает на любом числе инстансов n8n за
балансировщиком — состояние в Postgres, а не в памяти.

### Дедупликация (запасной вариант — static data)

Если у n8n нет доступа к Postgres, замените пару Postgres-нод Code-нодами
на `$getWorkflowStaticData('global')` (пара `outbox_id → provider_message_id`
в памяти одного инстанса). Достаточно для одиночного n8n, но теряется
при рестарте и не делится между инстансами:

```js
// Check Duplicate (Run Once for All Items)
const staticData = $getWorkflowStaticData('global');
if (!staticData.sentOutbox) staticData.sentOutbox = {};
const outboxId = String($json.body?.outbox_id || '');
if (staticData.sentOutbox[outboxId]) {
  return [{ json: { duplicate: true, outbox_id: outboxId,
    provider_message_id: staticData.sentOutbox[outboxId] } }];
}
return [{ json: { duplicate: false, outbox_id: outboxId,
  whatsapp_id: String($json.body?.whatsapp_id || ''),
  text: String($json.body?.text || '') } }];

// Mark Sent (Run Once for Each Item)
const staticData = $getWorkflowStaticData('global');
const outboxId = $('Check Duplicate').first().json.outbox_id;
const providerId = String($json.provider_message_id || '');
staticData.sentOutbox[outboxId] = providerId;
return [{ json: { outbox_id: outboxId, provider_message_id: providerId } }];
```

## 2. Правка основного воркфлоу бота: пауза (`bot_paused`)

CRM выставляет `crm_conversation_state.bot_paused` (кнопки «Пауза»/«Вернуть
боту», автопауза при ручном ответе). Бот должен сам останавливаться.

### Куда вставить

Сразу после приёма входящего сообщения и записи в `knewit_messages`,
**до** вызова AI-агента:

```
... Webhook/Trigger входящего → запись в knewit_messages →
→ Postgres «Is Bot Paused?» → IF «paused?» ──true──→ Stop (NoOp, конец)
                                   └─false─→ AI Agent → ...
```

### Нода Postgres «Is Bot Paused?»

- Credentials: те же, что основной бот использует для записи в Postgres.
- Query (параметризованный, один параметр):
  ```sql
  SELECT bot_paused FROM crm_conversation_state WHERE whatsapp_id = $1
  ```
- Query Parameters: `{{ $json.whatsapp_id }}` (то поле, где у вас лежит
  ID чата входящего сообщения; подставьте свой путь, например
  `{{ $('Webhook').item.json.body.whatsapp_id }}`).
- Важно: **только SELECT**. Никаких UPDATE/INSERT/TRIGGER на `knewit_*`.
  Отсутствующая строка = бот НЕ на паузе (`false`).

### Нода IF «paused?»

- Условие: результат Postgres `true`. Нет строк → `false`:
  ```
  {{ $json.bot_paused === true }}
  ```
  (в IF-ноде: boolean is true; пустой результат трактовать как false).
- Ветка `true` → нода `Stop` (NoOp/Stop And Error с `message: paused`,
  без ошибки) — AI-агент **не вызывается**, ответ не отправляется.
- Ветка `false` → существующая цепочка AI-агента без изменений.

### Cron-воркфлоу follow-up / напоминаний

Тот же гейт перед каждой отправкой по каждому `whatsapp_id`:

```
Cron → выборка due-followups → Loop по чатам →
→ Postgres «Is Bot Paused?» (тот же SELECT) → IF paused?
  ──true──→ пропустить чат (NoOp, следующий элемент loop)
  └─false─→ существующая отправка напоминания
```

### Пошаговая проверка на тестовом чате

1. В CRM открыть диалог тестового номера, нажать «Пауза» (или отправить
   ручное сообщение при включённой `auto_pause_on_manual_reply`).
   Проверить в БД: `SELECT bot_paused FROM crm_conversation_state
   WHERE whatsapp_id = '<тест>'` → `t`.
2. С тестового номера отправить любое сообщение в WhatsApp.
3. В Executions основного воркфлоу найти запуск: ветка должна уйти в
   `Stop`, executions AI-агента быть не должно, ответ клиенту не приходит.
4. В CRM нажать «Вернуть боту», убедиться `bot_paused = f`.
5. Повторить сообщение → ветка `false`, AI-агент вызван, ответ пришёл.
6. Cron: выставить тестовый follow-up `run_at = now()`, при `bot_paused = t`
   убедиться, что отправки не было (execution ушёл в пропуск), при `f` —
   отправка прошла.
7. Вернуть тестовый чат в исходное состояние (resume, удалить тестовые
   строки при необходимости).

## 3. Связка с CRM

- CRM env: `N8N_SEND_WEBHOOK_URL` (production URL из п.1),
  `N8N_WEBHOOK_SECRET` (тот же, что `$env.N8N_WEBHOOK_SECRET` в n8n).
- CRM никогда не хранит ключи WhatsApp-провайдера — только этот URL+секрет.
- Журнал доставки: CRM → Настройки → Интеграции (счётчики outbox,
  последняя ошибка — только класс + короткое сообщение, без PII).
