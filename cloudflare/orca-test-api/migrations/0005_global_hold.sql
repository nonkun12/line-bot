-- Global HOLD starts engaged. A human must explicitly set value='off' to
-- authorize autonomous execution. Missing table/row or any other value blocks.
CREATE TABLE IF NOT EXISTS system_controls (
  control_key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO system_controls (control_key, value)
VALUES ('global_hold', 'on');
