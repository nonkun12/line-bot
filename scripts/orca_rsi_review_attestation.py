"""Ed25519 verifier for independently signed review attestations.

The worker receives only the reviewer's public key. The private signing key
must remain in the independent reviewer service. Replay prevention is backed
by a caller-owned durable nonce/hash ledger: callers must atomically reserve
the challenge nonce and persist the returned attestation_hash before acting.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_AGE = timedelta(minutes=15)
_MAX_FUTURE_SKEW = timedelta(minutes=2)


class ReviewAttestationRejected(ValueError):
    """Raised when independent review provenance cannot be verified."""


@dataclass(frozen=True)
class VerifiedIndependentReview:
    """Verification result; bind it to the exact cycle and commit at the gate."""
    reviewer_id: str
    verdict: str
    evidence_refs: tuple[str, ...]
    reviewed_at: str
    commit_sha: str
    cycle_id: str
    nonce: str
    attestation_hash: str


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


def _load_public_key(value: Any) -> Ed25519PublicKey:
    if not isinstance(value, (str, bytes)):
        raise ReviewAttestationRejected("review_public_key_missing")
    try:
        raw = value.encode("utf-8") if isinstance(value, str) else value
        key = serialization.load_pem_public_key(raw)
    except (TypeError, ValueError):
        raise ReviewAttestationRejected("review_public_key_invalid") from None
    if not isinstance(key, Ed25519PublicKey):
        raise ReviewAttestationRejected("review_public_key_wrong_type")
    return key


def verify_independent_review(
    attestation: Any,
    public_key_pem: str | bytes,
    *,
    repository: str,
    cycle_id: str,
    commit_sha: str,
    expected_nonce: str,
    used_attestation_hashes: Iterable[str],
    now: datetime,
    allowed_reviewers: Iterable[str],
    public_key_reviewer_id: str,
    implementer_id: str,
) -> VerifiedIndependentReview:
    """Verify a fresh Ed25519 PASS attestation and reject previously used hashes."""
    if not isinstance(attestation, dict):
        raise ReviewAttestationRejected("review_attestation_missing")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ReviewAttestationRejected("review_verification_time_invalid")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ReviewAttestationRejected("review_repository_invalid")
    if not isinstance(cycle_id, str) or not _HEX_64.fullmatch(cycle_id):
        raise ReviewAttestationRejected("review_cycle_id_invalid")
    if not isinstance(commit_sha, str) or not _HEX_40.fullmatch(commit_sha):
        raise ReviewAttestationRejected("review_commit_sha_invalid")
    if type(attestation.get("schema_version")) is not int or attestation["schema_version"] != 1:
        raise ReviewAttestationRejected("review_schema_invalid")
    if attestation.get("repository") != repository:
        raise ReviewAttestationRejected("review_repository_mismatch")
    if attestation.get("cycle_id") != cycle_id:
        raise ReviewAttestationRejected("review_cycle_mismatch")
    if attestation.get("commit_sha") != commit_sha:
        raise ReviewAttestationRejected("review_commit_mismatch")
    if (not isinstance(expected_nonce, str) or len(expected_nonce) < 16
            or attestation.get("nonce") != expected_nonce):
        raise ReviewAttestationRejected("review_nonce_mismatch")

    if isinstance(allowed_reviewers, (str, bytes)):
        raise ReviewAttestationRejected("reviewer_allowlist_invalid")
    if not isinstance(allowed_reviewers, (list, tuple, set, frozenset)):
        raise ReviewAttestationRejected("reviewer_allowlist_invalid")
    try:
        reviewers = set(allowed_reviewers)
    except (TypeError, ValueError):
        raise ReviewAttestationRejected("reviewer_allowlist_invalid") from None
    if not reviewers or any(not isinstance(item, str) or not item for item in reviewers):
        raise ReviewAttestationRejected("reviewer_allowlist_invalid")
    reviewer = attestation.get("reviewer_id")
    if not isinstance(reviewer, str) or reviewer not in reviewers:
        raise ReviewAttestationRejected("reviewer_not_allowlisted")
    if (not isinstance(public_key_reviewer_id, str)
            or not public_key_reviewer_id.strip()):
        raise ReviewAttestationRejected("review_key_identity_binding_missing")
    if reviewer != public_key_reviewer_id:
        raise ReviewAttestationRejected("review_key_signer_mismatch")
    if attestation.get("verdict") != "PASS":
        raise ReviewAttestationRejected("independent_review_not_pass")
    if not isinstance(implementer_id, str) or not implementer_id.strip():
        raise ReviewAttestationRejected("review_implementer_identity_missing")
    if reviewer == implementer_id:
        raise ReviewAttestationRejected("reviewer_must_be_independent_of_implementer")

    refs = attestation.get("evidence_refs")
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(item, str) or not item.strip() for item in refs)):
        raise ReviewAttestationRejected("review_evidence_refs_invalid")
    signature = attestation.get("signature")
    if not isinstance(signature, str):
        raise ReviewAttestationRejected("review_signature_missing_or_invalid")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError):
        raise ReviewAttestationRejected("review_signature_missing_or_invalid") from None
    if len(signature_bytes) != 64:
        raise ReviewAttestationRejected("review_signature_missing_or_invalid")

    canonical = _canonical(attestation)
    public_key = _load_public_key(public_key_pem)
    try:
        public_key.verify(signature_bytes, canonical)
    except InvalidSignature:
        raise ReviewAttestationRejected("review_signature_invalid") from None

    current = now.astimezone(timezone.utc)
    reviewed_at = _timestamp(attestation.get("reviewed_at"))
    if reviewed_at > current + _MAX_FUTURE_SKEW:
        raise ReviewAttestationRejected("review_timestamp_in_future")
    if current - reviewed_at > _MAX_AGE:
        raise ReviewAttestationRejected("review_attestation_expired")

    if isinstance(used_attestation_hashes, (str, bytes)):
        raise ReviewAttestationRejected("review_replay_ledger_invalid")
    try:
        used = set(used_attestation_hashes)
    except (TypeError, ValueError):
        raise ReviewAttestationRejected("review_replay_ledger_invalid") from None
    if any(not isinstance(item, str) or not _HEX_64.fullmatch(item) for item in used):
        raise ReviewAttestationRejected("review_replay_ledger_invalid")
    fingerprint = hashlib.sha256(canonical + signature_bytes).hexdigest()
    if fingerprint in used:
        raise ReviewAttestationRejected("review_attestation_replayed")

    return VerifiedIndependentReview(
        reviewer_id=reviewer,
        verdict="PASS",
        evidence_refs=tuple(refs),
        reviewed_at=reviewed_at.isoformat(),
        commit_sha=commit_sha,
        cycle_id=cycle_id,
        nonce=expected_nonce,
        attestation_hash=fingerprint,
    )
