"""Stages 326-330: measurement sensitivity and aggregation robustness gates."""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from itertools import combinations
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


def stage326_check_evaluator_coalition_ablation(*, evaluator_gains: Mapping,
                                                maximum_removed: int = 2,
                                                minimum_remaining_gain: float = 0.0,
                                                held: bool = False):
    """Require gain floor after every declared evaluator coalition removal."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluator_gains, Mapping) or len(evaluator_gains) < 3
            or isinstance(maximum_removed, bool) or not isinstance(maximum_removed, int)
            or maximum_removed < 1 or maximum_removed >= len(evaluator_gains)
            or maximum_removed > 3 or not _finite(minimum_remaining_gain)):
        return _blocked("coalition inputs or bounds are invalid")
    gains = {}
    for key, value in evaluator_gains.items():
        if not isinstance(key, str) or not key.strip() or not _finite(value):
            return _blocked("evaluator IDs and gains must be finite")
        gains[key] = float(value)
    tested = {}
    names = sorted(gains)
    for size in range(1, maximum_removed + 1):
        for removed in combinations(names, size):
            remaining = [value for key, value in gains.items() if key not in removed]
            tested[",".join(removed)] = sum(remaining) / len(remaining)
    worst = min(tested.values())
    return _seal({
        "status": "EVALUATOR_COALITION_ROBUST" if worst > minimum_remaining_gain else "EVALUATOR_COALITION_FRAGILE",
        "coalitions_tested": len(tested), "worst_remaining_mean_gain": worst,
        "minimum_remaining_gain": float(minimum_remaining_gain),
        "evaluator_identity_authenticated": False,
    })


def stage327_check_task_difficulty_strata(*, strata_scores: Mapping,
                                           minimum_tasks_per_stratum: int = 3,
                                           minimum_stratum_gain: float = 0.0,
                                           held: bool = False):
    """Require every caller-declared difficulty stratum to meet paired-gain floors."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(strata_scores, Mapping) or not strata_scores
            or isinstance(minimum_tasks_per_stratum, bool)
            or not isinstance(minimum_tasks_per_stratum, int) or minimum_tasks_per_stratum < 1
            or not _finite(minimum_stratum_gain)):
        return _blocked("strata inputs or thresholds are invalid")
    results = {}
    for stratum, tasks in strata_scores.items():
        if not isinstance(stratum, str) or not stratum.strip() or not isinstance(tasks, Mapping):
            return _blocked("stratum labels and task mappings are malformed")
        if len(tasks) < minimum_tasks_per_stratum:
            return _blocked("one or more strata have insufficient task coverage")
        gains = []
        for task_id, pair in tasks.items():
            if (not isinstance(task_id, str) or not task_id.strip() or not isinstance(pair, Mapping)
                    or set(pair) != {"baseline", "candidate"}
                    or not _finite(pair["baseline"]) or not _finite(pair["candidate"])):
                return _blocked("stratum paired scores are malformed")
            gains.append(float(pair["candidate"] - pair["baseline"]))
        results[stratum] = {"task_count": len(gains), "mean_gain": sum(gains) / len(gains)}
    passed = all(row["mean_gain"] > minimum_stratum_gain for row in results.values())
    return _seal({
        "status": "TASK_DIFFICULTY_STRATA_PASSED" if passed else "TASK_DIFFICULTY_STRATA_FAILED",
        "strata_results": dict(sorted(results.items())),
        "minimum_tasks_per_stratum": minimum_tasks_per_stratum,
        "minimum_stratum_gain": float(minimum_stratum_gain),
        "difficulty_labels_authenticated": False,
    })


