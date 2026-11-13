import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from scripts.orca_github_atomic_claim import authorize_and_claim_one
from scripts.orca_github_state_store import StateConflict, StateSnapshot


class AtomicClaimTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        self.state = {
            "schema_version": 1,
            "revision": 4,
            "global_hold": False,
            "emergency_stop": False,
            "tasks": [{
                "task_id": "task-1",
                "request_hash": "a" * 64,
                "status": "queued",
                "created_at": "2026-11-13T11:59:00Z",
            }],
            "active_lease": None,
            "consumed_approval_ids": [],
            "run_guard": {
                "run_id": "run-1", "started_at": "2026-11-13T12:00:00Z",
                "tasks_claimed": 0, "attempts_by_task": {},
                "consecutive_failures": 0, "circuit_breaker_until": None,
                "paid_services_enabled": False, "automatic_retry_enabled": False,
            },
        }
        self.snapshot = StateSnapshot("b" * 40, self.state, "c" * 40)
        self.store = Mock()
        self.gate_result = {
            "status": "PASS",
            "execution_enabled": False,
            "consume_approval_id": "d" * 64,
        }

    def call(self):
        return authorize_and_claim_one(
            store=self.store,
            snapshot=self.snapshot,
            repository="owner/repo",
            task_id="task-1",
            request_hash="a" * 64,
            approval={"signed": "approval"},
            approval_signing_key="approval-key",
            allowed_approvers={"line-user"},
            budget_evidence={"signed": "budget"},
            budget_signing_key="budget-key",
            billing_account_id="billing-123",
            improvement_cycle={"cycle_id": "cycle"},
            now=self.now,
            owner="worker-1",
            run_id="run-1",
        )

    @patch("scripts.orca_github_atomic_claim.evaluate_execution_gate")
    def test_replay_marker_and_lease_are_committed_in_one_write(self, gate):
        gate.return_value = self.gate_result
        def persist(*, snapshot, next_state, expected_revision):
            self.assertIs(snapshot, self.snapshot)
            self.assertEqual(expected_revision, 4)
            self.assertEqual(next_state["consumed_approval_ids"], ["d" * 64])
            self.assertEqual(next_state["tasks"][0]["status"], "claimed")
            self.assertEqual(next_state["active_lease"]["task_id"], "task-1")
            return StateSnapshot("e" * 40, next_state, "f" * 40)
        self.store.write.side_effect = persist

        result = self.call()

        self.assertEqual(result["status"], "CLAIMED")
        self.assertFalse(result["execution_started"])
        self.store.write.assert_called_once()

    @patch("scripts.orca_github_atomic_claim.evaluate_execution_gate")
    def test_gate_rejection_never_writes_or_claims(self, gate):
        gate.side_effect = ValueError("global_hold_active_or_unverifiable")
        with self.assertRaisesRegex(ValueError, "global_hold"):
            self.call()
        self.store.write.assert_not_called()

    @patch("scripts.orca_github_atomic_claim.evaluate_execution_gate")
    def test_non_pass_or_execution_enabled_gate_result_is_rejected(self, gate):
        gate.return_value = dict(self.gate_result, execution_enabled=True)
        with self.assertRaisesRegex(RuntimeError, "non_executing_pass"):
            self.call()
        self.store.write.assert_not_called()

    @patch("scripts.orca_github_atomic_claim.evaluate_execution_gate")
    def test_stale_ref_conflict_propagates_without_retry(self, gate):
        gate.return_value = self.gate_result
        self.store.write.side_effect = StateConflict("github_ref_fast_forward_conflict")
        with self.assertRaisesRegex(StateConflict, "fast_forward"):
            self.call()
        self.store.write.assert_called_once()

    @patch("scripts.orca_github_atomic_claim.evaluate_execution_gate")
    def test_duplicate_approval_marker_aborts_before_write(self, gate):
        gate.return_value = self.gate_result
        self.state["consumed_approval_ids"] = ["d" * 64]
        with self.assertRaisesRegex(RuntimeError, "approval_replay"):
            self.call()
        self.store.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
