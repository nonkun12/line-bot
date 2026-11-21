import base64
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_five_stage import RSI_STAGES, new_cycle, record_stage
from scripts.orca_rsi_orca_adapter import RSIExecutionAdapterRejected, to_orca_improvement_candidate

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
NONCE = "one-time-challenge-nonce-123456"
CYCLE_ID = "a" * 64
COMMIT = "b" * 40
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC_PEM = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


def _attestation(**overrides):
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


def _cycle(cycle_id=CYCLE_ID):
    value = new_cycle(cycle_id)
    for stage in RSI_STAGES[:-1]:
        value = record_stage(value, stage=stage, evidence=f"{stage} evidence")
    return record_stage(value, stage="select_evolve", evidence="final evaluation", result="PASS")


def _candidate(**overrides):
    values = {
        "cycle_id": CYCLE_ID, "repository": "nonkun12/line-bot",
        "commit_sha": COMMIT, "review_attestation": _attestation(),
        "review_public_key_pem": PUBLIC_PEM, "expected_nonce": NONCE,
        "used_attestation_hashes": [], "allowed_reviewers": ["trusted-reviewer"],
        "public_key_reviewer_id": "trusted-reviewer", "implementer_id": "worker-author",
        "now": NOW, "evaluation": {"tests_passed": True, "critic_verdict": "pass"},
    }
    values.update(overrides)
    return to_orca_improvement_candidate(_cycle(), **values)


def test_adapter_maps_only_with_verified_ed25519_review():
    candidate = _candidate()
    assert candidate["evidence"]["reviewed"] == ["actions://review/123"]
    assert candidate["execution_authorized"] is False
    assert candidate["auto_apply"] is False
    assert candidate["auto_merge"] is False
    assert candidate["auto_deploy"] is False


def test_adapter_rejects_cycle_id_mismatch_between_argument_and_cycle():
    with pytest.raises(RSIExecutionAdapterRejected, match="rsi_cycle_id_mismatch"):
        to_orca_improvement_candidate(_cycle("c" * 64), **{
            key: value for key, value in {
                "cycle_id": CYCLE_ID, "repository": "nonkun12/line-bot",
                "commit_sha": COMMIT, "review_attestation": _attestation(),
                "review_public_key_pem": PUBLIC_PEM, "expected_nonce": NONCE,
                "used_attestation_hashes": [], "allowed_reviewers": ["trusted-reviewer"],
                "public_key_reviewer_id": "trusted-reviewer", "implementer_id": "worker-author",
                "now": NOW, "evaluation": {},
            }.items()
        })


def test_adapter_rejects_replayed_review():
    first = _candidate()
    with pytest.raises(RSIExecutionAdapterRejected, match="review_attestation_replayed"):
        _candidate(used_attestation_hashes=[first["review_attestation_hash"]])


def test_adapter_rejects_tampered_review():
    forged = _attestation()
    forged["evidence_refs"] = ["actions://forged"]
    with pytest.raises(RSIExecutionAdapterRejected, match="review_signature_invalid"):
        _candidate(review_attestation=forged)
