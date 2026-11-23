"""Deterministic, proposal-only evidence integrity checks for AI Factory stages 441-445."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
    return parsed if parsed.tzinfo is not None else None


def check_evidence_identity(evidence: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """441: require unique evidence IDs and explicit source, type, and content digest."""
    errors: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(evidence):
        eid = item.get("evidence_id")
        if not _text(eid):
            errors.append(f"evidence_id_invalid:{i}")
        elif eid in seen:
            errors.append(f"evidence_id_duplicate:{eid}")
        else:
            seen.add(eid)
        for field in ("source_id", "evidence_type", "content_sha256"):
            if not _text(item.get(field)):
                errors.append(f"evidence_{field}_missing:{eid if _text(eid) else i}")
        digest = item.get("content_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"evidence_digest_invalid:{eid if _text(eid) else i}")
    if not evidence:
        errors.append("evidence_inventory_empty")
    return {"stage": 441, "pass": not errors, "errors": errors, "evidence_count": len(seen)}


def check_evidence_freshness(evidence: Sequence[Mapping[str, Any]], *,
                             evaluated_at: str, max_age_seconds: int) -> dict[str, Any]:
    """442: reject missing, future-dated, timezone-naive, or stale evidence timestamps."""
    errors: list[str] = []
    now = _time(evaluated_at)
    if now is None:
        errors.append("evaluation_time_invalid")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds < 0:
        errors.append("max_age_invalid")
    if now is not None and isinstance(max_age_seconds, int) and not isinstance(max_age_seconds, bool) and max_age_seconds >= 0:
        for i, item in enumerate(evidence):
            stamp = _time(item.get("observed_at"))
            if stamp is None:
                errors.append(f"evidence_time_invalid:{item.get('evidence_id', i)}")
            elif stamp > now:
                errors.append(f"evidence_from_future:{item.get('evidence_id', i)}")
            elif (now - stamp).total_seconds() > max_age_seconds:
                errors.append(f"evidence_stale:{item.get('evidence_id', i)}")
    return {"stage": 442, "pass": not errors, "errors": errors,
            "evaluated_at": evaluated_at, "max_age_seconds": max_age_seconds}


def check_source_independence(evidence: Sequence[Mapping[str, Any]],
                              required_independent_sources: int) -> dict[str, Any]:
    """443: count distinct declared source IDs; declarations do not prove independence."""
    errors: list[str] = []
    if (not isinstance(required_independent_sources, int)
            or isinstance(required_independent_sources, bool) or required_independent_sources < 1):
        errors.append("independent_source_threshold_invalid")
        threshold = 1
    else:
        threshold = required_independent_sources
    sources = {item.get("source_id") for item in evidence if _text(item.get("source_id"))}
    if len(sources) < threshold:
        errors.append("independent_source_count_below_threshold")
    return {"stage": 443, "pass": not errors, "errors": errors,
            "declared_distinct_source_count": len(sources), "required_count": threshold}


def check_evidence_consistency(claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """444: flag incompatible declared values for the same claim key."""
    errors: list[str] = []
    values: dict[str, set[str]] = {}
    for i, item in enumerate(claims):
        key, value = item.get("claim_key"), item.get("value")
        if not _text(key) or not _text(value):
            errors.append(f"claim_invalid:{i}")
            continue
        values.setdefault(key, set()).add(value)
    conflicts = sorted(key for key, candidates in values.items() if len(candidates) > 1)
    errors.extend(f"evidence_claim_conflict:{key}" for key in conflicts)
    return {"stage": 444, "pass": not errors, "errors": errors, "conflicting_claim_keys": conflicts}


def evaluate_stages_441_445(*, evidence: Sequence[Mapping[str, Any]],
                            evaluated_at: str, max_age_seconds: int,
                            required_independent_sources: int,
                            claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """445: aggregate evidence integrity; readiness only, no authorization."""
    identity = check_evidence_identity(evidence)
    freshness = check_evidence_freshness(evidence, evaluated_at=evaluated_at,
                                         max_age_seconds=max_age_seconds)
    independence = check_source_independence(evidence, required_independent_sources)
    consistency = check_evidence_consistency(claims)
    checks = [identity, freshness, independence, consistency]
    passed = all(item["pass"] for item in checks)
    payload = {"checks": checks, "pass": passed, "proposal_only": True,
               "evidence_authoritative": False}
    return {"stage": 445, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "seal": _seal(payload), "proposal_only": True,
            "evidence_authoritative": False, "execution_authorized": False,
            "promotion_authorized": False}
