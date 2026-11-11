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
NONCE_MIGRATION = ROOT / "migrations" / "0004_append_only_approval_nonce_history.sql"


class AtomicClaimContractTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
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
        self.db.executescript(NONCE_MIGRATION.read_text(encoding="utf-8"))

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
               (task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status)
               VALUES ('t-1', 'approval-1', ?, ?, 'U123', '2026-11-11T00:00:00Z',
                       '2999-01-01T00:00:00Z', 'approved')""",
            ("C" * 32, "a" * 64),
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
        self.assertEqual(
            self.db.execute("SELECT status FROM task_approvals WHERE task_id='t-1'").fetchone()[0],
            "consumed",
        )

    def _upsert_approval(self, approval_id, nonce, request_hash, issued_at="2026-11-11T00:02:00Z"):
        try:
            self.db.execute("BEGIN")
            self.db.execute(
                """INSERT INTO task_approval_nonces
                   (approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
                   VALUES (?, 't-1', ?, ?, 'U123', ?, '2999-01-01T00:00:00Z')""",
                (nonce, approval_id, request_hash, issued_at),
            )
            result = self.db.execute(
                """INSERT INTO task_approvals
                   (task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status)
                   SELECT 't-1', ?, ?, ?, 'U123', ?, '2999-01-01T00:00:00Z', 'approved'
                     FROM tasks
                    WHERE task_id='t-1' AND (status='queued' OR
                      (status='running' AND lease_until IS NOT NULL
                        AND datetime(lease_until) <= CURRENT_TIMESTAMP))
                   ON CONFLICT(task_id) DO UPDATE SET
                     approval_id=excluded.approval_id,
                     approval_nonce=excluded.approval_nonce,
                     request_hash=excluded.request_hash,
                     issued_at=excluded.issued_at,
                     expires_at=excluded.expires_at,
                     status='approved'
                   WHERE julianday(excluded.issued_at) > julianday(task_approvals.issued_at)
                     AND (task_approvals.status='approved' OR
                       (task_approvals.status='consumed' AND EXISTS
                         (SELECT 1 FROM tasks WHERE task_id=excluded.task_id
                           AND status='running' AND datetime(lease_until) <= CURRENT_TIMESTAMP)))""",
                (approval_id, nonce, request_hash, issued_at),
            )
            self.db.commit()
            return result.rowcount
        except sqlite3.IntegrityError:
            self.db.rollback()
            return 0

    def test_consumed_approval_can_be_reissued_only_after_lease_expiry(self):
        self.insert_task()
        self.db.execute(
            """INSERT INTO task_approval_nonces
               (approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
               VALUES (?, 't-1', 'old-approval', ?, 'U123', '2026-11-11T00:00:00Z', '2026-11-11T00:01:00Z')""",
            ("A" * 32, "a" * 64),
        )
        self.db.execute(
            "UPDATE tasks SET status='running', lease_until='2000-01-01T00:00:00Z' WHERE task_id='t-1'"
        )
        self.db.execute(
            """INSERT INTO task_approvals
               (task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status)
               VALUES ('t-1', 'old-approval', ?, ?, 'U123', '2026-11-11T00:00:00Z',
                       '2026-11-11T00:01:00Z', 'consumed')""",
            ("A" * 32, "a" * 64),
        )
        self.db.commit()
        result = self._upsert_approval("new-approval", "B" * 32, "b" * 64)
        self.assertEqual(result, 1)
        self.assertEqual(
            self.db.execute("SELECT status FROM task_approvals WHERE task_id='t-1'").fetchone()[0],
            "approved",
        )

    def test_consumed_approval_cannot_be_replayed_after_lease_expiry(self):
        self.insert_task()
        self.db.execute(
            """INSERT INTO task_approval_nonces
               (approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
               VALUES (?, 't-1', 'old-approval', ?, 'U123', '2026-11-11T00:00:00Z', '2026-11-11T00:01:00Z')""",
            ("A" * 32, "a" * 64),
        )
        self.db.execute(
            "UPDATE tasks SET status='running', lease_until='2000-01-01T00:00:00Z' WHERE task_id='t-1'"
        )
        self.db.execute(
            """INSERT INTO task_approvals
               (task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status)
               VALUES ('t-1', 'old-approval', ?, ?, 'U123', '2026-11-11T00:00:00Z',
                       '2026-11-11T00:01:00Z', 'consumed')""",
            ("A" * 32, "a" * 64),
        )
        self.db.commit()
        replay = self._upsert_approval("replayed-approval", "A" * 32, "a" * 64)
        self.assertEqual(replay, 0)
        fresh = self._upsert_approval("fresh-approval", "B" * 32, "b" * 64)
        self.assertEqual(fresh, 1)

    def test_consumed_approval_cannot_be_reissued_while_lease_is_active(self):
        self.insert_task()
        self.db.execute(
            """INSERT INTO task_approval_nonces
               (approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
               VALUES (?, 't-1', 'old-approval', ?, 'U123', '2026-11-11T00:00:00Z', '2026-11-11T00:01:00Z')""",
            ("A" * 32, "a" * 64),
        )
        self.db.execute(
            "UPDATE tasks SET status='running', lease_until='2999-01-01T00:00:00Z' WHERE task_id='t-1'"
        )
        self.db.execute(
            """INSERT INTO task_approvals
               (task_id, approval_id, approval_nonce, request_hash, approver_user_id, issued_at, expires_at, status)
               VALUES ('t-1', 'old-approval', ?, ?, 'U123', '2026-11-11T00:00:00Z',
                       '2026-11-11T00:01:00Z', 'consumed')""",
            ("A" * 32, "a" * 64),
        )
        self.db.commit()
        result = self._upsert_approval("new-approval", "B" * 32, "b" * 64)
        self.assertEqual(result, 0)

    def test_old_nonce_cannot_be_replayed_after_a_newer_approval(self):
        self.insert_task()
        self.assertEqual(self._upsert_approval("approval-a", "A" * 32, "a" * 64,
                                               "2026-11-11T00:01:00Z"), 1)
        self.assertEqual(self._upsert_approval("approval-b", "B" * 32, "b" * 64,
                                               "2026-11-11T00:02:00Z"), 1)
        self.assertEqual(self._upsert_approval("replay-a", "A" * 32, "a" * 64,
                                               "2026-11-11T00:01:00Z"), 0)
        self.assertEqual(self.db.execute(
            "SELECT approval_nonce FROM task_approvals WHERE task_id='t-1'"
        ).fetchone()[0], "B" * 32)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM task_approval_nonces WHERE task_id='t-1'"
        ).fetchone()[0], 2)

    def test_older_distinct_nonce_cannot_overwrite_newer_approval(self):
        self.insert_task()
        self.assertEqual(self._upsert_approval("approval-b", "B" * 32, "b" * 64,
                                               "2026-11-11T00:02:00Z"), 1)
        self.assertEqual(self._upsert_approval("approval-c", "C" * 32, "c" * 64,
                                               "2026-11-11T00:01:00Z"), 0)
        self.assertEqual(self.db.execute(
            "SELECT approval_nonce FROM task_approvals WHERE task_id='t-1'"
        ).fetchone()[0], "B" * 32)
        # Even a stale nonce is recorded and cannot be retried.
        self.assertEqual(self._upsert_approval("replay-c", "C" * 32, "c" * 64,
                                               "2026-11-11T00:01:00Z"), 0)

    def test_terminal_task_cannot_receive_a_new_approval(self):
        self.insert_task()
        self.db.execute("UPDATE tasks SET status='pass' WHERE task_id='t-1'")
        self.db.commit()
        result = self._upsert_approval("terminal-approval", "T" * 32, "t" * 64)
        self.assertEqual(result, 0)
        # The unused signed nonce is retained, so it cannot later be replayed.
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM task_approval_nonces WHERE approval_nonce=?",
                            ("T" * 32,)).fetchone()[0],
            1,
        )
        self.assertIsNone(self.db.execute(
            "SELECT task_id FROM task_approvals WHERE task_id='t-1'"
        ).fetchone())

    def test_nonce_history_enforces_foreign_keys(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                """INSERT INTO task_approval_nonces
                   (approval_nonce, task_id, approval_id, request_hash, approver_user_id, issued_at, expires_at)
                   VALUES (?, 'missing-task', 'approval-x', 'a', 'U123', '2026-11-11T00:00:00Z', '2999-01-01T00:00:00Z')""",
                ("N" * 32,),
            )

    def test_worker_claim_requires_approval_validation_and_hmac(self):
        source = (ROOT / "src" / "index.js").read_text(encoding="utf-8")
        self.assertIn("crypto.subtle.importKey", source)
        self.assertIn("approval_nonce", source)
        self.assertIn("INSERT INTO task_approval_nonces", source)
        self.assertIn("julianday(excluded.issued_at) > julianday(task_approvals.issued_at)", source)
        self.assertIn("env.DB.batch([", source)
        self.assertIn("expires > issued + 60 * 60000", source)
        self.assertIn("expires <= issued", source)
        self.assertIn("ORCA_TASK_APPROVAL_HMAC_KEY", source)
        self.assertIn("AbortSignal.timeout(10_000)", source)
        self.assertIn("new TextEncoder().encode(approvalKey).length < 32", source)
        self.assertIn("task.user_id !== userId", source)
        self.assertIn("issuedAt, expiresAt, nonce].join", source)
        self.assertIn("status, lease_until, user_id FROM tasks", source)
        self.assertIn("approval_nonce", source)
        self.assertIn("only explicit app-development tasks can be approved", source)
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


    def test_status_endpoint_is_scoped_to_verified_line_owner(self):
        source = (ROOT / "src" / "index.js").read_text(encoding="utf-8")
        self.assertIn("complete|status", source)
        self.assertIn('parsed.action === "status" && request.method === "GET"', source)
        self.assertIn("WHERE task_id = ? AND user_id = ?", source)
        self.assertIn("SELECT task_id, status, created_at, updated_at FROM tasks", source)
        self.assertIn('json({ error: "not found" }, 404)', source)

    def test_status_query_returns_only_the_matching_task_owner(self):
        db = sqlite3.connect(":memory:")
        try:
            db.executescript("""
                CREATE TABLE tasks (
                  task_id TEXT PRIMARY KEY,
                  request_text TEXT NOT NULL,
                  status TEXT NOT NULL,
                  user_id TEXT
                );
            """)
            db.execute(
                "INSERT INTO tasks(task_id, request_text, status, user_id) VALUES (?, ?, ?, ?)",
                ("owned-task", "private request", "queued", "U" + "a" * 32),
            )
            own = db.execute(
                "SELECT task_id, status FROM tasks WHERE task_id = ? AND user_id = ?",
                ("owned-task", "U" + "a" * 32),
            ).fetchone()
            other = db.execute(
                "SELECT task_id, status FROM tasks WHERE task_id = ? AND user_id = ?",
                ("owned-task", "U" + "b" * 32),
            ).fetchone()
            missing = db.execute(
                "SELECT task_id, status FROM tasks WHERE task_id = ? AND user_id = ?",
                ("missing-task", "U" + "a" * 32),
            ).fetchone()
            self.assertEqual(tuple(own), ("owned-task", "queued"))
            self.assertIsNone(other)
            self.assertIsNone(missing)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

