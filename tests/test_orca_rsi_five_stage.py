from datetime import datetime, timezone
import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_five_stage import (
    RSI_STAGES, RSICycleRejected, continuation_decision, new_cycle, record_stage,
)
from scripts.orca_rsi_review_attestation import verify_independent_review

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
NONCE = "one-time-challenge-nonce-123456"
CYCLE_ID = "a" * 64
COMMIT = "b" * 40
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC_PEM = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


def _complete_cycle(result="PASS"):
    cycle = new_cycle(CYCLE_ID)
    for stage in RSI_STAGES[:-1]:
        cycle = record_stage(cycle, stage=stage, evidence=f"{stage} evidence")
    return record_stage(cycle, stage="select_evolve", evidence="decision evidence", result=result)


def _review():
    value = {
        "schema_version": 1, "repository": "nonkun12/line-bot",
        "cycle_id": CYCLE_ID, "commit_sha": COMMIT,
        "reviewer_id": "trusted-reviewer", "verdict": "PASS",
        "evidence_refs": ["actions://review/123"], "reviewed_at": NOW.isoformat(),
        "nonce": NONCE,
    }
    value["signature"] = base64.b64encode(PRIVATE.sign(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode())).decode()
    return verify_independent_review(
        value, PUBLIC_PEM, repository="nonkun12/line-bot", cycle_id=CYCLE_ID,
        commit_sha=COMMIT, expected_nonce=NONCE, used_attestation_hashes=[],
        now=NOW, allowed_reviewers=["trusted-reviewer"],
    )


def _gates(**overrides):
    values = {
        "queue_has_pending": True, "global_hold": False, "emergency_stop": False,
        "budget_verified": True, "approval_verified": True,
        "independent_review": _review(), "expected_commit_sha": COMMIT,
        "kill_switch": False,
    }
    values.update(overrides)
    return values


def test_five_rsi_stages_complete_in_order():
    cycle = _complete_cycle()
    assert cycle["completed_stages"] == list(RSI_STAGES)
    assert cycle["result"] == "PASS"
    assert len(cycle["evidence"]) == 5


def test_rsi_rejects_skipped_stage():
    try:
        record_stage(new_cycle("skip"), stage="diagnose", evidence="diagnosis")
    except RSICycleRejected as exc:
        assert str(exc) == "rsi_stage_out_of_order"
    else:
        raise AssertionError("out-of-order stage was accepted")


def test_rsi_rejects_empty_evidence():
    try:
        record_stage(new_cycle("empty"), stage="evaluate", evidence=" ")
    except RSICycleRejected as exc:
        assert str(exc) == "rsi_stage_evidence_missing_or_invalid"
    else:
        raise AssertionError("empty evidence was accepted")


def test_only_verified_review_bound_to_cycle_and_commit_can_continue():
    decision = continuation_decision(_complete_cycle(), **_gates())
    assert decision["continue"] is True
    assert decision["next_cycle_limit"] == 1


def test_hold_or_missing_budget_blocks_continuation():
    decision = continuation_decision(_complete_cycle(), **_gates(global_hold=True, budget_verified=False))
    assert decision["continue"] is False
    assert "global_hold_active" in decision["reasons"]
    assert "budget_evidence_missing_or_invalid" in decision["reasons"]


def test_no_change_does_not_continue():
    decision = continuation_decision(_complete_cycle("NO_CHANGE"), **_gates())
    assert decision["continue"] is False
    assert "rsi_result_not_pass" in decision["reasons"]


def test_raw_boolean_cannot_satisfy_independent_review_gate():
    decision = continuation_decision(_complete_cycle(), **_gates(independent_review=True))
    assert decision["continue"] is False
    assert "independent_review_not_verified" in decision["reasons"]


def test_review_from_another_cycle_or_commit_is_rejected():
    from dataclasses import replace
    wrong_cycle = replace(_review(), cycle_id="c" * 64)
    decision = continuation_decision(_complete_cycle(), **_gates(independent_review=wrong_cycle))
    assert "independent_review_cycle_mismatch" in decision["reasons"]
    wrong_commit = replace(_review(), commit_sha="d" * 40)
    decision = continuation_decision(_complete_cycle(), **_gates(independent_review=wrong_commit))
    assert "independent_review_commit_mismatch" in decision["reasons"]


def test_truthy_strings_cannot_satisfy_safety_gates():
    decision = continuation_decision(_complete_cycle(), **_gates(global_hold="false", budget_verified="true"))
    assert "gate_input_not_boolean" in decision["reasons"]


def test_boolean_schema_version_is_rejected():
    bad = _complete_cycle()
    bad["schema_version"] = True
    decision = continuation_decision(bad, **_gates())
    assert decision["continue"] is False
