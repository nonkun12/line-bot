"""SQLite contract tests for the ORCA D1 lease and outbox migration.

These tests exercise the migration's SQL invariants locally; they do not replace
Cloudflare D1 integration tests or deploy the Worker.
"""
import pathlib
import sqlite3
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0002_atomic_claims_and_outbox.sql"


class AtomicClaimContractTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE tasks (
              task_id TEXT PRIMARY KEY,
              request_text TEXT NOT NULL,
              status TEXT NOT NULL,
              source_event_id TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.db.executescript(MIGRATION.read_text(encoding="utf-8"))

    def tearDown(self):
        self.db.close()

    def insert_task(self, task_id="t-1", user_id="U123"):
        self.db.execute(
            "INSERT INTO tasks(task_id, request_text, status, user_id) VALUES (?, ?, 'queued', ?)",
            (task_id, "アプリ開発: test", user_id),
        )
        self.db.commit()

    def claim(self, task_id, token, lease_until):
        return self.db.execute(
            """
            UPDATE tasks
               SET status='running', lease_token=?, lease_until=?,
                   attempt_count=COALESCE(attempt_count, 0) + 1
             WHERE task_id=? AND (
               status='queued' OR
               (status='running' AND datetime(lease_until) <= CURRENT_TIMESTAMP)
             )
             RETURNING task_id, status, attempt_count
            """,
            (token, lease_until, task_id),
        ).fetchone()

    def test_only_one_claim_wins(self):
        self.insert_task()
        future = "2999-01-01T00:00:00.000Z"
        self.assertIsNotNone(self.claim("t-1", "token-a", future))
        self.assertIsNone(self.claim("t-1", "token-b", future))

    def test_expired_lease_can_be_reclaimed_and_old_token_is_stale(self):
        self.insert_task()
        self.assertIsNotNone(self.claim("t-1", "old", "2000-01-01T00:00:00.000Z"))
        self.assertIsNotNone(self.claim("t-1", "new", "2999-01-01T00:00:00.000Z"))
        stale = self.db.execute(
            """UPDATE tasks SET status='pass'
               WHERE task_id='t-1' AND status='running' AND lease_token='old'
                 AND datetime(lease_until) > CURRENT_TIMESTAMP"""
        )
        self.assertEqual(stale.rowcount, 0)

    def test_completion_and_outbox_are_bound_to_current_unexpired_claim(self):
        self.insert_task()
        self.claim("t-1", "valid", "2999-01-01T00:00:00.000Z")
        self.db.commit()
        self.db.execute("BEGIN")
        self.db.execute(
            """
            INSERT INTO notification_outbox(outbox_id, task_id, user_id, message)
            SELECT ?, task_id, user_id, ?
              FROM tasks
             WHERE task_id=? AND status='running' AND lease_token=?
               AND datetime(lease_until) > CURRENT_TIMESTAMP
               AND user_id IS NOT NULL
            """,
            (str(uuid.uuid4()), "ORCA task passed", "t-1", "valid"),
        )
        update = self.db.execute(
            """
            UPDATE tasks SET status='pass', lease_token=NULL, lease_until=NULL
             WHERE task_id=? AND status='running' AND lease_token=?
               AND datetime(lease_until) > CURRENT_TIMESTAMP
            """,
            ("t-1", "valid"),
        )
        self.db.commit()
        self.assertEqual(update.rowcount, 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 1
        )

    def test_no_outbox_for_tasks_without_line_user_id(self):
        self.insert_task(user_id=None)
        self.claim("t-1", "valid", "2999-01-01T00:00:00.000Z")
        self.db.execute(
            """
            INSERT INTO notification_outbox(outbox_id, task_id, user_id, message)
            SELECT ?, task_id, user_id, ?
              FROM tasks
             WHERE task_id=? AND status='running' AND lease_token=?
               AND datetime(lease_until) > CURRENT_TIMESTAMP
               AND user_id IS NOT NULL
            """,
            ("outbox-1", "done", "t-1", "valid"),
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
