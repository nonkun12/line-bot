"""Stages 331-335: longitudinal stability and distribution-shift robustness gates."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import math

_FALSE = {
    "proposal_only": True, "task_execution_authorized": False,
    "experiment_execution_authorized": False, "model_change_authorized": False,
    "merge_deploy_authorized": False, "hold_release_authorized": False,
}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _sealed(value, status):
    if not isinstance(value, Mapping) or value.get("status") != status:
        return False
    if any(value.get(k) is not v for k, v in _FALSE.items()):
        return False
    try:
        digest = value.get("result_digest")
        return (isinstance(digest, str) and len(digest) == 64
                and all(c in "0123456789abcdef" for c in digest)
                and digest == _hash({k: v for k, v in value.items() if k != "result_digest"}))
    except (TypeError, ValueError, OverflowError):
        return False


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def stage331_check_temporal_window_stability(*, window_gains: Mapping,
                                             minimum_windows: int = 3,
                                             minimum_window_gain: float = 0.0,
                                             maximum_window_spread: float = 0.25,
                                             held: bool = False):
    """Require each declared time window to pass and bound best-to-worst spread."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(window_gains, Mapping)
            or isinstance(minimum_windows, bool) or not isinstance(minimum_windows, int)
            or minimum_windows < 2 or len(window_gains) < minimum_windows
            or not _finite(minimum_window_gain) or not _finite(maximum_window_spread)
            or maximum_window_spread < 0):
        return _blocked("temporal window inputs or thresholds are invalid")
    gains = {}
    for window, gain in window_gains.items():
        if not isinstance(window, str) or not window.strip() or not _finite(gain):
            return _blocked("window labels and gains must be valid")
        gains[window] = float(gain)
    spread = max(gains.values()) - min(gains.values())
    passed = min(gains.values()) > minimum_window_gain and spread <= maximum_window_spread
    return _seal({
        "status": "TEMPORAL_WINDOW_STABILITY_PASSED" if passed else "TEMPORAL_WINDOW_STABILITY_FAILED",
        "window_count": len(gains), "minimum_window_gain_observed": min(gains.values()),
        "maximum_window_gain_observed": max(gains.values()), "window_gain_spread": spread,
        "minimum_window_gain": float(minimum_window_gain),
        "maximum_window_spread": float(maximum_window_spread),
        "window_timestamps_authenticated": False,
    })


def stage332_check_distribution_shift_robustness(*, shift_scenarios: Mapping,
                                                  maximum_declared_shift: float = 0.5,
                                                  minimum_shifted_gain: float = 0.0,
                                                  held: bool = False):
    """Require all declared shifted scenarios to stay within shift and gain bounds."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(shift_scenarios, Mapping) or not shift_scenarios
            or not _finite(maximum_declared_shift) or maximum_declared_shift < 0
            or not _finite(minimum_shifted_gain)):
        return _blocked("distribution-shift inputs or thresholds are invalid")
    rows = {}
    for scenario, values in shift_scenarios.items():
        if (not isinstance(scenario, str) or not scenario.strip() or not isinstance(values, Mapping)
                or set(values) != {"shift_magnitude", "gain"}
                or not _finite(values["shift_magnitude"]) or values["shift_magnitude"] < 0
                or not _finite(values["gain"])):
            return _blocked("each shift scenario requires finite nonnegative shift and finite gain")
        rows[scenario] = {
            "shift_magnitude": float(values["shift_magnitude"]),
            "gain": float(values["gain"]),
        }
    passed = all(row["shift_magnitude"] <= maximum_declared_shift
                 and row["gain"] > minimum_shifted_gain for row in rows.values())
    return _seal({
        "status": "DISTRIBUTION_SHIFT_ROBUST" if passed else "DISTRIBUTION_SHIFT_FRAGILE",
        "scenario_results": dict(sorted(rows.items())),
        "maximum_declared_shift": float(maximum_declared_shift),
        "minimum_shifted_gain": float(minimum_shifted_gain),
        "shift_measurement_authenticated": False,
    })


def stage333_check_bounded_measurement_perturbation(*, task_gains: Mapping,
                                                    maximum_score_perturbation: float = 0.02,
                                                    minimum_worst_case_gain: float = 0.0,
                                                    held: bool = False):
    """Apply a symmetric per-task error bound and require worst-case gains to pass."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_gains, Mapping) or not task_gains
            or not _finite(maximum_score_perturbation) or maximum_score_perturbation < 0
            or not _finite(minimum_worst_case_gain)):
        return _blocked("perturbation inputs or thresholds are invalid")
    gains = {}
    for task, gain in task_gains.items():
        if not isinstance(task, str) or not task.strip() or not _finite(gain):
            return _blocked("task IDs and gains must be finite")
        gains[task] = float(gain)
    worst = {task: gain - maximum_score_perturbation for task, gain in gains.items()}
    mean_worst = sum(worst.values()) / len(worst)
    passed = min(worst.values()) > minimum_worst_case_gain and mean_worst > minimum_worst_case_gain
    return _seal({
        "status": "BOUNDED_PERTURBATION_ROBUST" if passed else "BOUNDED_PERTURBATION_FRAGILE",
        "task_count": len(gains), "worst_case_task_gains": dict(sorted(worst.items())),
        "minimum_worst_case_gain_observed": min(worst.values()),
        "mean_worst_case_gain": mean_worst,
        "maximum_score_perturbation": float(maximum_score_perturbation),
        "perturbation_bound_calibrated": False,
    })


