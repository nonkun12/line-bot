import hashlib
import json
import unittest
from datetime import datetime, timezone

from scripts.orca_github_worker_dry_run import (
    MAX_PAYLOAD_BYTES, WorkerDryRunRejected, dry_run_one,
)


class WorkerDryRunTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        self.payload = {"operation": "analyze", "input": "sample"}
        self.payload_bytes = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()
        self.digest = hashlib.sha256(self.payload_bytes).hexdigest()
        self.state = {
            "schema_version": 1,
            "revision": 5,
            "global_hold": False,
            "tasks": [{
                "task_id": "task-1",
                "request_hash": self.digest,
                "status": "claimed",
                "created_at": "2026-11-13T11:59:00Z",
            }],
            "active_lease": {
                "task_id": "task-1",
                "owner": "worker-1",
                "run_id": "run-1",
                "expires_at": "2026-11-13T12:10:00Z",
            },
            "consumed_approval_ids": ["a" * 64],
        }
        self.envelope = {
            "task_id": "task-1",
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
        envelope = dict(self.envelope, payload={"operation": "different"})
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

    def test_unclaimed_task_blocks(self):
        state = {**self.state, "tasks": [{**self.state["tasks"][0], "status": "queued"}]}
        with self.assertRaisesRegex(WorkerDryRunRejected, "not_claimed"):
            dry_run_one(queue_state=state, envelope=self.envelope, now=self.now)

    def test_missing_lease_blocks(self):
        state = dict(self.state, active_lease=None)
        with self.assertRaisesRegex(WorkerDryRunRejected, "lease_missing"):
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
