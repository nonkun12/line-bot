-- One-time schema addition for cryptographically task-bound LINE approval.
-- Apply only after confirming migration 0002 has been applied to the target D1.
CREATE TABLE IF NOT EXISTS task_approvals (
  task_id TEXT PRIMARY KEY,
  approval_id TEXT NOT NULL UNIQUE,
  approval_nonce TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  approver_user_id TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'approved'
    CHECK (status IN ('approved', 'consumed')),
  FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
CREATE INDEX IF NOT EXISTS idx_task_approvals_due
  ON task_approvals(status, expires_at);
