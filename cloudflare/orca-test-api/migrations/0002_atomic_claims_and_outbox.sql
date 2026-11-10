-- Apply once to the existing orca-test-ledger D1 database.
-- Safe to run only after confirming these columns/tables do not already exist.
ALTER TABLE tasks ADD COLUMN user_id TEXT;
ALTER TABLE tasks ADD COLUMN lease_token TEXT;
ALTER TABLE tasks ADD COLUMN lease_until TEXT;
ALTER TABLE tasks ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_tasks_queued_lease
  ON tasks(status, lease_until);

CREATE TABLE IF NOT EXISTS notification_outbox (
  outbox_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'sent', 'dead')),
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  sent_at TEXT,
  last_error_code TEXT,
  FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_due
  ON notification_outbox(status, next_attempt_at, created_at);
