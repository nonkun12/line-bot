"""Uncertainty, subgroup, robustness, and calibration declaration checks (456-460)."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_uncertainty_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """456: validate declared sample size, confidence level, and interval containment."""
    errors: list[str] = []
    count = summary.get("sample_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        errors.append("uncertainty_sample_count_invalid")
    confidence = summary.get("confidence_level")
    if not _number(confidence) or not 0 < confidence < 1:
        errors.append("uncertainty_confidence_level_invalid")
    lower, estimate, upper = (summary.get("lower_bound"), summary.get("estimate"),
                              summary.get("upper_bound"))
    if not all(_number(x) for x in (lower, estimate, upper)):
        errors.append("uncertainty_interval_non_numeric")
    elif not lower <= estimate <= upper:
        errors.append("uncertainty_interval_order_invalid")
    if not isinstance(summary.get("method"), str) or not summary.get("method", "").strip():
        errors.append("uncertainty_method_missing")
    return {"stage": 456, "pass": not errors, "errors": errors}


def check_subgroup_coverage(rows: Sequence[Mapping[str, Any]], *,
                            required_groups: Sequence[str], minimum_samples: int) -> dict[str, Any]:
    """457: ensure each predeclared subgroup has a minimum declared sample count."""
    errors: list[str] = []
    if not isinstance(minimum_samples, int) or isinstance(minimum_samples, bool) or minimum_samples < 1:
        errors.append("subgroup_minimum_samples_invalid")
        minimum = 1
    else:
        minimum = minimum_samples
    required = set(x for x in required_groups if isinstance(x, str) and x.strip())
    if len(required) != len(required_groups) or not required:
        errors.append("subgroup_required_groups_invalid")
    counts: dict[str, int] = {}
    for i, row in enumerate(rows):
        group, count = row.get("group_id"), row.get("sample_count")
        if not isinstance(group, str) or not group.strip():
            errors.append(f"subgroup_id_invalid:{i}")
            continue
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"subgroup_sample_count_invalid:{group}")
            continue
        counts[group] = counts.get(group, 0) + count
    for group in sorted(required - set(counts)):
        errors.append(f"subgroup_missing:{group}")
    for group in sorted(required & set(counts)):
        if counts[group] < minimum:
            errors.append(f"subgroup_under_sampled:{group}")
    return {"stage": 457, "pass": not errors, "errors": errors,
            "declared_group_counts": counts, "required_groups": sorted(required)}


def check_perturbation_robustness(rows: Sequence[Mapping[str, Any]], *,
                                  required_scenarios: Sequence[str],
                                  minimum_success_rate: float) -> dict[str, Any]:
    """458: validate coverage and declared success rate for each required perturbation."""
    errors: list[str] = []
    if not _number(minimum_success_rate) or not 0 <= minimum_success_rate <= 1:
        errors.append("robustness_threshold_invalid")
        threshold = 1.0
    else:
        threshold = float(minimum_success_rate)
    required = set(x for x in required_scenarios if isinstance(x, str) and x.strip())
    if len(required) != len(required_scenarios) or not required:
        errors.append("robustness_scenarios_invalid")
    found: dict[str, float] = {}
    for i, row in enumerate(rows):
        scenario = row.get("scenario_id")
        rate = row.get("success_rate")
        if not isinstance(scenario, str) or not scenario.strip():
            errors.append(f"robustness_scenario_id_invalid:{i}")
        elif scenario in found:
            errors.append(f"robustness_scenario_duplicate:{scenario}")
        elif not _number(rate) or not 0 <= rate <= 1:
            errors.append(f"robustness_rate_invalid:{scenario}")
        else:
            found[scenario] = float(rate)
    for scenario in sorted(required - set(found)):
        errors.append(f"robustness_scenario_missing:{scenario}")
    for scenario in sorted(required & set(found)):
        if found[scenario] < threshold:
            errors.append(f"robustness_threshold_failed:{scenario}")
    return {"stage": 458, "pass": not errors, "errors": errors,
            "scenario_rates": found, "minimum_success_rate": threshold}


def check_calibration_bins(bins: Sequence[Mapping[str, Any]], *,
                           maximum_expected_calibration_error: float) -> dict[str, Any]:
    """459: calculate weighted absolute calibration gap from declared bins."""
    errors: list[str] = []
    if (not _number(maximum_expected_calibration_error)
            or not 0 <= maximum_expected_calibration_error <= 1):
        errors.append("calibration_threshold_invalid")
        threshold = 0.0
    else:
        threshold = float(maximum_expected_calibration_error)
    total = 0
    weighted_gap = 0.0
    for i, item in enumerate(bins):
        count = item.get("count")
        confidence, accuracy = item.get("mean_confidence"), item.get("observed_accuracy")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"calibration_count_invalid:{i}")
            continue
        if not _number(confidence) or not 0 <= confidence <= 1:
            errors.append(f"calibration_confidence_invalid:{i}")
            continue
        if not _number(accuracy) or not 0 <= accuracy <= 1:
            errors.append(f"calibration_accuracy_invalid:{i}")
            continue
        total += count
        weighted_gap += count * abs(float(confidence) - float(accuracy))
    if total == 0:
        errors.append("calibration_samples_empty")
        ece = None
    else:
        ece = weighted_gap / total
        if ece > threshold:
            errors.append("calibration_error_above_threshold")
    return {"stage": 459, "pass": not errors, "errors": errors,
            "expected_calibration_error": ece, "sample_count": total,
            "maximum_expected_calibration_error": threshold}


def evaluate_stages_456_460(*, uncertainty: Mapping[str, Any],
                            subgroup_rows: Sequence[Mapping[str, Any]],
                            required_groups: Sequence[str], minimum_group_samples: int,
                            perturbation_rows: Sequence[Mapping[str, Any]],
                            required_scenarios: Sequence[str], minimum_success_rate: float,
                            calibration_bins: Sequence[Mapping[str, Any]],
                            maximum_expected_calibration_error: float) -> dict[str, Any]:
    """460: aggregate bounded robustness/uncertainty declarations; no capability certification."""
    checks = [
        check_uncertainty_summary(uncertainty),
        check_subgroup_coverage(subgroup_rows, required_groups=required_groups,
                                minimum_samples=minimum_group_samples),
        check_perturbation_robustness(perturbation_rows, required_scenarios=required_scenarios,
                                      minimum_success_rate=minimum_success_rate),
        check_calibration_bins(calibration_bins,
                               maximum_expected_calibration_error=maximum_expected_calibration_error),
    ]
    passed = all(x["pass"] for x in checks)
    report = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 460, "status": "PASS" if passed else "BLOCKED",
            "checks": checks, "seal": _digest(report),
            "statistical_validity_verified": False, "generalization_verified": False,
            "capability_claim_authorized": False, "execution_authorized": False,
            "promotion_authorized": False, "proposal_only": True}
