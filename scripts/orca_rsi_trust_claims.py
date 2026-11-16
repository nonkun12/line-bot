"""Strict Ed25519 verification for task-approval and budget claims.

Verification only: this module does not provision keys, consume replay nonces,
or start workers. Callers must use separate trust stores and durable CAS
replay ledgers for each claim purpose.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{32,256}$")
_APPROVAL_FIELDS = {
    "claim_type", "schema_version", "key_id", "repository", "task_id",
    "task_digest", "cycle_id", "commit_sha", "approver_id", "verdict",
    "nonce", "issued_at", "expires_at", "signature",
}
_BUDGET_FIELDS = {
    "claim_type", "schema_version", "key_id", "repository", "task_id",
    "task_digest", "cycle_id", "commit_sha", "issuer_id", "budget_unit",
    "authorized_limit_units", "observed_spend_units", "remaining_units",
    "evidence_refs", "evidence_sha256", "nonce", "issued_at", "expires_at",
    "signature",
}


class TrustClaimRejected(ValueError):
    """Raised when a signed task approval or budget claim is not trustworthy."""


@dataclass(frozen=True)
class VerifiedTrustClaim:
    claim_type: str
    key_id: str
    signer_id: str
    repository: str
    task_id: str
    task_digest: str
    cycle_id: str
    commit_sha: str
    nonce: str
    claim_hash: str
    expires_at: str


def canonical_claim_bytes(claim: Mapping[str, Any]) -> bytes:
    """Canonical signed bytes; only the signature field is excluded."""
    unsigned = {key: value for key, value in claim.items() if key != "signature"}
    try:
        return json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise TrustClaimRejected("claim_not_canonicalizable") from None


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TrustClaimRejected(f"{field}_must_be_utc_z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise TrustClaimRejected(f"{field}_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise TrustClaimRejected(f"{field}_invalid_timezone")
    return parsed.astimezone(timezone.utc)


def _verify_common(
    claim: Any,
    *,
    expected_type: str,
    fields: set[str],
    keyring: Mapping[str, str | bytes],
    key_signer_map: Mapping[str, str],
    allowed_signers: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    signer_field: str,
    repository: str,
    task_id: str,
    task_digest: str,
    cycle_id: str,
    commit_sha: str,
    now: datetime,
    max_lifetime: timedelta,
) -> VerifiedTrustClaim:
    if not isinstance(claim, dict):
        raise TrustClaimRejected("claim_missing_or_invalid")
    if set(claim) != fields:
        raise TrustClaimRejected("claim_fields_mismatch")
    if type(claim.get("schema_version")) is not int or claim["schema_version"] != 1:
        raise TrustClaimRejected("claim_schema_invalid")
    if claim.get("claim_type") != expected_type:
        raise TrustClaimRejected("claim_type_mismatch")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise TrustClaimRejected("trusted_clock_invalid")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise TrustClaimRejected("expected_repository_invalid")
    if not isinstance(task_id, str) or not task_id:
        raise TrustClaimRejected("expected_task_id_invalid")
    for field, expected, pattern in (
        ("task_digest", task_digest, _HEX_64),
        ("cycle_id", cycle_id, _HEX_64),
        ("commit_sha", commit_sha, _HEX_40),
    ):
        if not isinstance(expected, str) or not pattern.fullmatch(expected):
            raise TrustClaimRejected(f"expected_{field}_invalid")
        if claim.get(field) != expected:
            raise TrustClaimRejected(f"{field}_mismatch")
    if claim.get("repository") != repository:
        raise TrustClaimRejected("repository_mismatch")
    if claim.get("task_id") != task_id:
        raise TrustClaimRejected("task_id_mismatch")

    key_id = claim.get("key_id")
    if not isinstance(key_id, str) or not key_id or key_id not in keyring:
        raise TrustClaimRejected("claim_key_id_not_allowlisted")
    if isinstance(allowed_signers, (str, bytes)) or not isinstance(
        allowed_signers, (set, frozenset, tuple, list)
    ):
        raise TrustClaimRejected("claim_signer_allowlist_invalid")
    if any(not isinstance(item, str) or not item for item in allowed_signers):
        raise TrustClaimRejected("claim_signer_allowlist_invalid")
    signer = claim.get(signer_field)
    if not isinstance(signer, str) or signer not in set(allowed_signers):
        raise TrustClaimRejected("claim_signer_not_allowlisted")
    if (not isinstance(key_signer_map, Mapping)
            or any(not isinstance(k, str) or not isinstance(v, str) or not v
                   for k, v in key_signer_map.items())):
        raise TrustClaimRejected("claim_key_signer_map_invalid")
    if key_signer_map.get(key_id) != signer:
        raise TrustClaimRejected("claim_key_signer_mismatch")

    nonce = claim.get("nonce")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise TrustClaimRejected("claim_nonce_invalid")

    issued = _parse_time(claim.get("issued_at"), "claim_issued_at")
    expires = _parse_time(claim.get("expires_at"), "claim_expires_at")
    current = now.astimezone(timezone.utc)
    if issued > current + timedelta(minutes=1):
        raise TrustClaimRejected("claim_issued_in_future")
    if expires <= current:
        raise TrustClaimRejected("claim_expired")
    if expires <= issued or expires - issued > max_lifetime:
        raise TrustClaimRejected("claim_lifetime_invalid")
    if current < issued - timedelta(minutes=1):
        raise TrustClaimRejected("claim_not_yet_valid")

    signature = claim.get("signature")
    if not isinstance(signature, str):
        raise TrustClaimRejected("claim_signature_invalid")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        public_raw = keyring[key_id]
        public_bytes = public_raw.encode("utf-8") if isinstance(public_raw, str) else public_raw
        public_key = serialization.load_pem_public_key(public_bytes)
    except (ValueError, TypeError):
        raise TrustClaimRejected("claim_signature_or_key_invalid") from None
    if len(signature_bytes) != 64 or not isinstance(public_key, Ed25519PublicKey):
        raise TrustClaimRejected("claim_signature_or_key_invalid")
    canonical = canonical_claim_bytes(claim)
    try:
        public_key.verify(signature_bytes, canonical)
    except InvalidSignature:
        raise TrustClaimRejected("claim_signature_invalid") from None

    digest = hashlib.sha256(canonical + signature_bytes).hexdigest()
    return VerifiedTrustClaim(
        claim_type=expected_type, key_id=key_id, signer_id=signer,
        repository=repository, task_id=task_id, task_digest=task_digest,
        cycle_id=cycle_id, commit_sha=commit_sha, nonce=nonce,
        claim_hash=digest, expires_at=expires.isoformat(),
    )


def verify_task_approval(
    claim: Any, *, keyring: Mapping[str, str | bytes],
    key_signer_map: Mapping[str, str],
    allowed_approvers: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    repository: str, task_id: str, task_digest: str, cycle_id: str,
    commit_sha: str, now: datetime, implementer_id: str,
) -> VerifiedTrustClaim:
    """Verify an explicit approval bound to the immutable task and commit."""
    if not isinstance(claim, dict) or claim.get("verdict") != "APPROVED":
        raise TrustClaimRejected("task_approval_not_approved")
    verified = _verify_common(
        claim, expected_type="orca_rsi_task_approval",
        fields=_APPROVAL_FIELDS, keyring=keyring,
        key_signer_map=key_signer_map, allowed_signers=allowed_approvers, signer_field="approver_id",
        repository=repository, task_id=task_id, task_digest=task_digest,
        cycle_id=cycle_id, commit_sha=commit_sha, now=now,
        max_lifetime=timedelta(minutes=10),
    )
    if not isinstance(implementer_id, str) or not implementer_id:
        raise TrustClaimRejected("implementer_identity_missing")
    if verified.signer_id == implementer_id:
        raise TrustClaimRejected("task_self_approval_forbidden")
    return verified


def verify_budget_authorization(
    claim: Any, *, keyring: Mapping[str, str | bytes],
    key_signer_map: Mapping[str, str],
    allowed_issuers: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    repository: str, task_id: str, task_digest: str, cycle_id: str,
    commit_sha: str, now: datetime, expected_budget_unit: str,
    resolved_evidence: Mapping[str, bytes] | None,
) -> VerifiedTrustClaim:
    """Verify signed budget bounds and a retrieved, digest-matched evidence bundle."""
    if not isinstance(claim, dict):
        raise TrustClaimRejected("claim_missing_or_invalid")
    verified = _verify_common(
        claim, expected_type="orca_rsi_budget_authorization",
        fields=_BUDGET_FIELDS, keyring=keyring,
        key_signer_map=key_signer_map, allowed_signers=allowed_issuers, signer_field="issuer_id",
        repository=repository, task_id=task_id, task_digest=task_digest,
        cycle_id=cycle_id, commit_sha=commit_sha, now=now,
        max_lifetime=timedelta(minutes=5),
    )
    if not isinstance(expected_budget_unit, str) or not expected_budget_unit:
        raise TrustClaimRejected("budget_unit_configuration_missing")
    if claim.get("budget_unit") != expected_budget_unit:
        raise TrustClaimRejected("budget_unit_mismatch")
    values = (
        claim.get("authorized_limit_units"),
        claim.get("observed_spend_units"),
        claim.get("remaining_units"),
    )
    if any(type(value) is not int for value in values):
        raise TrustClaimRejected("budget_values_must_be_integers")
    limit, spent, remaining = values
    if limit <= 0 or spent < 0 or remaining < 0:
        raise TrustClaimRejected("budget_values_out_of_range")
    if spent + remaining > limit:
        raise TrustClaimRejected("budget_limit_exceeded")

    refs = claim.get("evidence_refs")
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or len(refs) != len(set(refs))):
        raise TrustClaimRejected("budget_evidence_refs_invalid")
    evidence_digest = claim.get("evidence_sha256")
    if not isinstance(evidence_digest, str) or not _HEX_64.fullmatch(evidence_digest):
        raise TrustClaimRejected("budget_evidence_digest_invalid")
    if not isinstance(resolved_evidence, Mapping) or set(resolved_evidence) != set(refs):
        raise TrustClaimRejected("budget_evidence_unavailable")
    if any(not isinstance(value, bytes) for value in resolved_evidence.values()):
        raise TrustClaimRejected("budget_evidence_unavailable")
    bundle = b"".join(
        len(ref.encode("utf-8")).to_bytes(4, "big") + ref.encode("utf-8")
        + len(resolved_evidence[ref]).to_bytes(8, "big") + resolved_evidence[ref]
        for ref in sorted(refs)
    )
    if hashlib.sha256(bundle).hexdigest() != evidence_digest:
        raise TrustClaimRejected("budget_evidence_digest_mismatch")
    return verified
