CREATE TABLE IF NOT EXISTS site_user_agreements(
    user_id TEXT NOT NULL REFERENCES site_users(id) ON DELETE CASCADE,
    agreement_version TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    client TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY(user_id, agreement_version)
);

CREATE INDEX IF NOT EXISTS idx_site_user_agreements_user_accepted
ON site_user_agreements(user_id, accepted_at DESC);
