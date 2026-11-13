from datetime import datetime, timezone
import unittest

from scripts.orca_github_task_queue import (
    QueueRejected, empty_state, enqueue, claim_next, finish, reclaim_expired,
)

HASH = "a" * 64
NOW = "2026-11-13T10:00:00Z"


class QueueStateMachineTests(unittest.TestCase):
    def queued(self):
        state = empty_state()
        state["global_hold"] = False
        return enqueue(state, expected_revision=0, task_id="task-1",
                       request_hash=HASH, approved=True, created_at=NOW)

    def test_hold_blocks_claim(self):
        state = enqueue(empty_state(), expected_revision=0, task_id="task-1",
                        request_hash=HASH, approved=True, created_at=NOW)
        with self.assertRaisesRegex(QueueRejected, "global_hold_active"):
            claim_next(state, expected_revision=1, owner="worker", run_id="run-1", now=NOW)

    def test_unapproved_task_rejected(self):
        with self.assertRaisesRegex(QueueRejected, "explicit_approval_required"):
            enqueue(empty_state(), expected_revision=0, task_id="task-1",
                    request_hash=HASH, approved=False, created_at=NOW)

    def test_claim_and_finish_owner_bound(self):
        state = claim_next(self.queued(), expected_revision=1, owner="mac",
                           run_id="run-1", now=NOW)
        with self.assertRaisesRegex(QueueRejected, "lease_owner_mismatch"):
            finish(state, expected_revision=2, task_id="task-1", owner="other",
                   run_id="run-1", now=NOW, outcome="done")
        done = finish(state, expected_revision=2, task_id="task-1", owner="mac",
                      run_id="run-1", now=NOW, outcome="done")
        self.assertEqual(done["tasks"][0]["status"], "done")
        self.assertIsNone(done["active_lease"])

    def test_single_active_lease(self):
        state = self.queued()
        state = enqueue(state, expected_revision=1, task_id="task-2",
                        request_hash="b" * 64, approved=True, created_at=NOW)
        state = claim_next(state, expected_revision=2, owner="mac", run_id="run-1", now=NOW)
        with self.assertRaisesRegex(QueueRejected, "worker_already_has_active_lease"):
            claim_next(state, expected_revision=3, owner="mac", run_id="run-2", now=NOW)

    def test_expired_lease_reclaimed_to_queue(self):
        state = claim_next(self.queued(), expected_revision=1, owner="mac",
                           run_id="run-1", now=NOW, lease_seconds=30)
        state = reclaim_expired(state, expected_revision=2, now="2026-11-13T10:00:31Z")
        self.assertEqual(state["tasks"][0]["status"], "queued")
        self.assertIsNone(state["active_lease"])

    def test_stale_revision_rejected(self):
        with self.assertRaisesRegex(QueueRejected, "stale_revision_conflict"):
            enqueue(empty_state(), expected_revision=9, task_id="task-1",
                    request_hash=HASH, approved=True, created_at=NOW)

    def test_expired_lease_cannot_finish(self):
        state = claim_next(self.queued(), expected_revision=1, owner="mac",
                           run_id="run-1", now=NOW, lease_seconds=30)
        with self.assertRaisesRegex(QueueRejected, "lease_expired"):
            finish(state, expected_revision=2, task_id="task-1", owner="mac",
                   run_id="run-1", now="2026-11-13T10:00:31Z", outcome="done")


if __name__ == "__main__":
    unittest.main()
