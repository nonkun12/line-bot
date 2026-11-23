"""Stages 251-255: artifact integrity, replay controls and role separation.

These deterministic checks validate supplied structures and bytes. They do not
authenticate external identities, provide durable nonce storage, or grant authority.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
from datetime import datetime
from typing import Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[0-9a-f]{32,128}$")
_FALSE = {
    "proposal_only": True, "task_execution_authorized": False,
    "experiment_execution_authorized": False, "model_change_authorized": False,
    "merge_deploy_authorized": False, "hold_release_authorized": False,
}


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _out(payload):
    result = {**payload, **_FALSE}
    body = {k: v for k, v in result.items() if k != "result_digest"}
    result["result_digest"] = sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return result


def _valid(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    claimed = result.get("result_digest")
    if not _digest(claimed):
        return False
    try:
        body = {k: v for k, v in result.items() if k != "result_digest"}
        actual = sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        return False
    return claimed == actual


def _time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def stage251_verify_artifact_bytes(*, artifacts: Sequence[Mapping], package_id: str,
                                   held: bool = False):
    """Hash actual supplied bytes and validate each declared SHA-256 digest."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(package_id, str) or not package_id.strip() or not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)) or not artifacts:
        return _blocked("package ID and at least one artifact are required")
    seen, rows = set(), []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            return _blocked("each artifact must be a mapping")
        artifact_id, content, expected = artifact.get("artifact_id"), artifact.get("content"), artifact.get("sha256")
        if not isinstance(artifact_id, str) or not artifact_id.strip() or artifact_id in seen:
            return _blocked("artifact IDs must be non-empty and unique")
        if not isinstance(content, bytes) or not _digest(expected):
            return _blocked("artifact content must be bytes with a valid declared digest")
        actual = sha256(content).hexdigest()
        if actual != expected:
            return _blocked("artifact byte digest mismatch")
        seen.add(artifact_id)
        rows.append({"artifact_id": artifact_id, "sha256": actual, "size_bytes": len(content)})
    rows.sort(key=lambda row: row["artifact_id"])
    package_digest = sha256(json.dumps(
        {"package_id": package_id, "artifacts": rows},
        sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return _out({
        "status": "ARTIFACT_BYTES_VERIFIED", "package_id": package_id,
        "artifact_count": len(rows), "artifacts": rows, "package_digest": package_digest,
    })


def stage252_validate_key_lifecycle(*, key_records: Sequence[Mapping], evaluated_at: str,
                                    held: bool = False):
    """Check key-record shape, validity windows and revocation state (not signatures)."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    now = _time(evaluated_at)
    if now is None or not isinstance(key_records, Sequence) or isinstance(key_records, (str, bytes)) or not key_records:
        return _blocked("timezone-aware evaluation time and key records are required")
    seen, normalized = set(), []
    for record in key_records:
        if not isinstance(record, Mapping):
            return _blocked("each key record must be a mapping")
        key_id, principal_id, state = record.get("key_id"), record.get("principal_id"), record.get("state")
        start, end = _time(record.get("valid_from")), _time(record.get("valid_until"))
        if (not isinstance(key_id, str) or not key_id.strip() or key_id in seen
                or not isinstance(principal_id, str) or not principal_id.strip()
                or state not in {"active", "revoked"} or start is None or end is None
                or start >= end):
            return _blocked("invalid, duplicate or incomplete key lifecycle record")
        if state == "active" and not start <= now < end:
            return _blocked("active key is outside its declared validity window")
        seen.add(key_id)
        normalized.append({"key_id": key_id, "principal_id": principal_id, "state": state,
                           "valid_from": start.isoformat(), "valid_until": end.isoformat()})
    normalized.sort(key=lambda row: row["key_id"])
    registry_digest = sha256(json.dumps(
        normalized, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return _out({
        "status": "KEY_LIFECYCLE_STRUCTURALLY_VALID", "key_count": len(normalized),
        "active_key_count": sum(row["state"] == "active" for row in normalized),
        "registry_digest": registry_digest,
    })


def stage253_replay_check(*, nonce: str, consumed_nonces: Sequence[str],
                          issued_at: str, expires_at: str, evaluated_at: str,
                          package_digest: str, held: bool = False):
    """Reject reused/malformed nonces and expired or future-issued attestations."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    issued, expires, now = _time(issued_at), _time(expires_at), _time(evaluated_at)
    if (not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)
            or not isinstance(consumed_nonces, Sequence) or isinstance(consumed_nonces, (str, bytes))
            or any(not isinstance(item, str) or not _NONCE.fullmatch(item) for item in consumed_nonces)
            or len(set(consumed_nonces)) != len(consumed_nonces)
            or nonce in consumed_nonces or issued is None or expires is None or now is None
            or issued >= expires or issued > now or now >= expires or not _digest(package_digest)):
        return _blocked("nonce reuse, invalid time window or package digest")
    return _out({
        "status": "REPLAY_CHECK_CLEAR", "nonce_digest": sha256(nonce.encode()).hexdigest(),
        "package_digest": package_digest, "issued_at": issued.isoformat(),
        "expires_at": expires.isoformat(),
    })


def stage254_role_separation(*, assignments: Mapping, required_roles=("issuer", "evaluator", "approver"),
                             held: bool = False):
    """Require distinct declared principals for issuer, evaluator and approver roles."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(assignments, Mapping) or not isinstance(required_roles, Sequence) or isinstance(required_roles, (str, bytes)):
        return _blocked("role assignments and required role list are required")
    roles = tuple(required_roles)
    if (not roles or len(set(roles)) != len(roles)
            or any(not isinstance(role, str) or not role.strip() for role in roles)
            or any(not isinstance(assignments.get(role), str) or not assignments[role].strip() for role in roles)):
        return _blocked("all required roles must have distinct non-empty principals")
    principals = [assignments[role] for role in roles]
    if len(set(principals)) != len(principals):
        return _blocked("required roles must be assigned to distinct principals")
    normalized = {role: assignments[role] for role in sorted(roles)}
    return _out({
        "status": "ROLE_SEPARATION_DECLARED", "role_count": len(roles),
        "assignment_digest": sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    })


def stage255_attestation_review_gate(*, artifact_result: Mapping, key_result: Mapping,
                                     replay_result: Mapping, role_result: Mapping,
                                     held: bool = False):
    """Combine structural checks into a separate-review recommendation only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    checks = (
        (artifact_result, "ARTIFACT_BYTES_VERIFIED"),
        (key_result, "KEY_LIFECYCLE_STRUCTURALLY_VALID"),
        (replay_result, "REPLAY_CHECK_CLEAR"),
        (role_result, "ROLE_SEPARATION_DECLARED"),
    )
    if any(not _valid(result, status) for result, status in checks):
        return _blocked("one or more attestation checks failed integrity or status validation")
    if artifact_result["package_digest"] != replay_result["package_digest"]:
        return _blocked("artifact and replay package identities differ")
    return _out({
        "status": "ATTESTATION_READY_FOR_SEPARATE_REVIEW",
        "package_digest": artifact_result["package_digest"],
        "passed_stages": [251, 252, 253, 254],
        "required_next_step": "independent cryptographic verification and separate explicit authorization",
        "cryptographic_signature_verified": False,
        "durable_replay_registry_verified": False,
        "asi_or_rsi_claim": False,
    })
