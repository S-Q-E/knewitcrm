-- Test seed: covers all statuses/stages used by the CRM.
-- Stages come from frontend/app.js STAGE_LABELS, statuses from backend stats.

INSERT INTO knewit_leads (whatsapp_id, name, current_stage, previous_stage, status, direction, goal, experience_level, preferred_format, preferred_time, trial_datetime, last_objection, created_at, updated_at, last_message_at, confidence_last) VALUES
('77010000001@c.us', 'Айгерим Тестова', 'НОВЫЙ_ЛИД', NULL, 'ACTIVE', 'in', 'Шить для себя', 'beginner', 'offline', 'вечер', NULL, NULL, now() - interval '3 days', now() - interval '1 hour', now() - interval '1 hour', 0.91),
('77010000002@c.us', 'Болат Записан', 'ЗАПИСЬ', 'ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ', 'ЗАПИСАН', 'in', 'Шить на заказ', 'middle', 'online', 'утро', now() + interval '2 days', NULL, now() - interval '5 days', now() - interval '2 hours', now() - interval '2 hours', 0.87),
('77010000003@c.us', 'Мадина Думает', 'РАБОТА_С_ВОЗРАЖЕНИЕМ', 'ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ', 'ДУМАЕТ', 'in', 'Хобби', 'beginner', 'online', 'день', NULL, 'дорого', now() - interval '7 days', now() - interval '1 day', now() - interval '1 day', 0.62),
('77010000004@c.us', 'Серик Менеджер', 'ЦЕЛЕВОЕ_ДЕЙСТВИЕ', 'КВАЛИФИКАЦИЯ', 'МЕНЕДЖЕР', 'in', 'Бизнес', 'advanced', 'offline', 'вечер', NULL, 'хочет поговорить с человеком', now() - interval '2 days', now() - interval '30 minutes', now() - interval '30 minutes', 0.55),
('77010000005@c.us', 'Асель Клиент', 'ПРОДАЖА', 'ПОДТВЕРЖДЕНИЕ', 'КЛИЕНТ', 'in', 'Профессия', 'middle', 'offline', 'утро', now() - interval '1 day', NULL, now() - interval '20 days', now() - interval '1 day', now() - interval '1 day', 0.99),
('77010000006@c.us', 'Тимур Отказ', 'СОМНЕНИЯ_ПОСЛЕ_ПРОБНОГО', 'ПОСЛЕ_ПРОБНОГО', 'ОТКАЗ', 'in', 'Хобби', 'beginner', 'online', 'вечер', NULL, 'нет времени', now() - interval '10 days', now() - interval '3 days', now() - interval '3 days', 0.41)
ON CONFLICT (whatsapp_id) DO NOTHING;

INSERT INTO knewit_messages (whatsapp_id, direction, message_type, content, stage_at_moment, tokens_used, response_time_ms, created_at) VALUES
('77010000001@c.us', 'in', 'chat', 'Здравствуйте! Хочу научиться шить', 'НОВЫЙ_ЛИД', 12, NULL, now() - interval '2 hours'),
('77010000001@c.us', 'out', 'chat', 'Здравствуйте, Айгерим! Расскажите, какая у вас цель?', 'ВЫЯВЛЕНИЕ_ПОТРЕБНОСТИ', 45, 1200, now() - interval '2 hours' + interval '1 minute'),
('77010000001@c.us', 'in', 'chat', 'Хочу шить для себя и семьи', 'ВЫЯВЛЕНИЕ_ПОТРЕБНОСТИ', 10, NULL, now() - interval '1 hour'),
('77010000002@c.us', 'in', 'chat', 'Запишите меня на пробный урок', 'ЦЕЛЕВОЕ_ДЕЙСТВИЕ', 9, NULL, now() - interval '2 hours'),
('77010000002@c.us', 'out', 'chat', 'Готово! Ждём вас в четверг в 10:00', 'ЗАПИСЬ', 30, 900, now() - interval '2 hours' + interval '2 minutes'),
('77010000003@c.us', 'in', 'chat', 'Дороговато для меня', 'РАБОТА_С_ВОЗРАЖЕНИЕМ', 8, NULL, now() - interval '1 day'),
('77010000004@c.us', 'in', 'chat', 'Соедините с менеджером', 'ЦЕЛЕВОЕ_ДЕЙСТВИЕ', 7, NULL, now() - interval '30 minutes'),
('77010000005@c.us', 'out', 'chat', 'Поздравляем с покупкой курса!', 'ПРОДАЖА', 20, 800, now() - interval '1 day'),
('77010000006@c.us', 'in', 'chat', 'Не смогу ходить, нет времени', 'СОМНЕНИЯ_ПОСЛЕ_ПРОБНОГО', 11, NULL, now() - interval '3 days');

INSERT INTO knewit_events (whatsapp_id, event_type, from_stage, to_stage, payload, created_at) VALUES
('77010000001@c.us', 'stage_entered', NULL, 'НОВЫЙ_ЛИД', '{}', now() - interval '3 days'),
('77010000001@c.us', 'stage_entered', 'НОВЫЙ_ЛИД', 'ВЫЯВЛЕНИЕ_ПОТРЕБНОСТИ', '{}', now() - interval '2 hours'),
('77010000002@c.us', 'stage_entered', 'ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ', 'ЗАПИСЬ', '{}', now() - interval '2 hours'),
('77010000002@c.us', 'trial_booked', NULL, NULL, '{"trial_datetime": "in 2 days"}', now() - interval '2 hours'),
('77010000003@c.us', 'objection_raised', NULL, NULL, '{"objection": "дорого"}', now() - interval '1 day'),
('77010000004@c.us', 'transferred_to_manager', NULL, NULL, '{"reason": "хочет поговорить с человеком"}', now() - interval '30 minutes'),
('77010000005@c.us', 'sale_won', NULL, 'ПРОДАЖА', '{}', now() - interval '1 day'),
('77010000006@c.us', 'lead_lost', NULL, NULL, '{"reason": "нет времени"}', now() - interval '3 days');

INSERT INTO knewit_followups (whatsapp_id, run_at, status, payload, created_at) VALUES
('77010000003@c.us', now() + interval '2 days', 'queued', '{"note": "follow-up: подумать"}', now());
