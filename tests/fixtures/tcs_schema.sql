-- Test replica of the production n8n-owned tcs_* tables.
-- Source: schema_dump.sql (structure of the production database, pg_dump 16).
-- Production tables belong to n8n; CRM never migrates them (see docs/db_schema.md).
-- Production has NO foreign keys between tcs_* tables: rows are matched by
-- whatsapp_id, so tests must delete child rows explicitly.

CREATE OR REPLACE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS tcs_leads (
    id SERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL UNIQUE,
    client_name VARCHAR(100),
    phone VARCHAR(30),
    target_course VARCHAR(100),
    course_format VARCHAR(20),
    class_type VARCHAR(20),
    skill_level VARCHAR(30),
    student_category VARCHAR(30),
    primary_objection TEXT,
    status VARCHAR(30) DEFAULT 'new',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    current_stage VARCHAR(50) DEFAULT 'НОВЫЙ_ЛИД',
    direction VARCHAR(100),
    goal VARCHAR(200),
    experience_level VARCHAR(50),
    preferred_format VARCHAR(50),
    preferred_time VARCHAR(50),
    trial_datetime TIMESTAMPTZ,
    last_message_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    reminder_sent BOOLEAN DEFAULT FALSE,
    confidence_last NUMERIC(3,2),
    name VARCHAR(100),
    source VARCHAR(100) DEFAULT 'whatsapp',
    previous_stage VARCHAR(50),
    lead_data JSONB DEFAULT '{}'::jsonb,
    last_objection TEXT,
    last_interaction_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tcs_messages (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL,
    direction VARCHAR(3) NOT NULL CHECK (direction IN ('in', 'out')),
    message_type VARCHAR(20) DEFAULT 'chat',
    content TEXT,
    stage_at_moment VARCHAR(50),
    tokens_used INTEGER,
    response_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tcs_events (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    from_stage VARCHAR(50),
    to_stage VARCHAR(50),
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tcs_followups (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL,
    kind VARCHAR(20) NOT NULL DEFAULT 'THINKING',
    scheduled_at TIMESTAMPTZ NOT NULL,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tcs_ai_metrics (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL,
    unresolved_question TEXT,
    dialogue_turns INTEGER DEFAULT 0,
    token_usage INTEGER,
    transferred_to_manager BOOLEAN DEFAULT FALSE,
    is_lead BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tcs_chat_history (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id VARCHAR(50) NOT NULL,
    sender VARCHAR(20) NOT NULL,
    message_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tcs_leads_created ON tcs_leads (created_at);
CREATE INDEX IF NOT EXISTS idx_tcs_leads_stage ON tcs_leads (current_stage);
CREATE INDEX IF NOT EXISTS idx_tcs_leads_status ON tcs_leads (status);
CREATE INDEX IF NOT EXISTS idx_tcs_messages_created ON tcs_messages (created_at);
CREATE INDEX IF NOT EXISTS idx_tcs_messages_wa ON tcs_messages (whatsapp_id);
CREATE INDEX IF NOT EXISTS idx_tcs_events_created ON tcs_events (created_at);
CREATE INDEX IF NOT EXISTS idx_tcs_events_type ON tcs_events (event_type);
CREATE INDEX IF NOT EXISTS idx_tcs_events_wa ON tcs_events (whatsapp_id);
CREATE INDEX IF NOT EXISTS idx_tcs_followups_due ON tcs_followups (status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_tcs_metrics_created_at ON tcs_ai_metrics (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tcs_chat_history_whatsapp_id ON tcs_chat_history (whatsapp_id, created_at DESC);

DROP TRIGGER IF EXISTS update_tcs_leads_updated_at ON tcs_leads;
CREATE TRIGGER update_tcs_leads_updated_at BEFORE UPDATE ON tcs_leads
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();
