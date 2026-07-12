CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_user_created
ON site_asr_tasks(user_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_media_id
ON site_asr_tasks(media_id);

CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_status_updated
ON site_asr_tasks(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_expires_at
ON site_asr_tasks(expires_at);

CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_local_expires_at
ON site_asr_tasks(local_expires_at);
