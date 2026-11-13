"""Phase 3-C adversarial tests for the shared Emergency Stop latch.

All tests use in-memory fake state persistence; no GitHub calls or task execution.
"""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone

from scripts.orca_github_task_queue import empty_state, enqueue, claim_next, QueueRejected
from scripts.orca_github_emergency_stop import (
    activate_emergency_stop, require_not_stopped, EmergencyStopRejected,
)
from scripts.orca_github_state_store import StateSnapshot, StateConflict
from scripts.orca_github_worker_dry_run import dry_run_one, WorkerDryRunRejected


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
PAYLOAD = {"kind": "safety-test"}
PAYLOAD_BYTES = json.dumps(PAYLOAD, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
PAYLOAD_HASH = hashlib.sha256(PAYLOAD_BYTES).hexdigest()


class MemoryStore:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.writes = 0
        self.fail_write = False

    def read(self):
        return self.snapshot

    def write(self, *, snapshot, next_state, expected_revision):
        self.writes += 1
        if self.fail_write or snapshot.ref_sha != self.snapshot.ref_sha:
            raise StateConflict("simulated_stale_ref")
        if snapshot.state["revision"] != expected_revision:
            raise StateConflict("simulated_stale_revision")
        if next_state["revision"] != expected_revision + 1:
            raise StateConflict("simulated_revision_increment")
        self.snapshot = StateSnapshot(
            ref_sha=("b" * 40), state=copy.deepcopy(next_state), blob_sha="blob-next",
        )
        return self.snapshot


class Phase3EmergencyStopSafetyTests(unittest.TestCase):
    def claimed(self):
        state = empty_state()
        state["global_hold"] = False
        state = enqueue(
            state, expected_revision=0, task_id="task-1",
            request_hash=PAYLOAD_HASH, approved=True,
            created_at="2026-11-13T11:59:00Z",
        )
        state = claim_next(
            state, expected_revision=1, owner="worker-1", run_id="run-1",
            now="2026-11-13T12:00:00Z",
        )
        state["run_guard"] = {
            "run_id": "run-1", "started_at": "2026-11-13T12:00:00Z",
            "tasks_claimed": 1, "attempts_by_task": {"task-1": 1},
            "consecutive_failures": 0, "circuit_breaker_until": None,
            "paid_services_enabled": False, "automatic_retry_enabled": False,
        }
        return state

    def envelope(self):
        return {
            "task_id": "task-1", "request_hash": PAYLOAD_HASH,
            "owner": "worker-1", "run_id": "run-1", "payload": copy.deepcopy(PAYLOAD),
        }

    def snapshot(self, state):
        return StateSnapshot(ref_sha="a" * 40, state=copy.deepcopy(state), blob_sha="blob")

    def test_stop_latches_durably_and_worker_boundary_blocks(self):
        state = self.claimed()
        store = MemoryStore(self.snapshot(state))
        result = activate_emergency_stop(
            store=store, snapshot=store.read(), requested_by="terminal:operator",
            reason="runaway suspected", event_id="event-1", now=NOW,
            human_authorized=True,
        )
        self.assertEqual(result["status"], "EMERGENCY_STOPPED")
        self.assertTrue(result["snapshot"].state["emergency_stop"])
        self.assertEqual(store.writes, 1)
        with self.assertRaisesRegex(WorkerDryRunRejected, "emergency_stop_active"):
            dry_run_one(
                queue_state=result["snapshot"].state, envelope=self.envelope(), now=NOW,
            )

    def test_queue_claim_rejected_after_stop(self):
        state = self.claimed()
        state["emergency_stop"] = True
        state["revision"] += 1
        with self.assertRaisesRegex(QueueRejected, "emergency_stop_active"):
            claim_next(
                state, expected_revision=state["revision"], owner="worker-2",
                run_id="run-2", now="2026-11-13T12:00:01Z",
            )

    def test_missing_or_unverifiable_stop_field_blocks(self):
        with self.assertRaisesRegex(EmergencyStopRejected, "emergency_stop_active"):
            require_not_stopped({"global_hold": False})

    def test_repeated_stop_is_idempotent_and_does_not_overwrite_audit(self):
        state = self.claimed()
        state["emergency_stop"] = True
        state["emergency_stop_event"] = {"event_hash": "original"}
        snapshot = self.snapshot(state)
        store = MemoryStore(snapshot)
        result = activate_emergency_stop(
            store=store, snapshot=snapshot, requested_by="line:hashed-user",
            reason="repeat stop", event_id="event-2", now=NOW,
            human_authorized=True,
        )
        self.assertEqual(result["status"], "ALREADY_STOPPED")
        self.assertEqual(store.writes, 0)
        self.assertEqual(result["snapshot"].state["emergency_stop_event"], {"event_hash": "original"})

    def test_stale_snapshot_stop_write_fails_closed(self):
        state = self.claimed()
        snapshot = self.snapshot(state)
        store = MemoryStore(snapshot)
        store.fail_write = True
        with self.assertRaises(StateConflict):
            activate_emergency_stop(
                store=store, snapshot=snapshot, requested_by="terminal:operator",
                reason="stop", event_id="event-3", now=NOW,
                human_authorized=True,
            )
        self.assertFalse(store.snapshot.state["emergency_stop"])

    def test_unauthorized_or_naive_clock_cannot_latch_stop(self):
        state = self.claimed()
        snapshot = self.snapshot(state)
        store = MemoryStore(snapshot)
        with self.assertRaisesRegex(EmergencyStopRejected, "human_authorization_required"):
            activate_emergency_stop(
                store=store, snapshot=snapshot, requested_by="line:unknown",
                reason="stop", event_id="event-4", now=NOW,
                human_authorized=False,
            )
        with self.assertRaisesRegex(EmergencyStopRejected, "timezone_required"):
            activate_emergency_stop(
                store=store, snapshot=snapshot, requested_by="terminal:operator",
                reason="stop", event_id="event-5", now=datetime(2026, 11, 13, 12, 0),
                human_authorized=True,
            )
        self.assertEqual(store.writes, 0)


if __name__ == "__main__":
    unittest.main()
