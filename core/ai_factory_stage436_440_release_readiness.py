"""Proposal-only release-readiness declaration checks, stages 436-440."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_release_artifact_inventory(artifacts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """436: require unique, identified, digest-shaped release candidate artifacts."""
    errors: list[str] = []
    seen: set[str] = set()
    if not artifacts:
        errors.append("release_artifacts_empty")
    for i, item in enumerate(artifacts):
        aid = item.get("artifact_id")
        if not _text(aid):
            errors.append(f"artifact_id_invalid:{i}")
        elif aid in seen:
            errors.append(f"artifact_id_duplicate:{aid}")
        else:
            seen.add(aid)
        for field in ("version", "kind", "sha256"):
            if not _text(item.get(field)):
                errors.append(f"artifact_{field}_missing:{aid if _text(aid) else i}")
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"artifact_digest_invalid:{aid if _text(aid) else i}")
    return {"stage": 436, "pass": not errors, "errors": errors, "artifact_count": len(seen)}


def check_required_validation_results(results: Sequence[Mapping[str, Any]],
                                      required_checks: Sequence[str]) -> dict[str, Any]:
    """437: require exactly one successful result for every named required check."""
    errors: list[str] = []
    if not required_checks:
        errors.append("required_checks_empty")
    if len(set(required_checks)) != len(required_checks):
        errors.append("required_checks_duplicate")
    by_name: dict[str, list[Mapping[str, Any]]] = {}
    for item in results:
        name = item.get("name")
        if _text(name):
            by_name.setdefault(name, []).append(item)
    for name in required_checks:
        matches = by_name.get(name, [])
        if len(matches) != 1:
            errors.append(f"required_check_missing_or_duplicated:{name}")
        elif matches[0].get("status") != "completed" or matches[0].get("conclusion") != "success":
            errors.append(f"required_check_not_successful:{name}")
        elif not _text(matches[0].get("head_sha")):
            errors.append(f"required_check_sha_missing:{name}")
    shas = {item.get("head_sha") for name in required_checks
            for item in by_name.get(name, []) if _text(item.get("head_sha"))}
    if len(shas) > 1:
        errors.append("required_checks_head_sha_mismatch")
    return {"stage": 437, "pass": not errors, "errors": errors,
            "required_check_count": len(required_checks)}


def check_blocker_register(blockers: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """438: reject unresolved blockers and malformed blocker records."""
    errors: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(blockers):
        bid = item.get("blocker_id")
        if not _text(bid):
            errors.append(f"blocker_id_invalid:{i}")
        elif bid in seen:
            errors.append(f"blocker_id_duplicate:{bid}")
        else:
            seen.add(bid)
        if item.get("status") != "resolved":
            errors.append(f"blocker_unresolved:{bid if _text(bid) else i}")
        if not _text(item.get("resolution_ref")):
            errors.append(f"blocker_resolution_ref_missing:{bid if _text(bid) else i}")
    return {"stage": 438, "pass": not errors, "errors": errors, "blocker_count": len(seen)}


def check_rollback_readiness(plan: Mapping[str, Any]) -> dict[str, Any]:
    """439: require documented rollback owner, trigger, steps, and verification."""
    errors: list[str] = []
    for field in ("plan_id", "owner", "trigger", "verification_method", "evidence_ref"):
        if not _text(plan.get(field)):
            errors.append(f"rollback_{field}_missing")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps or any(not _text(step) for step in steps):
        errors.append("rollback_steps_invalid")
    if plan.get("tested") is not True:
        errors.append("rollback_test_evidence_not_declared")
    return {"stage": 439, "pass": not errors, "errors": errors}


def evaluate_stages_436_440(*, artifacts: Sequence[Mapping[str, Any]],
                            validation_results: Sequence[Mapping[str, Any]],
                            required_checks: Sequence[str],
                            blockers: Sequence[Mapping[str, Any]],
                            rollback_plan: Mapping[str, Any],
                            expected_head_sha: str) -> dict[str, Any]:
    """440: aggregate candidate readiness only; never authorizes or performs release."""
    inventory = check_release_artifact_inventory(artifacts)
    validations = check_required_validation_results(validation_results, required_checks)
    blocker_check = check_blocker_register(blockers)
    rollback = check_rollback_readiness(rollback_plan)
    checks = [inventory, validations, blocker_check, rollback]
    errors: list[str] = []
    observed = {item.get("head_sha") for item in validation_results
                if item.get("name") in required_checks and _text(item.get("head_sha"))}
    if not _text(expected_head_sha):
        errors.append("expected_head_sha_missing")
    elif observed and observed != {expected_head_sha}:
        errors.append("validation_results_not_for_expected_head")
    passed = all(item["pass"] for item in checks) and not errors
    payload = {"checks": checks, "errors": errors, "pass": passed,
               "proposal_only": True, "release_authorized": False}
    return {"stage": 440, "status": "READY_FOR_SEPARATE_REVIEW" if passed else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _seal(payload),
            "proposal_only": True, "release_authorized": False,
            "execution_authorized": False, "promotion_authorized": False}
