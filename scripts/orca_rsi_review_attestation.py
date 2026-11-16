"""Verifier for externally signed independent-review attestations.

The signing key must be held by a reviewer service distinct from the worker.
This module verifies attestations; it does not create signatures or call a
review model. The attestation is bound to repository, cycle, and commit.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_AGE = timedelta(minutes=15)
_MAX_FUTURE_SKEW = timedelta(minutes=2)


class ReviewAttestationRejected(ValueError):
    """Raised when independent review provenance cannot be verified."""


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReviewAttestationRejected("review_timestamp_missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReviewAttestationRejected("review_timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise ReviewAttestationRejected("review_timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _canonical(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    try:
        return json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise ReviewAttestationRejected("review_payload_not_canonical") from None


def verify_independent_review(
    attestation: Any,
    signing_key: str,
    *,
    repository: str,
    cycle_id: str,
    commit_sha: str,
    now: datetime,
    allowed_reviewers: Iterable[str],
) -> dict[str, Any]:
    """Verify a fresh HMAC-signed PASS attestation from an allowlisted reviewer."""
    if not isinstance(attestation, dict):
        raise ReviewAttestationRejected("review_attestation_missing")
    if not isinstance(signing_key, str) or len(signing_key.encode("utf-8")) < 32:
        raise ReviewAttestationRejected("review_verification_key_missing")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ReviewAttestationRejected("review_verification_time_invalid")
    if not isinstance(repository, str) or "/" not in repository:
        raise ReviewAttestationRejected("review_repository_invalid")
    if not isinstance(cycle_id, str) or not _HEX_64.fullmatch(cycle_id):
        raise ReviewAttestationRejected("review_cycle_id_invalid")
    if not isinstance(commit_sha, str) or not _HEX_40.fullmatch(commit_sha):
        raise ReviewAttestationRejected("review_commit_sha_invalid")
    if attestation.get("schema_version") != 1:
        raise ReviewAttestationRejected("review_schema_invalid")
    if attestation.get("repository") != repository:
        raise ReviewAttestationRejected("review_repository_mismatch")
    if attestation.get("cycle_id") != cycle_id:
        raise ReviewAttestationRejected("review_cycle_mismatch")
    if attestation.get("commit_sha") != commit_sha:
        raise ReviewAttestationRejected("review_commit_mismatch")

    try:
        reviewers = set(allowed_reviewers)
    except (TypeError, ValueError):
        raise ReviewAttestationRejected("reviewer_allowlist_invalid") from None
    if not reviewers or any(not isinstance(item, str) or not item for item in reviewers):
        raise ReviewAttestationRejected("reviewer_allowlist_invalid")
    reviewer = attestation.get("reviewer_id")
    if not isinstance(reviewer, str) or reviewer not in reviewers:
        raise ReviewAttestationRejected("reviewer_not_allowlisted")
    if attestation.get("verdict") != "PASS":
        raise ReviewAttestationRejected("independent_review_not_pass")

    refs = attestation.get("evidence_refs")
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(item, str) or not item.strip() for item in refs)):
        raise ReviewAttestationRejected("review_evidence_refs_invalid")
    signature = attestation.get("signature")
    if not isinstance(signature, str) or not _HEX_64.fullmatch(signature):
        raise ReviewAttestationRejected("review_signature_missing_or_invalid")
    expected = hmac.new(
        signing_key.encode("utf-8"), _canonical(attestation), hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ReviewAttestationRejected("review_signature_invalid")

    current = now.astimezone(timezone.utc)
    reviewed_at = _timestamp(attestation.get("reviewed_at"))
    if reviewed_at > current + _MAX_FUTURE_SKEW:
        raise ReviewAttestationRejected("review_timestamp_in_future")
    if current - reviewed_at > _MAX_AGE:
        raise ReviewAttestationRejected("review_attestation_expired")
    return {
        "reviewer_id": reviewer,
        "verdict": "PASS",
        "evidence_refs": list(refs),
        "reviewed_at": reviewed_at.isoformat(),
        "commit_sha": commit_sha,
        "cycle_id": cycle_id,
    }
