-- One-time replay protection for task-bound LINE approvals.
-- Existing current approvals are backfilled; overwritten historical nonces
-- cannot be reconstructed and must be treated as a pre-migration exposure.
CREATE TABLE task_approval_nonces (
  approval_nonce TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  request_hash TEXT NOT NULL,
  approver_user_id TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

INSERT INTO task_approval_nonces
  (approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
SELECT approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at
  FROM task_approvals;

CREATE INDEX idx_task_approval_nonces_task
  ON task_approval_nonces(task_id, recorded_at);
