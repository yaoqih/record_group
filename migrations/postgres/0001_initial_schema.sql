CREATE TABLE IF NOT EXISTS id_counters(
    prefix TEXT PRIMARY KEY,
    next_value BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records(
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    title TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcript_segments(
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    text TEXT NOT NULL,
    speaker TEXT,
    start_time TEXT,
    end_time TEXT,
    confidence DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_anchors(
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    segment_id TEXT NOT NULL REFERENCES transcript_segments(id),
    quote TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT
);

CREATE TABLE IF NOT EXISTS topic_blocks(
    created_order BIGSERIAL,
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    segment_ids JSONB NOT NULL,
    importance TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_objects(
    created_order BIGSERIAL,
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    evidence_ids JSONB NOT NULL,
    version INTEGER NOT NULL,
    confidence DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS change_events(
    created_order BIGSERIAL,
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    record_id TEXT NOT NULL REFERENCES records(id),
    change_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    target_object_id TEXT,
    candidate_object_id TEXT NOT NULL,
    requires_review BOOLEAN NOT NULL,
    evidence_ids JSONB NOT NULL,
    field_changes JSONB NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS jobs(
    created_order BIGSERIAL,
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload JSONB NOT NULL,
    record_id TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS record_digests(
    created_order BIGSERIAL,
    record_id TEXT PRIMARY KEY REFERENCES records(id),
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    digest_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS media_records(
    created_order BIGSERIAL,
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    source_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    url TEXT NOT NULL,
    public_url TEXT NOT NULL,
    object_name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    original_size_bytes BIGINT,
    compressed_size_bytes BIGINT NOT NULL,
    compression_codec TEXT,
    status TEXT NOT NULL,
    asr_task_id TEXT,
    transcript_text TEXT,
    utterances JSONB NOT NULL,
    raw_asr_result JSONB NOT NULL,
    record_id TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created_order ON jobs(status, created_order);

CREATE TABLE IF NOT EXISTS site_users(
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    points_balance INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_point_ledger(
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    delta INTEGER NOT NULL,
    kind TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    task_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS site_wechat_identities(
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    appid TEXT NOT NULL,
    openid TEXT NOT NULL,
    unionid TEXT NOT NULL DEFAULT '',
    session_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(appid, openid)
);

CREATE TABLE IF NOT EXISTS site_payment_orders(
    out_trade_no TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    points INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    status TEXT NOT NULL,
    transaction_id TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS site_asr_tasks(
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    media_id TEXT,
    job_id TEXT,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    content_type TEXT NOT NULL,
    status TEXT NOT NULL,
    points_cost INTEGER NOT NULL,
    charge_basis TEXT NOT NULL,
    agreement_version TEXT NOT NULL,
    editable_utterances JSONB NOT NULL DEFAULT '[]'::jsonb,
    error TEXT,
    confirmed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    original_size_bytes BIGINT NOT NULL DEFAULT 0,
    duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    local_file_path TEXT,
    local_expires_at TIMESTAMPTZ,
    raw_result JSONB DEFAULT '{}'::jsonb
);

ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS original_size_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS local_file_path TEXT;
ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS local_expires_at TIMESTAMPTZ;
ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS editable_utterances JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS raw_result JSONB DEFAULT '{}'::jsonb;
UPDATE site_asr_tasks SET raw_result = '{}'::jsonb WHERE raw_result IS NULL;
ALTER TABLE site_asr_tasks ALTER COLUMN raw_result SET DEFAULT '{}'::jsonb;
