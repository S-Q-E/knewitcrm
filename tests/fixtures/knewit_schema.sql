-- Local/test replica of n8n-owned knewit_* tables.
-- Production tables belong to n8n; CRM never migrates them.
-- This file is for docker-compose init and local development only.

CREATE TABLE IF NOT EXISTS knewit_leads (
    whatsapp_id TEXT PRIMARY KEY,
    name TEXT,
    current_stage TEXT,
    previous_stage TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    direction TEXT,
    goal TEXT,
    experience_level TEXT,
    preferred_format TEXT,
    preferred_time TEXT,
    trial_datetime TIMESTAMPTZ,
    last_objection TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_message_at TIMESTAMPTZ,
    confidence_last DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS knewit_messages (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id TEXT NOT NULL REFERENCES knewit_leads(whatsapp_id) ON DELETE CASCADE,
    direction TEXT NOT NULL DEFAULT 'in',
    message_type TEXT NOT NULL DEFAULT 'chat',
    content TEXT,
    stage_at_moment TEXT,
    tokens_used INTEGER,
    response_time_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knewit_events (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id TEXT NOT NULL REFERENCES knewit_leads(whatsapp_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knewit_followups (
    id BIGSERIAL PRIMARY KEY,
    whatsapp_id TEXT NOT NULL REFERENCES knewit_leads(whatsapp_id) ON DELETE CASCADE,
    run_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'queued',
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON knewit_leads (status);
CREATE INDEX IF NOT EXISTS idx_leads_current_stage ON knewit_leads (current_stage);
CREATE INDEX IF NOT EXISTS idx_messages_whatsapp_created ON knewit_messages (whatsapp_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_whatsapp ON knewit_events (whatsapp_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON knewit_events (event_type);
