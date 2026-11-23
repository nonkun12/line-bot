"""Proposal-only calibration and regression controls for AI Factory stages 376-380."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_calibration_bins(bins: Sequence[Mapping[str, Any]], *,
                           maximum_expected_error: float) -> dict[str, Any]:
    """Stage 376: calculate weighted absolute calibration error from declared bins."""
    errors = []
    total = 0
    weighted_error = 0.0
    if not bins:
        errors.append("calibration_bins_empty")
    if not _finite_number(maximum_expected_error) or not 0 <= maximum_expected_error <= 1:
        errors.append("maximum_expected_error_invalid")
    for index, item in enumerate(bins):
        count, confidence, accuracy = item.get("count"), item.get("confidence"), item.get("accuracy")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            errors.append(f"bin_count_invalid:{index}")
            continue
        if not _finite_number(confidence) or not 0 <= confidence <= 1:
            errors.append(f"bin_confidence_invalid:{index}")
            continue
        if not _finite_number(accuracy) or not 0 <= accuracy <= 1:
            errors.append(f"bin_accuracy_invalid:{index}")
            continue
        total += count
        weighted_error += count * abs(confidence - accuracy)
    ece = weighted_error / total if total else None
    if ece is not None and _finite_number(maximum_expected_error) and ece > maximum_expected_error:
        errors.append("expected_calibration_error_exceeded")
    return {"stage": 376, "pass": not errors, "errors": errors,
            "sample_count": total, "expected_calibration_error": ece}


def check_confidence_intervals(intervals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 377: validate finite [0,1] intervals and point estimates."""
    errors = []
    if not intervals:
        errors.append("intervals_empty")
    for index, item in enumerate(intervals):
        lower, estimate, upper = item.get("lower"), item.get("estimate"), item.get("upper")
        if not all(_finite_number(x) and 0 <= x <= 1 for x in (lower, estimate, upper)):
            errors.append(f"interval_value_invalid:{index}")
            continue
        if lower > upper:
            errors.append(f"interval_order_invalid:{index}")
        if not lower <= estimate <= upper:
            errors.append(f"estimate_outside_interval:{index}")
    return {"stage": 377, "pass": not errors, "errors": errors,
            "interval_count": len(intervals)}


def check_subgroup_disparity(groups: Sequence[Mapping[str, Any]], *,
                             maximum_gap: float, minimum_group_size: int) -> dict[str, Any]:
    """Stage 378: bound max-min subgroup score gap with minimum declared sample sizes."""
    errors = []
    scores = []
    if len(groups) < 2:
        errors.append("at_least_two_groups_required")
    if not _finite_number(maximum_gap) or not 0 <= maximum_gap <= 1:
        errors.append("maximum_gap_invalid")
    if isinstance(minimum_group_size, bool) or not isinstance(minimum_group_size, int) or minimum_group_size <= 0:
        errors.append("minimum_group_size_invalid")
    for index, group in enumerate(groups):
        size, score = group.get("size"), group.get("score")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            errors.append(f"group_size_invalid:{index}")
        elif isinstance(minimum_group_size, int) and not isinstance(minimum_group_size, bool) and minimum_group_size > 0 and size < minimum_group_size:
            errors.append(f"group_below_minimum_size:{index}")
        if not _finite_number(score) or not 0 <= score <= 1:
            errors.append(f"group_score_invalid:{index}")
        else:
            scores.append(score)
    gap = max(scores) - min(scores) if len(scores) == len(groups) and scores else None
    if gap is not None and _finite_number(maximum_gap) and gap > maximum_gap:
        errors.append("subgroup_gap_exceeded")
    return {"stage": 378, "pass": not errors, "errors": errors, "observed_gap": gap}


def check_metric_regressions(metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 379: compare declared baseline/current values against per-metric tolerance."""
    errors = []
    results = []
    if not metrics:
        errors.append("metrics_empty")
    for index, item in enumerate(metrics):
        baseline, current = item.get("baseline"), item.get("current")
        direction, tolerance = item.get("direction"), item.get("maximum_regression")
        if not _finite_number(baseline) or not _finite_number(current):
            errors.append(f"metric_value_invalid:{index}")
            continue
        if direction not in ("higher", "lower"):
            errors.append(f"metric_direction_invalid:{index}")
            continue
        if not _finite_number(tolerance) or tolerance < 0:
            errors.append(f"maximum_regression_invalid:{index}")
            continue
        regression = baseline - current if direction == "higher" else current - baseline
        results.append({"index": index, "regression": max(0.0, regression),
                        "pass": regression <= tolerance})
        if regression > tolerance:
            errors.append(f"metric_regression_exceeded:{index}")
    return {"stage": 379, "pass": not errors, "errors": errors, "metrics": results}


def evaluate_stages_376_380(*, calibration_bins: Sequence[Mapping[str, Any]],
                            maximum_expected_error: float,
                            confidence_intervals: Sequence[Mapping[str, Any]],
                            subgroups: Sequence[Mapping[str, Any]],
                            maximum_subgroup_gap: float,
                            minimum_group_size: int,
                            metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 380: integrated statistical guard; never authorizes execution."""
    checks = [
        check_calibration_bins(calibration_bins, maximum_expected_error=maximum_expected_error),
        check_confidence_intervals(confidence_intervals),
        check_subgroup_disparity(subgroups, maximum_gap=maximum_subgroup_gap,
                                 minimum_group_size=minimum_group_size),
        check_metric_regressions(metrics),
    ]
    payload = {"checks": checks, "all_pass": all(item["pass"] for item in checks),
               "execution_authorized": False, "proposal_only": True}
    return {"stage": 380, "status": "PASS" if payload["all_pass"] else "BLOCKED",
            "checks": checks, "seal": _seal(payload),
            "execution_authorized": False, "proposal_only": True}
