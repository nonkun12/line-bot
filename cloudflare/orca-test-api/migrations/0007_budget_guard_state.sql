-- Durable admission state. A fresh, explicit CLEAR/WARN row is required;
-- initial and unknown states block all new task admission.
CREATE TABLE IF NOT EXISTS budget_guard_state (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  status TEXT NOT NULL CHECK (status IN ('CLEAR', 'WARN', 'SUPPRESS', 'STOP', 'BLOCKED')),
  reason TEXT NOT NULL,
  stop_latched INTEGER NOT NULL DEFAULT 0 CHECK (stop_latched IN (0, 1)),
  release_approved INTEGER NOT NULL DEFAULT 0 CHECK (release_approved IN (0, 1)),
  observed_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO budget_guard_state
  (singleton, status, reason, stop_latched, release_approved, observed_at)
VALUES
  (1, 'BLOCKED', 'budget_guard_not_initialized', 0, 0, NULL);
