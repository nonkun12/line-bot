import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_trust_claims import (
    TrustClaimRejected,
    verify_budget_authorization,
    verify_task_approval,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
KEYRING = {"approval-key-v1": PUBLIC, "budget-key-v1": PUBLIC}
REPO = "nonkun12/line-bot"
TASK = "task-001"
TASK_DIGEST = "a" * 64
CYCLE = "b" * 64
COMMIT = "c" * 40
NONCE = "d" * 32


def _sign(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode()
    signed = dict(value)
    signed["signature"] = base64.b64encode(PRIVATE.sign(raw)).decode()
    return signed


def _approval(**overrides):
    value = {
        "claim_type": "orca_rsi_task_approval",
        "schema_version": 1,
        "key_id": "approval-key-v1",
        "repository": REPO,
        "task_id": TASK,
        "task_digest": TASK_DIGEST,
        "cycle_id": CYCLE,
        "commit_sha": COMMIT,
        "approver_id": "human-approver",
        "verdict": "APPROVED",
        "nonce": NONCE,
        "issued_at": "2026-11-16T11:59:00Z",
        "expires_at": "2026-11-16T12:05:00Z",
    }
    value.update(overrides)
    return _sign(value)


def _verify_approval(claim=None, **overrides):
    args = {
        "keyring": KEYRING,
        "allowed_approvers": ["human-approver"],
        "repository": REPO,
        "task_id": TASK,
        "task_digest": TASK_DIGEST,
        "cycle_id": CYCLE,
        "commit_sha": COMMIT,
        "now": NOW,
        "implementer_id": "worker-author",
    }
    args.update(overrides)
    return verify_task_approval(claim or _approval(), **args)


def _budget(evidence):
    refs = ["collector://bundle/42"]
    bundle = (
        len(refs[0].encode()).to_bytes(4, "big") + refs[0].encode()
        + len(evidence).to_bytes(8, "big") + evidence
    )
    value = {
        "claim_type": "orca_rsi_budget_authorization",
        "schema_version": 1,
        "key_id": "budget-key-v1",
        "repository": REPO,
        "task_id": TASK,
        "task_digest": TASK_DIGEST,
        "cycle_id": CYCLE,
        "commit_sha": COMMIT,
        "issuer_id": "budget-authority",
        "budget_unit": "github_actions_minutes",
        "authorized_limit_units": 100,
        "observed_spend_units": 20,
        "remaining_units": 80,
        "evidence_refs": refs,
        "evidence_sha256": hashlib.sha256(bundle).hexdigest(),
        "nonce": "e" * 32,
        "issued_at": "2026-11-16T11:59:00Z",
        "expires_at": "2026-11-16T12:04:00Z",
    }
    return _sign(value)


def _verify_budget(claim=None, **overrides):
    evidence = b"trusted collector evidence v1"
    args = {
        "keyring": KEYRING,
        "allowed_issuers": ["budget-authority"],
        "repository": REPO,
        "task_id": TASK,
        "task_digest": TASK_DIGEST,
        "cycle_id": CYCLE,
        "commit_sha": COMMIT,
        "now": NOW,
        "expected_budget_unit": "github_actions_minutes",
        "resolved_evidence": {"collector://bundle/42": evidence},
    }
    args.update(overrides)
    return verify_budget_authorization(claim or _budget(evidence), **args)


def test_valid_task_approval_is_bound_to_task_digest_and_commit():
    result = _verify_approval()
    assert result.claim_type == "orca_rsi_task_approval"
    assert result.signer_id == "human-approver"
    assert result.task_digest == TASK_DIGEST
    assert len(result.claim_hash) == 64


@pytest.mark.parametrize("field,value,error", [
    ("repository", "attacker/repo", "repository_mismatch"),
    ("task_id", "other-task", "task_id_mismatch"),
    ("task_digest", "f" * 64, "task_digest_mismatch"),
    ("cycle_id", "f" * 64, "cycle_id_mismatch"),
    ("commit_sha", "f" * 40, "commit_sha_mismatch"),
    ("verdict", "REJECTED", "task_approval_not_approved"),
    ("schema_version", True, "claim_schema_invalid"),
])
def test_task_approval_rejects_wrong_binding_or_claim(field, value, error):
    with pytest.raises(TrustClaimRejected, match=error):
        _verify_approval(_approval(**{field: value}))


def test_task_approval_rejects_self_approval():
    with pytest.raises(TrustClaimRejected, match="task_self_approval_forbidden"):
        _verify_approval(implementer_id="human-approver")


def test_task_approval_rejects_expired_claim():
    with pytest.raises(TrustClaimRejected, match="claim_expired"):
        _verify_approval(_approval(
            expires_at="2026-11-16T11:59:59Z",
            issued_at="2026-11-16T11:55:00Z",
        ))


def test_task_approval_rejects_tampering_and_unknown_fields():
    claim = _approval()
    claim["task_id"] = "forged-task"
    with pytest.raises(TrustClaimRejected, match="claim_signature_invalid"):
        _verify_approval(claim)
    claim = _approval()
    claim["unrecognized"] = "value"
    with pytest.raises(TrustClaimRejected, match="claim_fields_mismatch"):
        _verify_approval(claim)


def test_task_approval_rejects_untrusted_signer_and_key():
    with pytest.raises(TrustClaimRejected, match="claim_signer_not_allowlisted"):
        _verify_approval(allowed_approvers=["someone-else"])
    with pytest.raises(TrustClaimRejected, match="claim_key_id_not_allowlisted"):
        _verify_approval(_approval(key_id="unknown-key"))


def test_valid_budget_claim_requires_retrieved_matching_evidence():
    result = _verify_budget()
    assert result.claim_type == "orca_rsi_budget_authorization"
    assert result.signer_id == "budget-authority"


@pytest.mark.parametrize("field,value,error", [
    ("authorized_limit_units", True, "budget_values_must_be_integers"),
    ("observed_spend_units", 1.5, "budget_values_must_be_integers"),
    ("remaining_units", -1, "budget_values_out_of_range"),
    ("authorized_limit_units", 10, "budget_limit_exceeded"),
    ("budget_unit", "usd", "budget_unit_mismatch"),
])
def test_budget_claim_rejects_invalid_limits_or_units(field, value, error):
    evidence = b"trusted collector evidence v1"
    with pytest.raises(TrustClaimRejected, match=error):
        _verify_budget(_budget(evidence, **{field: value}))


def test_budget_claim_rejects_missing_or_modified_evidence():
    claim = _budget(b"trusted collector evidence v1")
    with pytest.raises(TrustClaimRejected, match="budget_evidence_unavailable"):
        _verify_budget(claim, resolved_evidence=None)
    with pytest.raises(TrustClaimRejected, match="budget_evidence_digest_mismatch"):
        _verify_budget(claim, resolved_evidence={"collector://bundle/42": b"modified"})


def test_budget_claim_rejects_wrong_signer_and_expired_claim():
    evidence = b"trusted collector evidence v1"
    with pytest.raises(TrustClaimRejected, match="claim_signer_not_allowlisted"):
        _verify_budget(allowed_issuers=["untrusted"])
    with pytest.raises(TrustClaimRejected, match="claim_expired"):
        _verify_budget(_budget(
            evidence,
            issued_at="2026-11-16T11:50:00Z",
            expires_at="2026-11-16T11:59:59Z",
        ))


def test_budget_claim_rejects_tampered_signature():
    claim = _budget(b"trusted collector evidence v1")
    claim["remaining_units"] = 79
    with pytest.raises(TrustClaimRejected, match="claim_signature_invalid"):
        _verify_budget(claim)
