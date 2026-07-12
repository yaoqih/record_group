ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notify_on_complete BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notification_template_id TEXT NOT NULL DEFAULT '';

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notification_job_id TEXT;

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notification_status TEXT NOT NULL DEFAULT 'disabled';

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notification_attempts INTEGER NOT NULL DEFAULT 0;

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notification_last_error TEXT;

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMPTZ;

ALTER TABLE site_asr_tasks
ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
