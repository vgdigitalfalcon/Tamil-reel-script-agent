-- ScriptFalcon v2.0 PostgreSQL Schema for VG Digital Falcon CRM

CREATE TABLE IF NOT EXISTS clients (
    client_id VARCHAR(100) PRIMARY KEY,
    client_name VARCHAR(255) NOT NULL,
    target_audience TEXT,
    industry VARCHAR(150),
    brand_tone VARCHAR(100),
    forbidden_words JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_quotas (
    client_id VARCHAR(100) PRIMARY KEY REFERENCES clients(client_id) ON DELETE CASCADE,
    balance_inr NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    reserved_inr NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    monthly_budget_inr NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS quota_reservations (
    reservation_id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(100) NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    user_id VARCHAR(100) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    reserved_amount_inr NUMERIC(12, 4) NOT NULL,
    actual_cost_inr NUMERIC(12, 4),
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL CHECK (status IN ('RESERVED', 'SETTLED', 'REFUNDED', 'EXPIRED')),
    dedup_key VARCHAR(128),
    usage_date VARCHAR(16),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_quota_res_client_status
    ON quota_reservations (client_id, status, expires_at);

CREATE TABLE IF NOT EXISTS user_daily_usage (
    user_id VARCHAR(100) NOT NULL,
    usage_date VARCHAR(16) NOT NULL,
    run_count INTEGER NOT NULL DEFAULT 0,
    bonus_runs_granted INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_inr NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, usage_date)
);

CREATE TABLE IF NOT EXISTS script_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    reservation_id VARCHAR(64) REFERENCES quota_reservations(reservation_id) ON DELETE SET NULL,
    deliverable_id VARCHAR(64),
    client_id VARCHAR(100) NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    user_id VARCHAR(100) NOT NULL,
    operation VARCHAR(32) NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_inr NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    usage_date VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS request_dedup_locks (
    dedup_key VARCHAR(128) PRIMARY KEY,
    client_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS script_deliverables (
    deliverable_id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(100) NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
    user_id VARCHAR(100) NOT NULL,
    topic TEXT NOT NULL,
    duration INTEGER NOT NULL,
    tone VARCHAR(64) NOT NULL,
    objective VARCHAR(200) NOT NULL,
    deliverable_json JSONB NOT NULL,
    model_used VARCHAR(100) NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_inr NUMERIC(12, 4) NOT NULL DEFAULT 0.0000,
    parent_deliverable_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_script_deliverables_client_created
    ON script_deliverables (client_id, created_at DESC);

-- Standalone (non-CRM) studio generations. No client FK: these are not billed to a CRM client.
CREATE TABLE IF NOT EXISTS standalone_deliverables (
    deliverable_id VARCHAR(64) PRIMARY KEY,
    topic TEXT NOT NULL,
    platform VARCHAR(64) NOT NULL DEFAULT '',
    duration INTEGER NOT NULL,
    tone VARCHAR(64) NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    deliverable_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_standalone_deliverables_updated
    ON standalone_deliverables (updated_at DESC);
