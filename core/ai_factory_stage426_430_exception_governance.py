"""Proposal-only exception governance validators for AI Factory stages 426-430."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _time(value: Any) -> datetime | None:
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def check_exception_identity(exceptions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """426: require unique exception IDs, explicit rationale, and bounded exact scope."""
    errors: list[str] = []
    seen: set[str] = set()
    if not exceptions:
        errors.append("exceptions_empty")
    for i, item in enumerate(exceptions):
        eid = item.get("exception_id")
        if not _text(eid):
            errors.append(f"exception_id_invalid:{i}")
        elif eid in seen:
            errors.append(f"exception_id_duplicate:{eid}")
        else:
            seen.add(eid)
        for field in ("rationale", "scope_type", "scope_id", "requested_by"):
            if not _text(item.get(field)):
                errors.append(f"exception_{field}_missing:{eid if _text(eid) else i}")
        scope_type = item.get("scope_type")
        if _text(scope_type) and scope_type not in ("metric", "workflow", "dataset", "evaluation", "artifact"):
            errors.append(f"exception_scope_type_invalid:{eid}")
    return {"stage": 426, "pass": not errors, "errors": errors, "exception_count": len(seen)}


def check_exception_approval_separation(exceptions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """427: require explicit approver distinct from requester and a recorded decision."""
    errors: list[str] = []
    for i, item in enumerate(exceptions):
        eid = item.get("exception_id")
        requester, approver = item.get("requested_by"), item.get("approved_by")
        if not _text(requester) or not _text(approver):
            errors.append(f"exception_approval_identity_missing:{eid if _text(eid) else i}")
        elif requester == approver:
            errors.append(f"exception_self_approval:{eid}")
        if item.get("decision") not in ("approved", "rejected"):
            errors.append(f"exception_decision_invalid:{eid if _text(eid) else i}")
        if not _text(item.get("decision_ref")):
            errors.append(f"exception_decision_ref_missing:{eid if _text(eid) else i}")
    return {"stage": 427, "pass": not errors, "errors": errors}


def check_exception_lifecycle(exceptions: Sequence[Mapping[str, Any]], *,
                              evaluated_at: str) -> dict[str, Any]:
    """428: validate timezone-aware validity windows and revocation state."""
    errors: list[str] = []
    now = _time(evaluated_at)
    if now is None:
        errors.append("evaluation_timestamp_invalid")
    for i, item in enumerate(exceptions):
        eid = item.get("exception_id")
        start, end = _time(item.get("valid_from")), _time(item.get("expires_at"))
        if start is None or end is None:
            errors.append(f"exception_lifecycle_timestamp_invalid:{eid if _text(eid) else i}")
            continue
        if start >= end:
            errors.append(f"exception_lifecycle_window_invalid:{eid if _text(eid) else i}")
        if now is not None and (now < start or now >= end):
            errors.append(f"exception_not_currently_valid:{eid if _text(eid) else i}")
        revoked = item.get("revoked")
        if not isinstance(revoked, bool):
            errors.append(f"exception_revocation_state_invalid:{eid if _text(eid) else i}")
        elif revoked:
            errors.append(f"exception_revoked:{eid if _text(eid) else i}")
    return {"stage": 428, "pass": not errors, "errors": errors}


def check_exception_scope_binding(exceptions: Sequence[Mapping[str, Any]],
                                  requested_scopes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """429: require each exception to bind to an exact requested scope, without wildcards."""
    errors: list[str] = []
    allowed = {(x.get("scope_type"), x.get("scope_id")) for x in requested_scopes
               if _text(x.get("scope_type")) and _text(x.get("scope_id"))}
    for i, item in enumerate(exceptions):
        scope = (item.get("scope_type"), item.get("scope_id"))
        if not all(_text(v) for v in scope):
            errors.append(f"exception_scope_invalid:{i}")
        elif scope not in allowed:
            errors.append(f"exception_scope_unbound:{item.get('exception_id')}")
        if scope[1] == "*" or scope[1] == "all":
            errors.append(f"exception_wildcard_scope_forbidden:{item.get('exception_id')}")
    if not requested_scopes:
        errors.append("requested_scopes_empty")
    return {"stage": 429, "pass": not errors, "errors": errors,
            "requested_scope_count": len(allowed)}


def evaluate_stages_426_430(*, exceptions: Sequence[Mapping[str, Any]],
                            requested_scopes: Sequence[Mapping[str, Any]],
                            evaluated_at: str) -> dict[str, Any]:
    """430: report exception governance readiness; never grants operational authority."""
    checks = [
        check_exception_identity(exceptions),
        check_exception_approval_separation(exceptions),
        check_exception_lifecycle(exceptions, evaluated_at=evaluated_at),
        check_exception_scope_binding(exceptions, requested_scopes),
    ]
    errors: list[str] = []
    # This is a review/readiness result only. Even a fully valid exception is not activated.
    passed = all(c["pass"] for c in checks) and not errors
    payload = {"checks": checks, "errors": errors, "all_pass": passed,
               "proposal_only": True, "exception_activation_authorized": False,
               "execution_authorized": False, "promotion_authorized": False}
    return {"stage": 430, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _seal(payload),
            "proposal_only": True, "exception_activation_authorized": False,
            "execution_authorized": False, "promotion_authorized": False}
