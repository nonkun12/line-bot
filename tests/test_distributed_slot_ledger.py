"""Tests for the fail-closed distributed slot ledger contract."""
import unittest

from scripts.distributed_slot_ledger import (
    expected_idempotency_key,
    transition_decision,
    validate_slot_record,
)


def pending_record():
    slot_id = "2026-11-19T10:17:00Z"
    return {
        "slot_id": slot_id,
        "workflow_id": 357086091,
        "idempotency_key": expected_idempotency_key(slot_id),
        "status": "PENDING",
        "attempt": 0,
        "created_at": "2026-11-19T10:17:02Z",
    }


class DistributedSlotLedgerContractTests(unittest.TestCase):
    def test_valid_pending_record(self):
        self.assertEqual(validate_slot_record(pending_record()), [])

    def test_rejects_wrong_slot_minute(self):
        record = pending_record()
        record["slot_id"] = "2026-11-19T10:30:00Z"
        self.assertIn("slot_id must be a real UTC :17 or :47 calendar timestamp", validate_slot_record(record))

    def test_rejects_impossible_calendar_slot(self):
        record = pending_record()
        record["slot_id"] = "2026-99-99T10:17:00Z"
        self.assertIn("slot_id must be a real UTC :17 or :47 calendar timestamp", validate_slot_record(record))

    def test_rejects_other_workflow_identity(self):
        record = pending_record()
        record["workflow_id"] = 12345
        errors = validate_slot_record(record)
        self.assertIn("workflow_id must match the designated distributed-loop workflow", errors)

    def test_rejects_idempotency_key_mismatch(self):
        record = pending_record()
        record["idempotency_key"] = "0" * 64
        self.assertIn("idempotency_key does not match workflow_id and slot_id", validate_slot_record(record))

    def test_rejects_boolean_workflow_id_and_attempt(self):
        record = pending_record()
        record["workflow_id"] = True
        record["attempt"] = False
        errors = validate_slot_record(record)
        self.assertIn("workflow_id must match the designated distributed-loop workflow", errors)
        self.assertIn("attempt must be a non-negative integer", errors)

    def test_claimed_requires_explicit_lease(self):
        record = pending_record()
        record.update(status="CLAIMED", attempt=1)
        self.assertIn("CLAIMED records require a lease object", validate_slot_record(record))

    def test_claimed_rejects_non_positive_lease_window(self):
        record = pending_record()
        record.update(status="CLAIMED", attempt=1, lease={
            "owner": "worker-a", "run_id": "123",
            "acquired_at": "2026-11-19T10:20:00Z",
            "expires_at": "2026-11-19T10:20:00Z",
        })
        self.assertIn("lease expires_at must be later than acquired_at", validate_slot_record(record))

    def test_completed_requires_verified_evidence(self):
        record = pending_record()
        record.update(status="COMPLETED", attempt=1, completion_evidence={
            "verified": False, "task_id": "task-1",
            "completed_at": "2026-11-19T10:22:00Z", "evidence_sha": "a" * 40,
        })
        self.assertIn("completion evidence must be explicitly verified", validate_slot_record(record))

    def test_valid_completed_record_requires_task_and_sha(self):
        record = pending_record()
        record.update(status="COMPLETED", attempt=1, completion_evidence={
            "verified": True, "task_id": "task-1",
            "completed_at": "2026-11-19T10:22:00Z", "evidence_sha": "a" * 40,
        })
        self.assertEqual(validate_slot_record(record), [])

    def test_failed_requires_reason(self):
        record = pending_record()
        record.update(status="FAILED", attempt=1)
        self.assertIn("FAILED records require failure_reason", validate_slot_record(record))

    def test_allowed_forward_transitions_are_bounded(self):
        self.assertTrue(transition_decision("PENDING", "CLAIMED")["allowed"])
        self.assertTrue(transition_decision("CLAIMED", "COMPLETED")["allowed"])
        self.assertTrue(transition_decision("CLAIMED", "FAILED")["allowed"])
        self.assertTrue(transition_decision("CLAIMED", "HELD")["allowed"])

    def test_failed_retry_and_terminal_reopen_are_blocked(self):
        retry = transition_decision("FAILED", "PENDING")
        reopen = transition_decision("COMPLETED", "CLAIMED")
        self.assertFalse(retry["allowed"])
        self.assertEqual(retry["reason"], "retry_requires_separate_human_review")
        self.assertFalse(reopen["allowed"])
        self.assertEqual(reopen["reason"], "terminal_state_no_automatic_transition")

    def test_lease_renewal_and_unknown_states_are_blocked(self):
        renewal = transition_decision("CLAIMED", "CLAIMED")
        unknown = transition_decision("UNKNOWN", "CLAIMED")
        malformed = transition_decision([], "CLAIMED")
        bad_record = pending_record()
        bad_record["status"] = []
        self.assertTrue(validate_slot_record(bad_record))
        self.assertFalse(malformed["allowed"])
        self.assertFalse(renewal["allowed"])
        self.assertEqual(renewal["reason"], "lease_renewal_not_implemented")
        self.assertFalse(unknown["allowed"])
        self.assertEqual(unknown["reason"], "unknown_lifecycle_state")


if __name__ == "__main__":
    unittest.main()
