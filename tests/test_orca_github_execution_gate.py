import hashlib
import hmac
import json
import math
import unittest
from datetime import datetime, timezone

from scripts.orca_github_execution_gate import (
    ExecutionGateRejected, evaluate_execution_gate,
)

NOW = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
REPO = "nonkun12/line-bot"
TASK_ID = "task-1"
REQUEST_HASH = "a" * 64
APPROVAL_KEY = "approval-signing-key-long-enough-for-hmac"
BUDGET_KEY = "budget-signing-key-long-enough-for-hmac"
ACCOUNT = "billing-account-1"


def signed(payload, key):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode()
    return dict(payload, signature=hmac.new(key.encode(), raw, hashlib.sha256).hexdigest())


def approval():
    return signed({
        "schema_version": 1,
        "approval_id": "b" * 64,
        "repository": REPO,
        "task_id": TASK_ID,
        "request_hash": REQUEST_HASH,
        "approved_by": "human-owner",
        "decision": "approve",
        "approved_at": "2026-11-13T10:00:00Z",
        "expires_at": "2026-11-13T10:10:00Z",
    }, APPROVAL_KEY)


def budget():
    source = {
        "name": "github_actions", "enabled": True, "used": 100, "limit": 2000,
        "unit": "minutes", "source_api": "trusted-account-collector",
        "limit_source": "verified_plan_included_minutes",
        "limit_evidence_id": "plan-evidence-1", "quality": "exact",
        "coverage_complete": True, "exact_counter": True, "sampling_mode": "none",
        "resource_count": 1,
        "resource_digest": hashlib.sha256(b"account-runners").hexdigest(),
        "source_watermark_at": "2026-11-13T10:00:00Z",
    }
    return signed({
        "schema_version": 1, "collector_id": "orca-github-actions-budget-collector",
        "repository": REPO, "billing_account_id": ACCOUNT,
        "observed_at": "2026-11-13T10:00:00Z",
        "period_start": "2026-11-01T00:00:00Z",
        "period_end": "2026-12-01T00:00:00Z",
        "consecutive_failures": 0, "sources": [source],
    }, BUDGET_KEY)


def cycle():
    return {
        "schema_version": 1, "cycle_id": "c" * 64,
        "stage": "evaluated", "decision": "accepted_candidate",
        "execution_authorized": False, "auto_apply": False,
        "auto_merge": False, "auto_deploy": False,
        "evidence": {stage: [f"evidence:{stage}"] for stage in
                    ("observed", "diagnosed", "proposed", "tested", "reviewed", "evaluated")},
        "details": {"evaluation": {
            "baseline_metric": 1.0, "candidate_metric": 2.0,
            "tests_passed": True, "critic_verdict": "pass",
        }},
    }


def queue():
    return {
        "schema_version": 1, "revision": 4, "global_hold": False,
        "tasks": [{
            "task_id": TASK_ID, "request_hash": REQUEST_HASH,
            "status": "queued", "created_at": "2026-11-13T09:00:00Z",
        }],
        "active_lease": None, "consumed_approval_ids": [],
    }


class ExecutionGateTests(unittest.TestCase):
    def evaluate(self, **overrides):
        args = {
            "repository": REPO, "queue_state": queue(),
            "task_id": TASK_ID, "request_hash": REQUEST_HASH,
            "approval": approval(), "approval_signing_key": APPROVAL_KEY,
            "allowed_approvers": ["human-owner"], "consumed_approval_ids": [],
            "budget_evidence": budget(), "budget_signing_key": BUDGET_KEY,
            "billing_account_id": ACCOUNT, "improvement_cycle": cycle(),
            "now": NOW,
        }
        args.update(overrides)
        return evaluate_execution_gate(**args)

    def test_all_verified_gates_pass_but_do_not_enable_execution(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["execution_enabled"])
        self.assertEqual(result["max_tasks_per_run"], 1)
        self.assertEqual(result["required_next_action"],
                         "persist_approval_replay_marker_before_worker_claim")

    def test_global_hold_blocks(self):
        state = queue()
        state["global_hold"] = True
        with self.assertRaisesRegex(ExecutionGateRejected, "global_hold"):
            self.evaluate(queue_state=state)

    def test_missing_or_unverifiable_hold_blocks(self):
        state = queue()
        del state["global_hold"]
        with self.assertRaisesRegex(ExecutionGateRejected, "global_hold"):
            self.evaluate(queue_state=state)

    def test_active_lease_blocks_second_worker(self):
        state = queue()
        state["active_lease"] = {"task_id": TASK_ID}
        with self.assertRaisesRegex(ExecutionGateRejected, "active_lease_present"):
            self.evaluate(queue_state=state)

    def test_task_hash_mismatch_blocks(self):
        with self.assertRaisesRegex(ExecutionGateRejected, "request_hash_mismatch"):
            self.evaluate(request_hash="d" * 64)

    def test_forged_approval_signature_blocks(self):
        proof = approval()
        proof["approved_by"] = "attacker"
        with self.assertRaisesRegex(ExecutionGateRejected, "approver_not_allowed"):
            self.evaluate(approval=proof)

    def test_invalid_approval_signature_blocks(self):
        proof = approval()
        proof["signature"] = "0" * 64
        with self.assertRaisesRegex(ExecutionGateRejected, "signature_invalid"):
            self.evaluate(approval=proof)

    def test_replayed_approval_blocks(self):
        with self.assertRaisesRegex(ExecutionGateRejected, "approval_replay_detected"):
            self.evaluate(consumed_approval_ids=["b" * 64])

    def test_missing_budget_evidence_blocks(self):
        with self.assertRaisesRegex(ExecutionGateRejected, "budget_gate_blocked"):
            self.evaluate(budget_evidence=None)

    def test_unsafe_improvement_cycle_blocks(self):
        candidate = cycle()
        candidate["auto_apply"] = True
        with self.assertRaisesRegex(ExecutionGateRejected, "unsafe_improvement"):
            self.evaluate(improvement_cycle=candidate)

    def test_missing_improvement_stage_evidence_blocks(self):
        candidate = cycle()
        del candidate["evidence"]["diagnosed"]
        with self.assertRaisesRegex(ExecutionGateRejected, "stage_evidence_missing"):
            self.evaluate(improvement_cycle=candidate)

    def test_non_finite_improvement_metric_blocks(self):
        candidate = cycle()
        candidate["details"]["evaluation"]["candidate_metric"] = math.nan
        with self.assertRaisesRegex(ExecutionGateRejected, "metric_not_positive"):
            self.evaluate(improvement_cycle=candidate)

    def test_unapproved_identity_blocks(self):
        with self.assertRaisesRegex(ExecutionGateRejected, "approver_not_allowed"):
            self.evaluate(allowed_approvers=["different-owner"])


    def test_missing_active_lease_field_blocks(self):
        state = queue()
        del state["active_lease"]
        with self.assertRaisesRegex(ExecutionGateRejected, "queue_tasks_or_lease_missing"):
            self.evaluate(queue_state=state)

    def test_empty_approver_allowlist_blocks(self):
        with self.assertRaisesRegex(ExecutionGateRejected, "approver_allowlist_invalid"):
            self.evaluate(allowed_approvers=[])


    def test_replay_ledger_must_match_immutable_queue_snapshot(self):
        with self.assertRaisesRegex(ExecutionGateRejected, "ledger_snapshot_mismatch"):
            self.evaluate(consumed_approval_ids=["d" * 64])


if __name__ == "__main__":
    unittest.main()
