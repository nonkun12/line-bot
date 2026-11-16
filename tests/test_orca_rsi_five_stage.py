from datetime import datetime, timezone
import base64
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
        {k: v for k, v in value.items() if k != "signature"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode())).decode()
    return value


def _gates(**overrides):
    values = {
        "queue_has_pending": True, "global_hold": False, "emergency_stop": False,
        "budget_verified": True, "approval_verified": True,
        "independent_review_attestation": _signed_review(),
        "review_public_key_pem": PUBLIC_PEM, "review_nonce": NONCE,
        "used_attestation_hashes": [], "repository": "nonkun12/line-bot",
        "allowed_reviewers": ["trusted-reviewer"], "now": NOW,
        "expected_commit_sha": COMMIT, "kill_switch": False,
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


def test_only_cryptographically_verified_review_can_continue():
    decision = continuation_decision(_complete_cycle(), **_gates())
    assert decision["continue"] is True
    assert decision["next_cycle_limit"] == 1


def test_raw_boolean_cannot_satisfy_independent_review_gate():
    decision = continuation_decision(_complete_cycle(), **_gates(independent_review_attestation=True))
    assert decision["continue"] is False
    assert any(reason.startswith("independent_review_rejected:review_attestation_missing")
               for reason in decision["reasons"])


def test_review_for_another_cycle_or_commit_is_rejected():
    decision = continuation_decision(
        _complete_cycle(), **_gates(independent_review_attestation=_signed_review(cycle_id="c" * 64))
    )
    assert any("review_cycle_mismatch" in reason for reason in decision["reasons"])
    decision = continuation_decision(
        _complete_cycle(), **_gates(independent_review_attestation=_signed_review(commit_sha="d" * 40))
    )
    assert any("review_commit_mismatch" in reason for reason in decision["reasons"])


def test_hold_or_missing_budget_blocks_continuation():
    decision = continuation_decision(_complete_cycle(), **_gates(global_hold=True, budget_verified=False))
    assert decision["continue"] is False
    assert "global_hold_active" in decision["reasons"]
    assert "budget_evidence_missing_or_invalid" in decision["reasons"]


def test_no_change_does_not_continue():
    decision = continuation_decision(_complete_cycle("NO_CHANGE"), **_gates())
    assert decision["continue"] is False
    assert "rsi_result_not_pass" in decision["reasons"]


def test_replayed_review_is_rejected_by_gate():
    from scripts.orca_rsi_review_attestation import verify_independent_review
    signed = _signed_review()
    first = verify_independent_review(
        signed, PUBLIC_PEM, repository="nonkun12/line-bot", cycle_id=CYCLE_ID,
        commit_sha=COMMIT, expected_nonce=NONCE, used_attestation_hashes=[],
        now=NOW, allowed_reviewers=["trusted-reviewer"],
    )
    decision = continuation_decision(
        _complete_cycle(), **_gates(used_attestation_hashes=[first.attestation_hash])
    )
    assert any("review_attestation_replayed" in reason for reason in decision["reasons"])


def test_truthy_strings_cannot_satisfy_safety_gates():
    decision = continuation_decision(_complete_cycle(), **_gates(global_hold="false", budget_verified="true"))
    assert "gate_input_not_boolean" in decision["reasons"]


def test_boolean_schema_version_is_rejected():
    bad = _complete_cycle()
    bad["schema_version"] = True
    decision = continuation_decision(bad, **_gates())
    assert decision["continue"] is False
