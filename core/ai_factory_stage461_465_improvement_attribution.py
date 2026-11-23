"""Controlled improvement-attribution checks for AI Factory stages 461-465."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _valid_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_paired_comparison(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    """461: require matched task/protocol/metric and distinct run identifiers."""
    errors: list[str] = []
    for field in ("protocol_id", "task_set_id", "metric_id", "scoring_method"):
        if not isinstance(baseline.get(field), str) or not baseline.get(field).strip():
            errors.append(f"baseline_{field}_missing")
        if baseline.get(field) != candidate.get(field):
            errors.append(f"comparison_{field}_mismatch")
    for label, record in (("baseline", baseline), ("candidate", candidate)):
        if not isinstance(record.get("run_id"), str) or not record.get("run_id").strip():
            errors.append(f"{label}_run_id_missing")
    if baseline.get("run_id") == candidate.get("run_id"):
        errors.append("comparison_run_ids_not_distinct")
    return {"stage": 461, "pass": not errors, "errors": errors}


def check_change_isolation(changes: Sequence[Mapping[str, Any]], declared_primary_change: str) -> dict[str, Any]:
    """462: accept a single declared primary change and reject additional uncontrolled changes."""
    errors: list[str] = []
    if not isinstance(declared_primary_change, str) or not declared_primary_change.strip():
        errors.append("primary_change_missing")
    ids: set[str] = set()
    primary_count = 0
    for i, change in enumerate(changes):
        cid, category = change.get("change_id"), change.get("category")
        if not isinstance(cid, str) or not cid.strip():
            errors.append(f"change_id_invalid:{i}")
        elif cid in ids:
            errors.append(f"change_id_duplicate:{cid}")
        else:
            ids.add(cid)
        if category == declared_primary_change:
            primary_count += 1
        elif category != "declared_control":
            errors.append(f"uncontrolled_change:{cid if isinstance(cid, str) else i}")
    if primary_count != 1:
        errors.append("primary_change_count_not_one")
    return {"stage": 462, "pass": not errors, "errors": errors,
            "change_count": len(changes), "primary_change_count": primary_count}


def check_metric_improvement(baseline_value: float, candidate_value: float, *,
                             direction: str, minimum_improvement: float) -> dict[str, Any]:
    """463: evaluate a declared metric direction and minimum absolute improvement."""
    errors: list[str] = []
    if not _valid_number(baseline_value) or not _valid_number(candidate_value):
        errors.append("metric_values_invalid")
        delta = None
    elif direction not in ("higher_is_better", "lower_is_better"):
        errors.append("metric_direction_invalid")
        delta = None
    else:
        delta = candidate_value - baseline_value
        gain = delta if direction == "higher_is_better" else -delta
        if not _valid_number(minimum_improvement) or minimum_improvement < 0:
            errors.append("minimum_improvement_invalid")
        elif gain + 1e-12 < minimum_improvement:
            errors.append("minimum_improvement_not_met")
    return {"stage": 463, "pass": not errors, "errors": errors,
            "raw_delta": delta, "direction": direction,
            "minimum_improvement": minimum_improvement}


def check_guardrail_metrics(baseline: Mapping[str, float], candidate: Mapping[str, float],
                            maximum_regressions: Mapping[str, float]) -> dict[str, Any]:
    """464: reject missing/non-finite guardrails and degradation beyond per-metric limits."""
    errors: list[str] = []
    regressions: dict[str, float] = {}
    if not maximum_regressions:
        errors.append("guardrail_limits_empty")
    for metric, limit in maximum_regressions.items():
        if metric not in baseline or metric not in candidate:
            errors.append(f"guardrail_metric_missing:{metric}")
            continue
        before, after = baseline[metric], candidate[metric]
        if not _valid_number(before) or not _valid_number(after) or not _valid_number(limit) or limit < 0:
            errors.append(f"guardrail_values_invalid:{metric}")
            continue
        regression = after - before
        regressions[metric] = regression
        if regression > limit + 1e-12:
            errors.append(f"guardrail_regression_exceeded:{metric}")
    return {"stage": 464, "pass": not errors, "errors": errors,
            "regressions": regressions, "limits": dict(maximum_regressions)}


def evaluate_stages_461_465(*, baseline: Mapping[str, Any], candidate: Mapping[str, Any],
                            changes: Sequence[Mapping[str, Any]], declared_primary_change: str,
                            direction: str, minimum_improvement: float,
                            guardrail_baseline: Mapping[str, float],
                            guardrail_candidate: Mapping[str, float],
                            maximum_regressions: Mapping[str, float]) -> dict[str, Any]:
    """465: aggregate improvement attribution; HOLD on any missing or failed evidence."""
    checks = [
        check_paired_comparison(baseline, candidate),
        check_change_isolation(changes, declared_primary_change),
        check_metric_improvement(baseline.get("metric_value"), candidate.get("metric_value"),
                                 direction=direction, minimum_improvement=minimum_improvement),
        check_guardrail_metrics(guardrail_baseline, guardrail_candidate, maximum_regressions),
    ]
    passed = all(item["pass"] for item in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 465, "status": "READY_FOR_REVIEW" if passed else "HOLD",
            "checks": checks, "seal": _seal(record), "causal_attribution_verified": False,
            "execution_authorized": False, "promotion_authorized": False,
            "proposal_only": True}
