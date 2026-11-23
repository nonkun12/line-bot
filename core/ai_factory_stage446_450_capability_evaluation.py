"""Deterministic capability-evaluation controls; proposal-only stages 446-450."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_evaluation_protocol(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """446: require a versioned, bounded, reproducible evaluation protocol declaration."""
    errors: list[str] = []
    for field in ("protocol_id", "version", "objective", "task_set_id", "scoring_method", "owner"):
        if not _text(protocol.get(field)):
            errors.append(f"protocol_{field}_missing")
    tasks = protocol.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("protocol_tasks_empty_or_invalid")
    else:
        ids = [task.get("task_id") for task in tasks if isinstance(task, Mapping)]
        if len(ids) != len(tasks) or any(not _text(x) for x in ids):
            errors.append("protocol_task_identity_invalid")
        elif len(set(ids)) != len(ids):
            errors.append("protocol_task_ids_duplicate")
    bounds = protocol.get("score_bounds")
    if (not isinstance(bounds, Mapping) or not isinstance(bounds.get("min"), (int, float))
            or isinstance(bounds.get("min"), bool) or not isinstance(bounds.get("max"), (int, float))
            or isinstance(bounds.get("max"), bool) or bounds["min"] >= bounds["max"]):
        errors.append("protocol_score_bounds_invalid")
    return {"stage": 446, "pass": not errors, "errors": errors}


def check_capability_results(results: Sequence[Mapping[str, Any]],
                             protocol: Mapping[str, Any]) -> dict[str, Any]:
    """447: validate per-task scores, unique task IDs, and exact task-set coverage."""
    errors: list[str] = []
    tasks = protocol.get("tasks")
    expected = {task.get("task_id") for task in tasks if isinstance(task, Mapping)} if isinstance(tasks, list) else set()
    bounds = protocol.get("score_bounds", {})
    low = bounds.get("min") if isinstance(bounds, Mapping) else None
    high = bounds.get("max") if isinstance(bounds, Mapping) else None
    seen: set[str] = set()
    for i, item in enumerate(results):
        tid, score = item.get("task_id"), item.get("score")
        if not _text(tid):
            errors.append(f"result_task_id_invalid:{i}")
        elif tid in seen:
            errors.append(f"result_task_duplicate:{tid}")
        else:
            seen.add(tid)
        if (not isinstance(score, (int, float)) or isinstance(score, bool)
                or not isinstance(low, (int, float)) or not isinstance(high, (int, float))
                or score < low or score > high):
            errors.append(f"result_score_out_of_bounds:{tid if _text(tid) else i}")
        if not _text(item.get("result_ref")):
            errors.append(f"result_reference_missing:{tid if _text(tid) else i}")
    for tid in sorted(expected - seen):
        errors.append(f"result_task_missing:{tid}")
    for tid in sorted(seen - expected):
        errors.append(f"result_task_unexpected:{tid}")
    return {"stage": 447, "pass": not errors, "errors": errors,
            "expected_task_count": len(expected), "result_task_count": len(seen)}


def check_baseline_alignment(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    """448: require matching protocol/task-set/scoring metadata for a valid comparison."""
    errors: list[str] = []
    for field in ("protocol_id", "task_set_id", "scoring_method", "score_bounds"):
        if current.get(field) != baseline.get(field):
            errors.append(f"baseline_{field}_mismatch")
    if not _text(baseline.get("baseline_id")):
        errors.append("baseline_id_missing")
    if current.get("version") == baseline.get("version"):
        errors.append("evaluation_version_not_advanced")
    return {"stage": 448, "pass": not errors, "errors": errors}


def check_regression_thresholds(current_score: float, baseline_score: float,
                                allowed_drop: float) -> dict[str, Any]:
    """449: flag score regressions exceeding a non-negative absolute threshold."""
    errors: list[str] = []
    numbers = (current_score, baseline_score, allowed_drop)
    if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in numbers):
        errors.append("regression_values_invalid")
        drop = None
    else:
        drop = baseline_score - current_score
        if allowed_drop < 0:
            errors.append("allowed_drop_negative")
        elif drop > allowed_drop:
            errors.append("regression_threshold_exceeded")
    return {"stage": 449, "pass": not errors, "errors": errors,
            "observed_drop": drop, "allowed_drop": allowed_drop}


def evaluate_stages_446_450(*, protocol: Mapping[str, Any],
                            results: Sequence[Mapping[str, Any]],
                            baseline_protocol: Mapping[str, Any],
                            current_score: float, baseline_score: float,
                            allowed_drop: float) -> dict[str, Any]:
    """450: produce a scorecard readiness report, never a general capability claim."""
    protocol_check = check_evaluation_protocol(protocol)
    results_check = check_capability_results(results, protocol)
    baseline_check = check_baseline_alignment(protocol, baseline_protocol)
    regression_check = check_regression_thresholds(current_score, baseline_score, allowed_drop)
    checks = [protocol_check, results_check, baseline_check, regression_check]
    passed = all(item["pass"] for item in checks)
    scorecard = {"protocol_id": protocol.get("protocol_id"),
                 "task_set_id": protocol.get("task_set_id"),
                 "current_score": current_score, "baseline_score": baseline_score,
                 "observed_drop": regression_check.get("observed_drop"),
                 "checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 450, "status": "PASS" if passed else "BLOCKED",
            "scorecard": scorecard, "seal": _seal(scorecard),
            "capability_claim_authorized": False, "execution_authorized": False,
            "promotion_authorized": False, "proposal_only": True}
