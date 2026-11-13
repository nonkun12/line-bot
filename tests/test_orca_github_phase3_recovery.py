"""Phase 3-C crash, replay, retry, and concurrency adversarial tests.

These tests exercise only pure state transitions and the side-effect-free
worker dry-run. They do not contact GitHub or execute task payloads.
"""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone

from scripts.orca_github_task_queue import (
    QueueRejected, empty_state, enqueue, claim_next, finish, reclaim_expired,
)
from scripts.orca_github_worker_dry_run import WorkerDryRunRejected, dry_run_one
from scripts.orca_github_runaway_guard import RunawayGuardRejected, finish_with_outcome


NOW = "2026-11-13T12:00:00Z"
NOW_DT = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
TASK_ID = "ai-speaker-empty-transcript-no-brain-call"
PAYLOAD = {"task_type": "add_regression_test", "target_path": "tests/test_ai_speaker.py", "contract_version": 1}
PAYLOAD_BYTES = json.dumps(
    PAYLOAD, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
).encode("utf-8")
PAYLOAD_HASH = hashlib.sha256(PAYLOAD_BYTES).hexdigest()


class Phase3RecoveryTests(unittest.TestCase):
    def queued_state(self):
        state = empty_state()
        state["global_hold"] = False
        return enqueue(
            state, expected_revision=0, task_id=TASK_ID,
            request_hash=PAYLOAD_HASH, approved=True, created_at=NOW,
        )

    def claimed_state(self, *, run_id="run-1", lease_seconds=60):
        state = claim_next(
            self.queued_state(), expected_revision=1, owner="worker-1",
            run_id=run_id, now=NOW, lease_seconds=lease_seconds,
        )
        state["run_guard"] = {
            "run_id": run_id, "started_at": NOW,
            "tasks_claimed": 1, "attempts_by_task": {TASK_ID: 1},
            "consecutive_failures": 0, "circuit_breaker_until": None,
            "paid_services_enabled": False, "automatic_retry_enabled": False,
            "outcomes_by_task": {},
        }
        return state

    def envelope(self, *, run_id="run-1", owner="worker-1"):
        return {
            "task_id": TASK_ID, "request_hash": PAYLOAD_HASH,
            "owner": owner, "run_id": run_id, "payload": copy.deepcopy(PAYLOAD),
        }

    def test_crash_after_durable_claim_can_only_resume_as_dry_run(self):
        # Simulate process death immediately after claim commit: the durable
        # state contains a lease, but no task code has been run.
        state = self.claimed_state()
        before = copy.deepcopy(state)
        report = dry_run_one(queue_state=state, envelope=self.envelope(), now=NOW_DT)
        self.assertEqual(report["status"], "DRY_RUN_PASS")
        self.assertFalse(report["execution_started"])
        self.assertFalse(report["side_effects_performed"])
        self.assertEqual(state, before)

    def test_duplicate_delivery_cannot_obtain_a_second_claim(self):
        state = self.claimed_state()
        with self.assertRaisesRegex(QueueRejected, "worker_already_has_active_lease"):
            claim_next(
                state, expected_revision=state["revision"], owner="worker-2",
                run_id="run-2", now="2026-11-13T12:00:01Z",
            )

    def test_expired_claim_is_reclaimed_once_and_old_worker_is_fenced(self):
        claimed = self.claimed_state(lease_seconds=30)
        reclaimed = reclaim_expired(
            claimed, expected_revision=claimed["revision"],
            now="2026-11-13T12:00:31Z",
        )
        self.assertEqual(reclaimed["tasks"][0]["status"], "queued")
        self.assertIsNone(reclaimed["active_lease"])
        with self.assertRaisesRegex(QueueRejected, "no_expired_lease"):
            reclaim_expired(
                reclaimed, expected_revision=reclaimed["revision"],
                now="2026-11-13T12:00:32Z",
            )
        with self.assertRaisesRegex(QueueRejected, "stale_revision_conflict"):
            finish(
                claimed, expected_revision=claimed["revision"] - 1,
                task_id=TASK_ID, owner="worker-1", run_id="run-1",
                now="2026-11-13T12:00:32Z", outcome="done",
            )

    def test_reclaimed_task_gets_new_run_and_old_envelope_is_rejected(self):
        claimed = self.claimed_state(lease_seconds=30)
        reclaimed = reclaim_expired(
            claimed, expected_revision=claimed["revision"],
            now="2026-11-13T12:00:31Z",
        )
        new_claim = claim_next(
            reclaimed, expected_revision=reclaimed["revision"],
            owner="worker-2", run_id="run-2",
            now="2026-11-13T12:00:32Z",
        )
        new_claim["run_guard"] = {
            "run_id": "run-2", "started_at": "2026-11-13T12:00:32Z",
            "tasks_claimed": 1, "attempts_by_task": {TASK_ID: 1},
            "consecutive_failures": 0, "circuit_breaker_until": None,
            "paid_services_enabled": False, "automatic_retry_enabled": False,
        }
        with self.assertRaisesRegex(WorkerDryRunRejected, "lease_owner_or_run_mismatch"):
            dry_run_one(
                queue_state=new_claim, envelope=self.envelope(),
                now=datetime(2026, 11, 13, 12, 0, 33, tzinfo=timezone.utc),
            )
        new_report = dry_run_one(
            queue_state=new_claim, envelope=self.envelope(run_id="run-2", owner="worker-2"),
            now=datetime(2026, 11, 13, 12, 0, 33, tzinfo=timezone.utc),
        )
        self.assertEqual(new_report["status"], "DRY_RUN_PASS")

    def test_global_hold_asserted_after_claim_blocks_worker(self):
        state = self.claimed_state()
        held = {**state, "global_hold": True}
        with self.assertRaisesRegex(WorkerDryRunRejected, "global_hold"):
            dry_run_one(queue_state=held, envelope=self.envelope(), now=NOW_DT)

    def test_stale_lease_cannot_finish_after_expiry(self):
        state = self.claimed_state(lease_seconds=30)
        with self.assertRaisesRegex(QueueRejected, "lease_expired"):
            finish(
                state, expected_revision=state["revision"],
                task_id=TASK_ID, owner="worker-1", run_id="run-1",
                now="2026-11-13T12:00:31Z", outcome="done",
            )

    def test_wrong_worker_cannot_finish_or_reclaim_before_expiry(self):
        state = self.claimed_state()
        with self.assertRaisesRegex(QueueRejected, "lease_owner_mismatch"):
            finish(
                state, expected_revision=state["revision"],
                task_id=TASK_ID, owner="worker-2", run_id="run-1",
                now="2026-11-13T12:00:01Z", outcome="done",
            )
        with self.assertRaisesRegex(QueueRejected, "no_expired_lease"):
            reclaim_expired(
                state, expected_revision=state["revision"],
                now="2026-11-13T12:00:10Z",
            )

    def test_completed_task_cannot_be_finished_twice(self):
        state = self.claimed_state()
        done = finish(
            state, expected_revision=state["revision"],
            task_id=TASK_ID, owner="worker-1", run_id="run-1",
            now="2026-11-13T12:00:01Z", outcome="done",
        )
        self.assertEqual(done["tasks"][0]["status"], "done")
        with self.assertRaisesRegex(QueueRejected, "lease_owner_mismatch"):
            finish(
                done, expected_revision=done["revision"],
                task_id=TASK_ID, owner="worker-1", run_id="run-1",
                now="2026-11-13T12:00:02Z", outcome="done",
            )


    def test_failure_outcome_opens_breaker_and_replay_is_idempotent(self):
        state = self.claimed_state()
        state["run_guard"]["consecutive_failures"] = 1
        failed = finish_with_outcome(
            state=state, expected_revision=state["revision"], task_id=TASK_ID,
            owner="worker-1", run_id="run-1", now="2026-11-13T12:00:01Z",
            outcome="failed",
        )
        self.assertEqual(failed["tasks"][0]["status"], "failed")
        self.assertEqual(failed["run_guard"]["consecutive_failures"], 2)
        self.assertEqual(failed["run_guard"]["circuit_breaker_until"], "2026-11-13T13:00:01Z")
        replay = finish_with_outcome(
            state=failed, expected_revision=failed["revision"], task_id=TASK_ID,
            owner="worker-1", run_id="run-1", now="2026-11-13T12:00:02Z",
            outcome="failed",
        )
        self.assertEqual(replay, failed)

    def test_conflicting_outcome_replay_rejected(self):
        state = self.claimed_state()
        failed = finish_with_outcome(
            state=state, expected_revision=state["revision"], task_id=TASK_ID,
            owner="worker-1", run_id="run-1", now="2026-11-13T12:00:01Z",
            outcome="failed",
        )
        with self.assertRaisesRegex(RunawayGuardRejected, "conflicting_outcome_replay"):
            finish_with_outcome(
                state=failed, expected_revision=failed["revision"], task_id=TASK_ID,
                owner="worker-1", run_id="run-1", now="2026-11-13T12:00:02Z",
                outcome="done",
            )


    def test_new_run_guard_initialization_preserves_failure_history(self):
        from scripts.orca_github_runaway_guard import initialize_run_guard
        state = self.queued_state()
        state["run_guard"] = {
            "run_id": "old-run", "started_at": "2026-11-13T10:00:00Z",
            "tasks_claimed": 1, "attempts_by_task": {"old-task": 1},
            "consecutive_failures": 1, "circuit_breaker_until": None,
            "paid_services_enabled": False, "automatic_retry_enabled": False,
            "outcomes_by_task": {"old-task": "failed"},
        }
        guard = initialize_run_guard(state=state, run_id="new-run", now=NOW_DT)
        self.assertEqual(guard["run_id"], "new-run")
        self.assertEqual(guard["tasks_claimed"], 0)
        self.assertEqual(guard["consecutive_failures"], 1)
        self.assertEqual(guard["attempts_by_task"], {})
        self.assertFalse(guard["paid_services_enabled"])
        self.assertFalse(guard["automatic_retry_enabled"])
        with self.assertRaisesRegex(RunawayGuardRejected, "already_initialized"):
            initialize_run_guard(state={**state, "run_guard": guard}, run_id="new-run", now=NOW_DT)

    def test_new_run_guard_initialization_refuses_hold_stop_lease_and_cooldown(self):
        from scripts.orca_github_runaway_guard import initialize_run_guard
        state = self.queued_state()
        with self.assertRaisesRegex(RunawayGuardRejected, "global_hold"):
            initialize_run_guard(state={**state, "global_hold": True}, run_id="new", now=NOW_DT)
        with self.assertRaisesRegex(RunawayGuardRejected, "emergency_stop"):
            initialize_run_guard(state={**state, "emergency_stop": True}, run_id="new", now=NOW_DT)
        with self.assertRaisesRegex(RunawayGuardRejected, "active_lease"):
            initialize_run_guard(state={**state, "active_lease": {"task_id": "x"}}, run_id="new", now=NOW_DT)
        state["run_guard"] = {
            "run_id": "old", "started_at": NOW, "tasks_claimed": 1,
            "attempts_by_task": {}, "consecutive_failures": 1,
            "circuit_breaker_until": "2026-11-13T13:00:00Z",
            "paid_services_enabled": False, "automatic_retry_enabled": False,
            "outcomes_by_task": {},
        }
        with self.assertRaisesRegex(RunawayGuardRejected, "cooldown"):
            initialize_run_guard(state=state, run_id="new", now=NOW_DT)


if __name__ == "__main__":
    unittest.main()
