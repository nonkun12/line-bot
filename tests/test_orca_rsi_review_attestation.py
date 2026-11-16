import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest

from scripts.orca_rsi_review_attestation import (
    ReviewAttestationRejected,
    verify_independent_review,
)


KEY = "test-review-key-that-is-at-least-32-bytes"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


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
    }
    value.update(overrides)
    canonical = {key: item for key, item in value.items() if key != "signature"}
    value["signature"] = hmac.new(
        KEY.encode(), json.dumps(
            canonical, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode(), hashlib.sha256,
    ).hexdigest()
    return value


def _verify(attestation=None, **kwargs):
    return verify_independent_review(
        attestation or _attestation(), KEY,
        repository="nonkun12/line-bot", cycle_id="a" * 64,
        commit_sha="b" * 40, now=NOW,
        allowed_reviewers=["trusted-reviewer"], **kwargs,
    )


def test_verifies_signed_fresh_commit_bound_independent_review():
    result = _verify()
    assert result["verdict"] == "PASS"
    assert result["evidence_refs"] == ["actions://review/123"]


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
    stale = _attestation(reviewed_at="2026-11-16T11:00:00+00:00")
    with pytest.raises(ReviewAttestationRejected, match="review_attestation_expired"):
        _verify(stale)


def test_rejects_missing_external_signing_key():
    with pytest.raises(ReviewAttestationRejected, match="review_verification_key_missing"):
        verify_independent_review(
            _attestation(), "short", repository="nonkun12/line-bot",
            cycle_id="a" * 64, commit_sha="b" * 40, now=NOW,
            allowed_reviewers=["trusted-reviewer"],
        )
