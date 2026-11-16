from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import copy
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_five_stage import (
    RSI_STAGES, RSICycleRejected, continuation_decision, new_cycle, record_stage,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
NONCE = "one-time-challenge-nonce-123456"
CYCLE_ID = "a" * 64
COMMIT = "b" * 40
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC_PEM = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


@dataclass
class Snapshot:
    ref_sha: str
    state: dict


class FakeCASStore:
    def __init__(self):
        self.snapshot = Snapshot("c" * 40, {
            "schema_version": 1, "revision": 3, "global_hold": False,
            "emergency_stop": False, "tasks": [{"task_id": "task-1", "status": "queued"}],
            "active_lease": None,
            "consumed_approval_ids": [],
            "rsi_review_replay": {"used_nonces": [], "used_attestation_hashes": []},
        })
        self.writes = 0
        self.conflict = False

    def write(self, *, snapshot, next_state, expected_revision):
        self.writes += 1
        if self.conflict or snapshot.ref_sha != self.snapshot.ref_sha:
            raise RuntimeError("github_ref_fast_forward_conflict")
        if expected_revision != self.snapshot.state["revision"]:
            raise RuntimeError("stale_state_revision")
        self.snapshot = Snapshot("d" * 40, copy.deepcopy(next_state))
        return self.snapshot


def _complete_cycle(result="PASS"):
    cycle = new_cycle(CYCLE_ID)
    for stage in RSI_STAGES[:-1]:
        cycle = record_stage(cycle, stage=stage, evidence=f"{stage} evidence")
    return record_stage(cycle, stage="select_evolve", evidence="decision evidence", result=result)


def _signed_review(**overrides):
    value = {
        "schema_version": 1, "repository": "nonkun12/line-bot",
        "cycle_id": CYCLE_ID, "commit_sha": COMMIT,
        "reviewer_id": "trusted-reviewer", "verdict": "PASS",
        "evidence_refs": ["actions://review/123"], "reviewed_at": NOW.isoformat(),
        "nonce": NONCE,
    }
    value.update(overrides)
    value["signature"] = base64.b64encode(PRIVATE.sign(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode())).decode()
    return value


def _gates(store=None, **overrides):
    store = store or FakeCASStore()
    values = {
        "budget_verified": True, "approval_verified": True,
        "independent_review_attestation": _signed_review(),
        "review_public_key_pem": PUBLIC_PEM, "review_nonce": NONCE,
        "replay_store": store, "replay_snapshot": store.snapshot,
        "repository": "nonkun12/line-bot",
        "allowed_reviewers": ["trusted-reviewer"], "public_key_reviewer_id": "trusted-reviewer", "implementer_id": "worker-author", "now": NOW,
        "expected_commit_sha": COMMIT, "kill_switch": False,
    }
    values.update(overrides)
    return store, values


def test_five_rsi_stages_complete_in_order():
    cycle = _complete_cycle()
    assert cycle["completed_stages"] == list(RSI_STAGES)
    assert cycle["result"] == "PASS"
    assert len(cycle["evidence"]) == 5


def test_rsi_rejects_skipped_stage():
    try:
        record_stage(new_cycle("f" * 64), stage="diagnose", evidence="diagnosis")
    except RSICycleRejected as exc:
        assert str(exc) == "rsi_stage_out_of_order"
    else:
        raise AssertionError("out-of-order stage was accepted")


def test_rsi_rejects_empty_evidence():
    try:
        record_stage(new_cycle("e" * 64), stage="evaluate", evidence=" ")
    except RSICycleRejected as exc:
        assert str(exc) == "rsi_stage_evidence_missing_or_invalid"
    else:
        raise AssertionError("empty evidence was accepted")


def test_only_signed_and_durably_consumed_review_can_continue():
    store, gates = _gates()
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is True
    assert decision["next_cycle_limit"] == 1
    assert decision["review_replay_status"] == "REVIEW_CONSUMED"
    assert decision["execution_started"] is False
    assert store.writes == 1
    assert store.snapshot.state["revision"] == 4


def test_raw_boolean_cannot_satisfy_independent_review_gate():
    store, gates = _gates(independent_review_attestation=True)
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is False
    assert "independent_review_rejected:review_attestation_missing" in decision["reasons"]
    assert store.writes == 0


def test_review_for_another_cycle_or_commit_is_rejected():
    store, gates = _gates(independent_review_attestation=_signed_review(cycle_id="c" * 64))
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is False
    assert any("review_cycle_mismatch" in reason for reason in decision["reasons"])
    assert store.writes == 0

    store, gates = _gates(independent_review_attestation=_signed_review(commit_sha="d" * 40))
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is False
    assert any("review_commit_mismatch" in reason for reason in decision["reasons"])
    assert store.writes == 0


def test_hold_or_missing_budget_blocks_without_consuming_review():
    store, gates = _gates(budget_verified=False)
    store.snapshot.state["global_hold"] = True
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is False
    assert "global_hold_active" in decision["reasons"]
    assert "budget_evidence_missing_or_invalid" in decision["reasons"]
    assert store.writes == 0


def test_no_change_does_not_consume_or_continue():
    store, gates = _gates()
    decision = continuation_decision(_complete_cycle("NO_CHANGE"), **gates)
    assert decision["continue"] is False
    assert "rsi_result_not_pass" in decision["reasons"]
    assert store.writes == 0


def test_replayed_review_is_rejected_by_durable_gate():
    store, gates = _gates()
    first = continuation_decision(_complete_cycle(), **gates)
    assert first["continue"] is True
    # The persisted state from the first pass is the only accepted next snapshot.
    store2, gates2 = _gates(store)
    gates2["replay_snapshot"] = store.snapshot
    second = continuation_decision(_complete_cycle(), **gates2)
    assert second["continue"] is False
    assert any("review_nonce_replayed" in reason for reason in second["reasons"])


def test_truthy_strings_cannot_satisfy_safety_gates():
    store, gates = _gates(budget_verified="true")
    decision = continuation_decision(_complete_cycle(), **gates)
    assert "gate_input_not_boolean" in decision["reasons"]
    assert store.writes == 0


def test_boolean_schema_version_is_rejected():
    store, gates = _gates()
    bad = _complete_cycle()
    bad["schema_version"] = True
    decision = continuation_decision(bad, **gates)
    assert decision["continue"] is False
    assert store.writes == 0


def test_cas_conflict_fails_closed_without_retry():
    store, gates = _gates()
    store.conflict = True
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is False
    assert any("review_replay_persistence_failed" in reason for reason in decision["reasons"])
    assert store.writes == 1


def test_missing_review_replay_ledger_fails_closed_without_initializing_it():
    store, gates = _gates()
    del store.snapshot.state["rsi_review_replay"]
    decision = continuation_decision(_complete_cycle(), **gates)
    assert decision["continue"] is False
    assert any("review_replay_ledger_missing" in reason for reason in decision["reasons"])
    assert store.writes == 0
    assert "rsi_review_replay" not in store.snapshot.state
