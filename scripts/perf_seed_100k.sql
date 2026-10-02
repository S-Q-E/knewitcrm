-- Step 14 perf harness: synthetic load for EXPLAIN/latency analysis.
-- All rows carry the perf14_ prefix and MUST be removed after the analysis:
--   DELETE FROM crm_conversation_state WHERE whatsapp_id LIKE 'perf14\_%';
--   DELETE FROM knewit_messages WHERE whatsapp_id LIKE 'perf14\_%';
--   DELETE FROM knewit_events WHERE whatsapp_id LIKE 'perf14\_%';
--   DELETE FROM knewit_leads WHERE whatsapp_id LIKE 'perf14\_%';
-- Prefix perf14_ never collides with real or fixture rows (fixtures use 7701/7999).
BEGIN;

INSERT INTO knewit_leads (whatsapp_id, name, current_stage, status, last_objection, created_at, updated_at, last_message_at)
SELECT 'perf14_' || g || '@c.us',
       'Perf ' || g,
       (ARRAY['НОВЫЙ_ЛИД','КВАЛИФИКАЦИЯ','ЗАПИСЬ','ПРОДАЖА'])[1 + (g % 4)],
       (ARRAY['ACTIVE','ЗАПИСАН','МЕНЕДЖЕР','КЛИЕНТ','ОТКАЗ'])[1 + (g % 5)],
       CASE WHEN g % 7 = 0 THEN 'дорого' WHEN g % 11 = 0 THEN 'нет времени' ELSE NULL END,
       now() - ((g * 37) % 129600 || ' minutes')::interval,
       now() - ((g * 13) % 10000 || ' minutes')::interval,
       now() - ((g * 29) % 50000 || ' minutes')::interval
FROM generate_series(1, 2000) g;

-- 100k messages, ~50 per lead, spread over ~70 days, mixed directions.
INSERT INTO knewit_messages (whatsapp_id, direction, message_type, content, stage_at_moment, tokens_used, response_time_ms, created_at)
SELECT 'perf14_' || (1 + (g % 2000)) || '@c.us',
       CASE WHEN g % 2 = 0 THEN 'in' ELSE 'out' END,
       'chat',
       'perf message ' || g,
       'НОВЫЙ_ЛИД',
       10 + (g % 200),
       CASE WHEN g % 2 = 1 THEN 500 + (g % 3000) ELSE NULL END,
       now() - (g || ' minutes')::interval
FROM generate_series(1, 100000) g;

INSERT INTO knewit_events (whatsapp_id, event_type, from_stage, to_stage, created_at)
SELECT 'perf14_' || (1 + (g % 2000)) || '@c.us',
       (ARRAY['stage_entered','objection_raised','trial_booked','transferred_to_manager'])[1 + (g % 4)],
       'НОВЫЙ_ЛИД', 'КВАЛИФИКАЦИЯ',
       now() - ((g * 3) || ' minutes')::interval
FROM generate_series(1, 10000) g;

INSERT INTO crm_conversation_state (whatsapp_id, unread_count, last_read_at, last_message_at, last_message_direction, last_message_preview)
SELECT 'perf14_' || g || '@c.us', CASE WHEN g % 5 = 0 THEN 3 ELSE 0 END, now(),
       now() - ((g * 29) % 50000 || ' minutes')::interval,
       CASE WHEN g % 2 = 0 THEN 'in' ELSE 'out' END,
       'perf message preview ' || g
FROM generate_series(1, 2000) g;

COMMIT;
