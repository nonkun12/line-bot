"""Proposal-only evaluation-validity checks for AI Factory stages 411-415."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()


def _finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def check_metric_specifications(specifications: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 411: require unique, interpretable metric definitions and declared direction."""
    errors: list[str] = []
    seen: set[str] = set()
    if not specifications:
        errors.append("metric_specifications_empty")
    for i, item in enumerate(specifications):
        metric_id = item.get("metric_id")
        if not isinstance(metric_id, str) or not metric_id.strip():
            errors.append(f"metric_id_invalid:{i}")
        elif metric_id in seen:
            errors.append(f"metric_id_duplicate:{metric_id}")
        else:
            seen.add(metric_id)
        for field in ("definition", "unit"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"metric_{field}_missing:{metric_id if isinstance(metric_id, str) else i}")
        if item.get("direction") not in ("higher_is_better", "lower_is_better", "target_range"):
            errors.append(f"metric_direction_invalid:{metric_id if isinstance(metric_id, str) else i}")
        if item.get("aggregation") not in ("mean", "sum", "rate", "count", "median", "other"):
            errors.append(f"metric_aggregation_invalid:{metric_id if isinstance(metric_id, str) else i}")
    return {"stage": 411, "pass": not errors, "errors": errors, "metric_count": len(seen)}


def check_metric_denominators(observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 412: validate numerator/denominator arithmetic and declared sample coverage."""
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    if not observations:
        errors.append("metric_observations_empty")
    for i, item in enumerate(observations):
        metric_id, cohort = item.get("metric_id"), item.get("cohort_id")
        key = (metric_id, cohort)
        if not isinstance(metric_id, str) or not metric_id.strip():
            errors.append(f"observation_metric_id_invalid:{i}")
        if not isinstance(cohort, str) or not cohort.strip():
            errors.append(f"observation_cohort_id_invalid:{i}")
        if key in seen:
            errors.append(f"observation_duplicate:{metric_id}:{cohort}")
        else:
            seen.add(key)
        numerator, denominator, sample_count = (
            item.get("numerator"), item.get("denominator"), item.get("sample_count"))
        for field, value in (("numerator", numerator), ("denominator", denominator),
                             ("sample_count", sample_count)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{field}_invalid:{metric_id}:{cohort}")
        if isinstance(denominator, int) and not isinstance(denominator, bool):
            if denominator <= 0:
                errors.append(f"denominator_not_positive:{metric_id}:{cohort}")
            if isinstance(numerator, int) and not isinstance(numerator, bool):
                if numerator > denominator:
                    errors.append(f"numerator_exceeds_denominator:{metric_id}:{cohort}")
            if isinstance(sample_count, int) and not isinstance(sample_count, bool):
                if sample_count < denominator:
                    errors.append(f"sample_count_below_denominator:{metric_id}:{cohort}")
    return {"stage": 412, "pass": not errors, "errors": errors,
            "observation_count": len(seen)}


def check_uncertainty_intervals(intervals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 413: check declared point estimates and uncertainty bounds are finite and ordered."""
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    if not intervals:
        errors.append("uncertainty_intervals_empty")
    for i, item in enumerate(intervals):
        metric_id, cohort = item.get("metric_id"), item.get("cohort_id")
        key = (metric_id, cohort)
        if not isinstance(metric_id, str) or not metric_id.strip():
            errors.append(f"interval_metric_id_invalid:{i}")
        if not isinstance(cohort, str) or not cohort.strip():
            errors.append(f"interval_cohort_id_invalid:{i}")
        if key in seen:
            errors.append(f"interval_duplicate:{metric_id}:{cohort}")
        else:
            seen.add(key)
        lower, estimate, upper = item.get("lower"), item.get("estimate"), item.get("upper")
        if not all(_finite_number(v) for v in (lower, estimate, upper)):
            errors.append(f"interval_value_nonfinite_or_invalid:{metric_id}:{cohort}")
            continue
        if lower > estimate or estimate > upper:
            errors.append(f"interval_bounds_misordered:{metric_id}:{cohort}")
        method = item.get("method")
        if not isinstance(method, str) or not method.strip():
            errors.append(f"interval_method_missing:{metric_id}:{cohort}")
    return {"stage": 413, "pass": not errors, "errors": errors,
            "interval_count": len(seen)}


def check_comparison_compatibility(comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 414: require baseline/candidate comparisons to declare matching study context."""
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    if not comparisons:
        errors.append("comparisons_empty")
    for i, item in enumerate(comparisons):
        metric_id, cohort = item.get("metric_id"), item.get("cohort_id")
        key = (metric_id, cohort)
        if not isinstance(metric_id, str) or not metric_id.strip():
            errors.append(f"comparison_metric_id_invalid:{i}")
        if not isinstance(cohort, str) or not cohort.strip():
            errors.append(f"comparison_cohort_id_invalid:{i}")
        if key in seen:
            errors.append(f"comparison_duplicate:{metric_id}:{cohort}")
        else:
            seen.add(key)
        for field in ("baseline_protocol", "candidate_protocol", "baseline_population",
                      "candidate_population", "baseline_window", "candidate_window"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"comparison_{field}_missing:{metric_id}:{cohort}")
        for left, right, label in (
            ("baseline_protocol", "candidate_protocol", "protocol"),
            ("baseline_population", "candidate_population", "population"),
            ("baseline_window", "candidate_window", "window"),
        ):
            a, b = item.get(left), item.get(right)
            if isinstance(a, str) and isinstance(b, str) and a.strip() and b.strip() and a != b:
                errors.append(f"comparison_{label}_mismatch:{metric_id}:{cohort}")
    return {"stage": 414, "pass": not errors, "errors": errors,
            "comparison_count": len(seen)}


def evaluate_stages_411_415(*, metric_specifications: Sequence[Mapping[str, Any]],
                            observations: Sequence[Mapping[str, Any]],
                            uncertainty_intervals: Sequence[Mapping[str, Any]],
                            comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 415: aggregate evaluation-input validity; no claim of statistical validity."""
    checks = [
        check_metric_specifications(metric_specifications),
        check_metric_denominators(observations),
        check_uncertainty_intervals(uncertainty_intervals),
        check_comparison_compatibility(comparisons),
    ]
    errors: list[str] = []
    metric_ids = {x.get("metric_id") for x in metric_specifications
                  if isinstance(x.get("metric_id"), str)}
    for label, records in (("observation", observations),
                           ("interval", uncertainty_intervals),
                           ("comparison", comparisons)):
        used = {x.get("metric_id") for x in records if isinstance(x.get("metric_id"), str)}
        errors.extend(f"{label}_metric_not_registered:{x}" for x in sorted(used - metric_ids))
    all_pass = all(x["pass"] for x in checks) and not errors
    payload = {"checks": checks, "errors": errors, "all_pass": all_pass,
               "proposal_only": True, "execution_authorized": False,
               "promotion_authorized": False}
    return {"stage": 415, "status": "PASS" if all_pass else "BLOCKED",
            "checks": checks, "errors": errors, "seal": _seal(payload),
            "proposal_only": True, "execution_authorized": False,
            "promotion_authorized": False}
