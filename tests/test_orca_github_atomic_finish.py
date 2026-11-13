import hashlib
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from scripts.orca_github_atomic_finish import persist_task_outcome
from scripts.orca_github_runaway_guard import RunawayGuardRejected
from scripts.orca_github_state_store import StateConflict, StateSnapshot
from scripts.orca_github_task_queue import empty_state, enqueue, claim_next


TASK_ID = "ai-speaker-empty-transcript-no-brain-call"
PAYLOAD = {
    "task_type": "add_regression_test",
    "target_path": "tests/test_ai_speaker.py",
    "contract_version": 1,
}
PAYLOAD_HASH = hashlib.sha256(json.dumps(
    PAYLOAD, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
).encode("utf-8")).hexdigest()
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


class AtomicFinishTests(unittest.TestCase):
    def setUp(self):
        state = empty_state()
        state["global_hold"] = False
        state = enqueue(
            state, expected_revision=0, task_id=TASK_ID,
            request_hash=PAYLOAD_HASH, approved=True,
            created_at="2026-11-13T11:59:00Z",
        )
        state = claim_next(
            state, expected_revision=1, owner="worker-1", run_id="run-1",
            now="2026-11-13T12:00:00Z", task_id=TASK_ID,
        )
        state["run_guard"] = {
            "run_id": "run-1", "started_at": "2026-11-13T12:00:00Z",
            "tasks_claimed": 1, "attempts_by_task": {TASK_ID: 1},
            "consecutive_failures": 0, "circuit_breaker_until": None,
            "paid_services_enabled": False, "automatic_retry_enabled": False,
            "outcomes_by_task": {},
        }
        self.snapshot = StateSnapshot("a" * 40, state, "b" * 40)
        self.store = Mock()
        self.store.write.side_effect = lambda *, snapshot, next_state, expected_revision: StateSnapshot(
            "c" * 40, next_state, "d" * 40
        )

    def call(self, outcome="done", *, owner="worker-1", now=NOW):
        return persist_task_outcome(
            store=self.store, snapshot=self.snapshot, task_id=TASK_ID,
            owner=owner, run_id="run-1", now=now, outcome=outcome,
        )

    def test_done_status_lease_release_and_guard_commit_in_one_cas(self):
        result = self.call()
        self.assertEqual(result["status"], "RECORDED")
        self.assertTrue(result["persisted"])
        self.store.write.assert_called_once()
        kwargs = self.store.write.call_args.kwargs
        self.assertIs(kwargs["snapshot"], self.snapshot)
        self.assertEqual(kwargs["expected_revision"], self.snapshot.state["revision"])
        state = kwargs["next_state"]
        self.assertEqual(state["tasks"][0]["status"], "done")
        self.assertIsNone(state["active_lease"])
        self.assertEqual(state["run_guard"]["outcomes_by_task"], {TASK_ID: "done"})
        self.assertEqual(state["run_guard"]["consecutive_failures"], 0)
        self.assertIsNone(state["run_guard"]["circuit_breaker_until"])

    def test_failure_counter_and_cooldown_are_in_same_cas(self):
        state = dict(self.snapshot.state)
        state["run_guard"] = dict(state["run_guard"], consecutive_failures=1)
        self.snapshot = StateSnapshot(self.snapshot.ref_sha, state, self.snapshot.blob_sha)
        result = self.call("failed")
        self.assertEqual(result["status"], "RECORDED")
        next_state = self.store.write.call_args.kwargs["next_state"]
        self.assertEqual(next_state["tasks"][0]["status"], "failed")
        self.assertIsNone(next_state["active_lease"])
        self.assertEqual(next_state["run_guard"]["consecutive_failures"], 2)
        self.assertEqual(
            next_state["run_guard"]["circuit_breaker_until"],
            "2026-11-13T13:00:00Z",
        )

    def test_identical_replay_does_not_write_twice(self):
        first = self.call()
        persisted_snapshot = first["snapshot"]
        self.snapshot = persisted_snapshot
        self.store.write.reset_mock()
        replay = self.call()
        self.assertEqual(replay["status"], "ALREADY_RECORDED")
        self.assertFalse(replay["persisted"])
        self.store.write.assert_not_called()

    def test_replay_from_different_run_is_rejected_before_persistence(self):
        first = self.call()
        self.snapshot = first["snapshot"]
        self.store.write.reset_mock()
        with self.assertRaisesRegex(RunawayGuardRejected, "guard_run_id_mismatch"):
            persist_task_outcome(
                store=self.store, snapshot=self.snapshot, task_id=TASK_ID,
                owner="worker-1", run_id="attacker-run", now=NOW, outcome="done",
            )
        self.store.write.assert_not_called()

    def test_wrong_owner_is_rejected_before_persistence(self):
        with self.assertRaisesRegex(RunawayGuardRejected, "lease_owner_mismatch"):
            self.call(owner="attacker")
        self.store.write.assert_not_called()

    def test_stale_cas_conflict_is_not_retried(self):
        self.store.write.side_effect = StateConflict("github_ref_fast_forward_conflict")
        with self.assertRaisesRegex(StateConflict, "fast_forward"):
            self.call()
        self.store.write.assert_called_once()

    def test_naive_clock_is_rejected(self):
        with self.assertRaisesRegex(RunawayGuardRejected, "timezone"):
            self.call(now=datetime(2026, 11, 13, 12, 0))
        self.store.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
