CREATE INDEX IF NOT EXISTS idx_site_point_ledger_user_created
ON site_point_ledger(user_id, created_at DESC, id DESC);