def stage328_check_gain_threshold_sensitivity(*, task_gains: Mapping,
                                               gain_thresholds: list,
                                               minimum_positive_fraction: float = 0.5,
                                               held: bool = False):
    """Check positive-task share and mean gain over every declared gain threshold."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_gains, Mapping) or not task_gains
            or not isinstance(gain_thresholds, list) or not gain_thresholds
            or len(gain_thresholds) > 20
            or not _finite(minimum_positive_fraction)
            or not 0 <= minimum_positive_fraction <= 1
            or any(not _finite(v) for v in task_gains.values())
            or any(not _finite(v) for v in gain_thresholds)):
        return _blocked("gain sensitivity inputs are invalid")
    if len(set(gain_thresholds)) != len(gain_thresholds):
        return _blocked("gain thresholds must be unique")
    gains = [float(value) for value in task_gains.values()]
    rows = {}
    for threshold in sorted(gain_thresholds):
        fraction = sum(gain > threshold for gain in gains) / len(gains)
        mean = sum(gains) / len(gains)
        rows[str(float(threshold))] = {
            "mean_gain": mean, "fraction_above_threshold": fraction,
            "passed": mean > threshold and fraction >= minimum_positive_fraction,
        }
    passed = all(row["passed"] for row in rows.values())
    return _seal({
        "status": "GAIN_THRESHOLD_SENSITIVITY_PASSED" if passed else "GAIN_THRESHOLD_SENSITIVITY_FAILED",
        "threshold_results": rows, "task_count": len(gains),
        "minimum_positive_fraction": float(minimum_positive_fraction),
    })


def stage329_check_weight_concentration(*, weighted_task_gains: Mapping,
                                        maximum_weight_share: float = 0.25,
                                        minimum_weighted_gain: float = 0.0,
                                        held: bool = False):
    """Bound any single task's normalized weight share and weighted mean gain."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(weighted_task_gains, Mapping) or len(weighted_task_gains) < 2
            or not _finite(maximum_weight_share) or not 0 < maximum_weight_share <= 1
            or not _finite(minimum_weighted_gain)):
        return _blocked("weight concentration inputs or thresholds are invalid")
    rows = {}
    for task_id, row in weighted_task_gains.items():
        if (not isinstance(task_id, str) or not task_id.strip() or not isinstance(row, Mapping)
                or set(row) != {"gain", "weight"} or not _finite(row["gain"])
                or not _finite(row["weight"]) or row["weight"] <= 0):
            return _blocked("each task requires finite gain and positive finite weight")
        rows[task_id] = (float(row["gain"]), float(row["weight"]))
    total = sum(weight for _, weight in rows.values())
    shares = {key: weight / total for key, (_, weight) in rows.items()}
    weighted_gain = sum(gain * weight for gain, weight in rows.values()) / total
    max_share = max(shares.values())
    passed = max_share <= maximum_weight_share and weighted_gain > minimum_weighted_gain
    return _seal({
        "status": "WEIGHT_CONCENTRATION_PASSED" if passed else "WEIGHT_CONCENTRATION_FAILED",
        "weighted_mean_gain": weighted_gain, "maximum_observed_weight_share": max_share,
        "maximum_weight_share": float(maximum_weight_share),
        "minimum_weighted_gain": float(minimum_weighted_gain),
        "task_count": len(rows),
    })


def stage330_integrate_measurement_sensitivity(*, coalition_result: Mapping,
                                               strata_result: Mapping,
                                               threshold_result: Mapping,
                                               weight_result: Mapping,
                                               held: bool = False):
    """Fail closed unless all measurement-sensitivity gates pass; proposal-only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates = (
        (coalition_result, "EVALUATOR_COALITION_ROBUST"),
        (strata_result, "TASK_DIFFICULTY_STRATA_PASSED"),
        (threshold_result, "GAIN_THRESHOLD_SENSITIVITY_PASSED"),
        (weight_result, "WEIGHT_CONCENTRATION_PASSED"),
    )
    if not all(_sealed(result, status) for result, status in gates):
        return _blocked("all four sealed measurement-sensitivity gates must pass")
    return _seal({
        "status": "MEASUREMENT_SENSITIVITY_PASSED",
        "evidence_digests": [result["result_digest"] for result, _ in gates],
        "decision_scope": "proposal eligibility for separate review only",
        "sampling_validity_proven": False, "difficulty_labels_validated": False,
        "score_scale_comparability_proven": False, "causal_gain_proven": False,
        "recursive_self_improvement_proven": False, "asi_demonstrated": False,
    })
