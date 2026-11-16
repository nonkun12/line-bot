import base64
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.orca_rsi_review_attestation import (
    ReviewAttestationRejected,
    verify_independent_review,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
NONCE = "one-time-challenge-nonce-123456"
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC_PEM = PRIVATE.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


def _attestation(**overrides):
    value = {
        "schema_version": 1,
        "repository": "nonkun12/line-bot",
        "cycle_id": "a" * 64,
        "commit_sha": "b" * 40,
        "reviewer_id": "trusted-reviewer",
        "verdict": "PASS",
        "evidence_refs": ["actions://review/123"],
        "reviewed_at": NOW.isoformat(),
        "nonce": NONCE,
    }
    value.update(overrides)
    import json
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    value["signature"] = base64.b64encode(PRIVATE.sign(canonical)).decode()
    return value


def _verify(attestation=None, **kwargs):
    return verify_independent_review(
        attestation or _attestation(), PUBLIC_PEM,
        repository="nonkun12/line-bot", cycle_id="a" * 64,
        commit_sha="b" * 40, expected_nonce=NONCE,
        used_attestation_hashes=[], now=NOW,
        allowed_reviewers=["trusted-reviewer"], **kwargs,
    )


def test_verifies_ed25519_signed_fresh_review_without_private_key():
    result = _verify()
    assert result.verdict == "PASS"
    assert result.evidence_refs == ("actions://review/123",)
    assert len(result.attestation_hash) == 64


@pytest.mark.parametrize("field,value,error", [
    ("repository", "attacker/repo", "review_repository_mismatch"),
    ("cycle_id", "c" * 64, "review_cycle_mismatch"),
    ("commit_sha", "d" * 40, "review_commit_mismatch"),
    ("reviewer_id", "untrusted", "reviewer_not_allowlisted"),
    ("verdict", "FAIL", "independent_review_not_pass"),
])
def test_rejects_wrong_review_identity_or_verdict(field, value, error):
    with pytest.raises(ReviewAttestationRejected, match=error):
        _verify(_attestation(**{field: value}))


def test_rejects_tampered_signature():
    value = _attestation()
    value["evidence_refs"] = ["actions://forged"]
    with pytest.raises(ReviewAttestationRejected, match="review_signature_invalid"):
        _verify(value)


def test_rejects_stale_attestation():
    with pytest.raises(ReviewAttestationRejected, match="review_attestation_expired"):
        _verify(_attestation(reviewed_at="2026-11-16T11:00:00+00:00"))


def test_rejects_nonce_mismatch():
    with pytest.raises(ReviewAttestationRejected, match="review_nonce_mismatch"):
        _verify(_attestation(nonce="different-one-time-challenge"))


def test_rejects_replayed_attestation_hash():
    result = _verify()
    with pytest.raises(ReviewAttestationRejected, match="review_attestation_replayed"):
        _verify(used_attestation_hashes=[result.attestation_hash])


def test_rejects_string_allowlist():
    with pytest.raises(ReviewAttestationRejected, match="reviewer_allowlist_invalid"):
        _verify(allowed_reviewers="trusted-reviewer")


def test_rejects_boolean_schema_version():
    with pytest.raises(ReviewAttestationRejected, match="review_schema_invalid"):
        _verify(_attestation(schema_version=True))


def test_rejects_wrong_key_type():
    with pytest.raises(ReviewAttestationRejected, match="review_public_key_wrong_type"):
        verify_independent_review(
            _attestation(), "not-an-ed25519-key", repository="nonkun12/line-bot",
            cycle_id="a" * 64, commit_sha="b" * 40, expected_nonce=NONCE,
            used_attestation_hashes=[], now=NOW,
            allowed_reviewers=["trusted-reviewer"],
        )
