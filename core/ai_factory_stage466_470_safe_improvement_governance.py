"""Safe improvement governance declarations for AI Factory stages 466-470."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_review_evidence(review: Mapping[str, Any], *,
                          expected_head: str, required_dimensions: Sequence[str]) -> dict[str, Any]:
    """466: validate review scope, exact head binding, and coverage declarations."""
    errors: list[str] = []
    if not _text(expected_head) or review.get("head_sha") != expected_head:
        errors.append("review_head_mismatch")
    for field in ("review_id", "reviewer_id", "review_method", "reviewed_at"):
        if not _text(review.get(field)):
            errors.append(f"review_{field}_missing")
    dimensions = review.get("dimensions")
    if not isinstance(dimensions, list):
        errors.append("review_dimensions_invalid")
        dimensions = []
    if len(set(x for x in dimensions if _text(x))) != len(dimensions):
        errors.append("review_dimensions_duplicate_or_invalid")
    missing = sorted(set(required_dimensions) - set(dimensions))
    if missing:
        errors.append("review_dimensions_missing:" + ",".join(missing))
    return {"stage": 466, "pass": not errors, "errors": errors,
            "missing_dimensions": missing}


def check_reviewer_separation(reviewers: Sequence[Mapping[str, Any]], *,
                              author_id: str, minimum_reviewers: int = 1) -> dict[str, Any]:
    """467: ensure reviewer identities are distinct from author and each other."""
    errors: list[str] = []
    if not _text(author_id):
        errors.append("author_id_missing")
    if not isinstance(minimum_reviewers, int) or isinstance(minimum_reviewers, bool) or minimum_reviewers < 1:
        errors.append("minimum_reviewers_invalid")
        minimum = 1
    else:
        minimum = minimum_reviewers
    ids: list[str] = []
    for i, reviewer in enumerate(reviewers):
        rid = reviewer.get("reviewer_id")
        if not _text(rid):
            errors.append(f"reviewer_id_invalid:{i}")
        else:
            ids.append(rid)
            if rid == author_id:
                errors.append("author_cannot_review_own_change")
    if len(ids) != len(set(ids)):
        errors.append("reviewer_identity_duplicate")
    if len(set(ids)) < minimum:
        errors.append("independent_reviewer_count_below_minimum")
    return {"stage": 467, "pass": not errors, "errors": errors,
            "reviewer_count": len(set(ids)), "minimum_reviewers": minimum}


def check_hold_register(holds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """468: require unique, actionable HOLD records and reject implicit clearance."""
    errors: list[str] = []
    seen: set[str] = set()
    for i, hold in enumerate(holds):
        hid = hold.get("hold_id")
        if not _text(hid):
            errors.append(f"hold_id_invalid:{i}")
        elif hid in seen:
            errors.append(f"hold_id_duplicate:{hid}")
        else:
            seen.add(hid)
        for field in ("reason", "owner", "required_evidence"):
            if not _text(hold.get(field)):
                errors.append(f"hold_{field}_missing:{hid if _text(hid) else i}")
        if hold.get("cleared") is True:
            errors.append(f"hold_clearance_not_authorized:{hid if _text(hid) else i}")
    return {"stage": 468, "pass": not errors, "errors": errors,
            "hold_count": len(seen), "holds_preserved": True}


def check_recovery_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """469: validate declared recovery/rollback plan without executing it."""
    errors: list[str] = []
    for field in ("plan_id", "trigger_conditions", "recovery_steps",
                  "verification_steps", "owner", "data_preservation"):
        value = plan.get(field)
        if isinstance(value, list):
            if not value or any(not _text(x) for x in value):
                errors.append(f"recovery_{field}_invalid")
        elif not _text(value):
            errors.append(f"recovery_{field}_missing")
    if plan.get("execution_requested") is True:
        errors.append("recovery_execution_not_permitted")
    return {"stage": 469, "pass": not errors, "errors": errors,
            "recovery_executed": False}


def evaluate_stages_466_470(*, review: Mapping[str, Any], expected_head: str,
                            required_dimensions: Sequence[str],
                            reviewers: Sequence[Mapping[str, Any]], author_id: str,
                            holds: Sequence[Mapping[str, Any]], recovery_plan: Mapping[str, Any],
                            minimum_reviewers: int = 1) -> dict[str, Any]:
    """470: final governance screen; never clears HOLD or grants release authority."""
    checks = [
        check_review_evidence(review, expected_head=expected_head,
                              required_dimensions=required_dimensions),
        check_reviewer_separation(reviewers, author_id=author_id,
                                  minimum_reviewers=minimum_reviewers),
        check_hold_register(holds),
        check_recovery_plan(recovery_plan),
    ]
    passed = all(item["pass"] for item in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 470, "status": "READY_FOR_REVIEW" if passed else "HOLD",
            "checks": checks, "seal": _seal(record), "hold_release_authorized": False,
            "recovery_execution_authorized": False, "merge_authorized": False,
            "deployment_authorized": False, "promotion_authorized": False,
            "proposal_only": True}
