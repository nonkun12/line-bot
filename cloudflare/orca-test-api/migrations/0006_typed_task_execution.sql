-- Add an explicit execution type and bounded loop count.
-- Existing rows are classified as app_development; no legacy row is promoted
-- to distributed_loop by this migration.
ALTER TABLE tasks
  ADD COLUMN task_type TEXT NOT NULL DEFAULT 'app_development'
  CHECK (task_type IN ('app_development', 'distributed_loop'));

ALTER TABLE tasks
  ADD COLUMN max_tasks INTEGER NOT NULL DEFAULT 1
  CHECK (
    (task_type = 'app_development' AND max_tasks = 1)
    OR
    (task_type = 'distributed_loop' AND max_tasks BETWEEN 1 AND 4)
  );

ALTER TABLE task_approvals
  ADD COLUMN task_type TEXT NOT NULL DEFAULT 'app_development'
  CHECK (task_type IN ('app_development', 'distributed_loop'));

ALTER TABLE task_approvals
  ADD COLUMN max_tasks INTEGER NOT NULL DEFAULT 1
  CHECK (
    (task_type = 'app_development' AND max_tasks = 1)
    OR
    (task_type = 'distributed_loop' AND max_tasks BETWEEN 1 AND 4)
  );

CREATE INDEX IF NOT EXISTS idx_tasks_type_status_created
  ON tasks(task_type, status, created_at);