def stage334_check_subgroup_gain_gap(*, subgroup_gains: Mapping,
                                     minimum_subgroup_gain: float = 0.0,
                                     maximum_subgroup_gain_gap: float = 0.25,
                                     held: bool = False):
    """Require all declared subgroups to meet a gain floor and bounded gain gap."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(subgroup_gains, Mapping) or len(subgroup_gains) < 2
            or not _finite(minimum_subgroup_gain) or not _finite(maximum_subgroup_gain_gap)
            or maximum_subgroup_gain_gap < 0):
        return _blocked("subgroup inputs or thresholds are invalid")
    gains = {}
    for subgroup, gain in subgroup_gains.items():
        if not isinstance(subgroup, str) or not subgroup.strip() or not _finite(gain):
            return _blocked("subgroup labels and gains must be finite")
        gains[subgroup] = float(gain)
    gap = max(gains.values()) - min(gains.values())
    passed = min(gains.values()) > minimum_subgroup_gain and gap <= maximum_subgroup_gain_gap
    return _seal({
        "status": "SUBGROUP_GAIN_GAP_PASSED" if passed else "SUBGROUP_GAIN_GAP_FAILED",
        "subgroup_gains": dict(sorted(gains.items())),
        "minimum_subgroup_gain_observed": min(gains.values()),
        "maximum_subgroup_gain_gap_observed": gap,
        "minimum_subgroup_gain": float(minimum_subgroup_gain),
        "maximum_subgroup_gain_gap": float(maximum_subgroup_gain_gap),
        "subgroup_membership_authenticated": False,
        "fairness_or_parity_proven": False,
    })


def stage335_integrate_longitudinal_generalization(*, temporal_result: Mapping,
                                                   shift_result: Mapping,
                                                   perturbation_result: Mapping,
                                                   subgroup_result: Mapping,
                                                   held: bool = False):
    """Fail closed unless all longitudinal/generalization gates pass; proposal-only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates = (
        (temporal_result, "TEMPORAL_WINDOW_STABILITY_PASSED"),
        (shift_result, "DISTRIBUTION_SHIFT_ROBUST"),
        (perturbation_result, "BOUNDED_PERTURBATION_ROBUST"),
        (subgroup_result, "SUBGROUP_GAIN_GAP_PASSED"),
    )
    if not all(_sealed(result, status) for result, status in gates):
        return _blocked("all four sealed longitudinal/generalization gates must pass")
    return _seal({
        "status": "LONGITUDINAL_GENERALIZATION_PASSED",
        "evidence_digests": [result["result_digest"] for result, _ in gates],
        "decision_scope": "proposal eligibility for separate review only",
        "future_performance_proven": False, "distribution_invariance_proven": False,
        "fairness_or_parity_proven": False, "causal_gain_proven": False,
        "recursive_self_improvement_proven": False, "asi_demonstrated": False,
    })
