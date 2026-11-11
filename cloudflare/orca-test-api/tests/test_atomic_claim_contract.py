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
APPROVAL_MIGRATION = ROOT / "migrations" / "0003_task_bound_approvals.sql"


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
        self.db.executescript(APPROVAL_MIGRATION.read_text(encoding="utf-8"))

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
        update = self.db.execute(
            """
            UPDATE tasks SET status='pass'
             WHERE task_id=? AND status='running' AND lease_token=?
               AND datetime(lease_until) > CURRENT_TIMESTAMP
            """,
            ("t-1", "valid"),
        )
        self.db.execute(
            """
            INSERT INTO notification_outbox(outbox_id, task_id, user_id, message)
            SELECT ?, task_id, user_id, ?
              FROM tasks
             WHERE task_id=? AND status='pass' AND lease_token=?
               AND user_id IS NOT NULL
            """,
            (str(uuid.uuid4()), "ORCA task passed", "t-1", "valid"),
        )
        self.db.execute(
            "UPDATE tasks SET lease_token=NULL, lease_until=NULL WHERE task_id='t-1' AND status='pass' AND lease_token='valid'"
        )
        self.db.commit()
        self.assertEqual(update.rowcount, 1)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0], 1
        )

    def test_only_one_dispatcher_claims_an_outbox_row(self):
        self.insert_task()
        self.claim("t-1", "valid", "2999-01-01T00:00:00.000Z")
        self.db.commit()
        self.db.execute(
            """
            INSERT INTO notification_outbox(outbox_id, task_id, user_id, message)
            VALUES ('out-1', 't-1', 'U123', 'done')
            """
        )
        self.db.commit()
        first = self.db.execute(
            """
            UPDATE notification_outbox
               SET dispatch_token='sender-a', dispatch_until=datetime('now', '+5 minutes')
             WHERE outbox_id='out-1' AND status='pending'
               AND (dispatch_until IS NULL OR datetime(dispatch_until) <= CURRENT_TIMESTAMP)
             RETURNING outbox_id
            """
        ).fetchone()
        second = self.db.execute(
            """
            UPDATE notification_outbox
               SET dispatch_token='sender-b', dispatch_until=datetime('now', '+5 minutes')
             WHERE outbox_id='out-1' AND status='pending'
               AND (dispatch_until IS NULL OR datetime(dispatch_until) <= CURRENT_TIMESTAMP)
             RETURNING outbox_id
            """
        ).fetchone()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

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



    def test_task_cannot_be_claimed_without_signed_approval_record(self):
        self.insert_task()
        token = "worker-token"
        result = self.db.execute(
            """
            UPDATE tasks SET status='running', lease_token=?, lease_until='2999-01-01T00:00:00Z'
             WHERE task_id='t-1' AND status='queued'
               AND EXISTS (SELECT 1 FROM task_approvals
                            WHERE task_id='t-1' AND status='approved'
                              AND datetime(expires_at) > CURRENT_TIMESTAMP)
            """,
            (token,),
        )
        self.assertEqual(result.rowcount, 0)
        self.assertEqual(self.db.execute("SELECT status FROM tasks WHERE task_id='t-1'").fetchone()[0], "queued")

    def test_task_approval_is_consumed_atomically_with_claim(self):
        self.insert_task()
        self.db.execute(
            """INSERT INTO task_approvals
               (task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
               VALUES ('t-1', 'approval-1', ?, 'U123', '2026-11-11T00:00:00Z', '2999-01-01T00:00:00Z')""",
            ("a" * 64,),
        )
        self.db.commit()
        self.db.execute("BEGIN")
        claimed = self.db.execute(
            """UPDATE tasks SET status='running', lease_token='claim-1', lease_until='2999-01-01T00:00:00Z'
                 WHERE task_id='t-1' AND status='queued'
                   AND EXISTS (SELECT 1 FROM task_approvals WHERE task_id='t-1'
                     AND approval_id='approval-1' AND status='approved'
                     AND datetime(expires_at) > CURRENT_TIMESTAMP)"""
        )
        consumed = self.db.execute(
            """UPDATE task_approvals SET status='consumed'
                 WHERE task_id='t-1' AND approval_id='approval-1' AND status='approved'
                   AND EXISTS (SELECT 1 FROM tasks WHERE task_id='t-1'
                     AND status='running' AND lease_token='claim-1')"""
        )
        self.db.commit()
        self.assertEqual(claimed.rowcount, 1)
        self.assertEqual(consumed.rowcount, 1)
        retry = self.db.execute(
            """UPDATE tasks SET status='running', lease_token='claim-2'
                 WHERE task_id='t-1' AND status='queued'
                   AND EXISTS (SELECT 1 FROM task_approvals WHERE task_id='t-1' AND status='approved')"""
        )
        self.assertEqual(retry.rowcount, 0)

    def test_worker_claim_requires_approval_validation_and_hmac(self):
        source = (ROOT / "src" / "index.js").read_text(encoding="utf-8")
        self.assertIn("crypto.subtle.importKey", source)
        self.assertIn("ORCA_TASK_APPROVAL_HMAC_KEY", source)
        self.assertIn("task.user_id !== userId", source)
        self.assertIn('parsed.action === "approve"', source)
        self.assertIn("a valid task-bound LINE approval is required", source)


    def test_task_list_exposes_only_boolean_approval_state(self):
        source = (ROOT / "src" / "index.js").read_text(encoding="utf-8")
        self.assertIn("AS approved", source)
        self.assertIn('url.searchParams.get("approved") === "true"', source)
        self.assertIn("ORDER BY created_at \" + order", source)
        self.assertIn("a.status = 'approved'", source)
        self.assertIn("datetime(a.expires_at) > CURRENT_TIMESTAMP", source)
        self.assertNotIn("approver_user_id FROM task_approvals", source)

    def test_outbox_dispatch_batch_stays_within_free_subrequest_budget(self):
        source = (ROOT / "src" / "index.js").read_text(encoding="utf-8")
        self.assertIn("ORDER BY created_at LIMIT 10", source)


if __name__ == "__main__":
    unittest.main()
