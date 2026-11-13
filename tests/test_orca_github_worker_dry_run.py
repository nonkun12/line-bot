import hashlib
import json
import unittest
from pathlib import Path
from datetime import datetime, timezone

from scripts.orca_github_worker_dry_run import (
    MAX_PAYLOAD_BYTES, WorkerDryRunRejected, dry_run_one,
)


class WorkerDryRunTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        self.task_id = "ai-speaker-empty-transcript-no-brain-call"
        self.payload = {"task_type": "add_regression_test", "target_path": "tests/test_ai_speaker.py", "contract_version": 1}
        self.payload_bytes = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()
        self.digest = hashlib.sha256(self.payload_bytes).hexdigest()
        self.state = {
            "schema_version": 1,
            "revision": 5,
            "global_hold": False,
            "emergency_stop": False,
            "run_guard": {
                "run_id": "run-1", "started_at": "2026-11-13T12:00:00Z",
                "tasks_claimed": 1, "attempts_by_task": {self.task_id: 1},
                "consecutive_failures": 0, "circuit_breaker_until": None,
                "paid_services_enabled": False, "automatic_retry_enabled": False,
                "outcomes_by_task": {},
            },
            "tasks": [{
                "task_id": self.task_id,
                "request_hash": self.digest,
                "status": "claimed",
                "created_at": "2026-11-13T11:59:00Z",
            }],
            "active_lease": {
                "task_id": self.task_id,
                "owner": "worker-1",
                "run_id": "run-1",
                "expires_at": "2026-11-13T12:10:00Z",
            },
            "consumed_approval_ids": ["a" * 64],
        }
        self.envelope = {
            "task_id": self.task_id,
            "request_hash": self.digest,
            "owner": "worker-1",
            "run_id": "run-1",
            "payload": self.payload,
        }

    def test_valid_single_claim_returns_dry_run_without_execution(self):
        result = dry_run_one(queue_state=self.state, envelope=self.envelope, now=self.now)
        self.assertEqual(result["status"], "DRY_RUN_PASS")
        self.assertFalse(result["side_effects_performed"])
        self.assertFalse(result["execution_started"])
        self.assertEqual(result["request_hash"], self.digest)
        self.assertFalse(result["execution_supported"])
        self.assertEqual(result["task_contract"]["status"], "BLOCKED_HANDLER_NOT_IMPLEMENTED")

    def test_catalog_matches_finite_typed_registry_and_one_task_cap(self):
        catalog_path = Path(__file__).resolve().parents[1] / ".github" / "autonomous-loop-tasks.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(catalog["max_tasks_per_run"], 1)
        for item in catalog["tasks"]:
            with self.subTest(task_id=item["id"]):
                self.assertEqual(item["task_type"], "add_regression_test")
                self.assertEqual(item["contract_version"], 1)
                self.assertEqual(len(item["allowed_paths"]), 1)
                self.assertEqual(item["allowed_paths"][0], {
                    "ai-speaker-empty-transcript-no-brain-call": "tests/test_ai_speaker.py",
                    "recovery-ai-state-isolation": "tests/test_recovery_ai.py",
                    "router-regression-general-request-metadata": "tests/test_management_router.py",
                    "recovery-ai-loop-adapter-durable-state-readback": "tests/test_recovery_ai_loop_adapter.py",
                }[item["id"]])

    def test_emergency_stop_and_missing_stop_state_fail_closed(self):
        stopped = dict(self.state, emergency_stop=True)
        with self.assertRaisesRegex(WorkerDryRunRejected, "emergency_stop_active"):
            dry_run_one(queue_state=stopped, envelope=self.envelope, now=self.now)

        missing = dict(self.state)
        missing.pop("emergency_stop")
        with self.assertRaisesRegex(WorkerDryRunRejected, "emergency_stop_active"):
            dry_run_one(queue_state=missing, envelope=self.envelope, now=self.now)

    def test_runaway_guard_limits_are_rechecked_at_worker_boundary(self):
        cases = [
            ("paid_services_enabled", "paid_services_forbidden"),
            ("automatic_retry_enabled", "automatic_retry_forbidden"),
            ("consecutive_failures", "failure_circuit_breaker_open"),
            ("tasks_claimed", "worker_run_task_count_invalid"),
        ]
        for field, expected in cases:
            with self.subTest(field=field):
                state = json.loads(json.dumps(self.state))
                if field == "paid_services_enabled":
                    state["run_guard"][field] = True
                elif field == "automatic_retry_enabled":
                    state["run_guard"][field] = True
                elif field == "consecutive_failures":
                    state["run_guard"][field] = 2
                else:
                    state["run_guard"][field] = 2
                with self.assertRaisesRegex(WorkerDryRunRejected, expected):
                    dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)

    def test_global_hold_blocks(self):
        state = dict(self.state, global_hold=True)
        with self.assertRaisesRegex(WorkerDryRunRejected, "global_hold"):
            dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)

    def test_missing_or_malformed_envelope_blocks(self):
        for envelope in (None, {}, dict(self.envelope, extra="not-allowed")):
            with self.subTest(envelope=envelope):
                with self.assertRaises(WorkerDryRunRejected):
                    dry_run_one(queue_state=self.state, envelope=envelope, now=self.now)

    def test_payload_hash_mismatch_blocks(self):
        envelope = dict(self.envelope, payload={"task_type": "add_regression_test", "target_path": "tests/test_ai_speaker.py", "contract_version": 2})
        with self.assertRaisesRegex(WorkerDryRunRejected, "payload_hash_mismatch"):
            dry_run_one(queue_state=self.state, envelope=envelope, now=self.now)

    def test_payload_size_limit_blocks(self):
        payload = {"data": "x" * (MAX_PAYLOAD_BYTES + 1)}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        envelope = dict(self.envelope, payload=payload, request_hash=hashlib.sha256(raw).hexdigest())
        state = {
            **self.state,
            "tasks": [{**self.state["tasks"][0], "request_hash": envelope["request_hash"]}],
        }
        with self.assertRaisesRegex(WorkerDryRunRejected, "payload_too_large"):
            dry_run_one(queue_state=state, envelope=envelope, now=self.now)

    def test_unknown_task_id_and_free_form_payload_block(self):
        unknown = dict(self.envelope, task_id="unknown-task")
        with self.assertRaisesRegex(WorkerDryRunRejected, "task_id_not_in_typed_allowlist"):
            dry_run_one(queue_state=self.state, envelope=unknown, now=self.now)
        arbitrary = dict(self.envelope, payload={"operation": "shell", "command": "echo unsafe"})
        raw = json.dumps(arbitrary["payload"], sort_keys=True, separators=(",", ":")).encode()
        arbitrary["request_hash"] = hashlib.sha256(raw).hexdigest()
        state = {**self.state, "tasks": [{**self.state["tasks"][0], "request_hash": arbitrary["request_hash"]}]}
        with self.assertRaisesRegex(WorkerDryRunRejected, "typed_task_payload_shape_invalid"):
            dry_run_one(queue_state=state, envelope=arbitrary, now=self.now)

    def test_unclaimed_task_blocks(self):
        state = {
            **self.state,
            "tasks": [{**self.state["tasks"][0], "status": "queued"}],
            "active_lease": None,
        }
        with self.assertRaisesRegex(WorkerDryRunRejected, "not_claimed"):
            dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)

    def test_missing_lease_blocks(self):
        state = dict(self.state, active_lease=None)
        with self.assertRaisesRegex(WorkerDryRunRejected, "lease_task_state_mismatch"):
            dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)

    def test_wrong_owner_or_run_blocks(self):
        envelope = dict(self.envelope, owner="other-worker")
        with self.assertRaisesRegex(WorkerDryRunRejected, "lease_owner_or_run"):
            dry_run_one(queue_state=self.state, envelope=envelope, now=self.now)

    def test_expired_lease_blocks(self):
        state = {
            **self.state,
            "active_lease": {**self.state["active_lease"], "expires_at": "2026-11-13T11:59:59Z"},
        }
        with self.assertRaisesRegex(WorkerDryRunRejected, "lease_expired"):
            dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)

    def test_naive_clock_blocks(self):
        with self.assertRaisesRegex(WorkerDryRunRejected, "clock_timezone_missing"):
            dry_run_one(queue_state=self.state, envelope=self.envelope,
                        now=datetime(2026, 11, 13, 12, 0))

    def test_duplicate_or_inconsistent_queue_blocks(self):
        state = {**self.state, "tasks": self.state["tasks"] * 2}
        with self.assertRaises(WorkerDryRunRejected):
            dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)


if __name__ == "__main__":
    unittest.main()
