"""Stages 321-325: evaluator ablation and paired task-level robustness gates."""
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


def stage321_check_leave_one_evaluator_out(*, evaluator_gains: Mapping,
                                           minimum_evaluators: int = 3,
                                           minimum_gain: float = 0.0,
                                           held: bool = False):
    """Require the declared gain threshold to survive removal of every evaluator."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluator_gains, Mapping)
            or isinstance(minimum_evaluators, bool) or not isinstance(minimum_evaluators, int)
            or minimum_evaluators < 3 or len(evaluator_gains) < minimum_evaluators
            or not _finite(minimum_gain) or minimum_gain < 0):
        return _blocked("evaluator gains or thresholds are invalid")
    gains = {}
    for evaluator, gain in evaluator_gains.items():
        if not isinstance(evaluator, str) or not evaluator.strip() or not _finite(gain):
            return _blocked("evaluator IDs and gains must be valid")
        gains[evaluator] = float(gain)
    overall = sum(gains.values()) / len(gains)
    leave_one_out = {
        evaluator: sum(value for key, value in gains.items() if key != evaluator) / (len(gains) - 1)
        for evaluator in sorted(gains)
    }
    passed = overall > minimum_gain and all(value > minimum_gain for value in leave_one_out.values())
    return _seal({
        "status": "LEAVE_ONE_EVALUATOR_OUT_ROBUST" if passed else "LEAVE_ONE_EVALUATOR_OUT_FRAGILE",
        "evaluator_count": len(gains), "overall_mean_gain": overall,
        "leave_one_out_mean_gains": leave_one_out, "minimum_gain": float(minimum_gain),
        "evaluator_identity_authenticated": False,
    })


def stage322_check_paired_task_gains(*, task_scores: Mapping,
                                     score_minimum: float = 0.0,
                                     score_maximum: float = 1.0,
                                     minimum_tasks: int = 10,
                                     minimum_mean_gain: float = 0.0,
                                     minimum_positive_fraction: float = 0.5,
                                     held: bool = False):
    """Validate exact paired scores and enforce mean-gain and positive-task share floors."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_scores, Mapping) or not task_scores
            or not _finite(score_minimum) or not _finite(score_maximum)
            or score_minimum >= score_maximum
            or isinstance(minimum_tasks, bool) or not isinstance(minimum_tasks, int) or minimum_tasks < 1
            or not _finite(minimum_mean_gain) or minimum_mean_gain < 0
            or not _finite(minimum_positive_fraction) or not 0 <= minimum_positive_fraction <= 1
            or len(task_scores) < minimum_tasks):
        return _blocked("paired score inputs or thresholds are invalid or insufficient")
    gains = {}
    for task, pair in task_scores.items():
        if (not isinstance(task, str) or not task.strip() or not isinstance(pair, Mapping)
                or set(pair) != {"baseline", "candidate"}
                or not _finite(pair["baseline"]) or not _finite(pair["candidate"])
                or not score_minimum <= pair["baseline"] <= score_maximum
                or not score_minimum <= pair["candidate"] <= score_maximum):
            return _blocked("each task requires bounded finite baseline and candidate scores")
        gains[task] = float(pair["candidate"] - pair["baseline"])
    mean_gain = sum(gains.values()) / len(gains)
    positive_fraction = sum(g > 0 for g in gains.values()) / len(gains)
    passed = mean_gain > minimum_mean_gain and positive_fraction >= minimum_positive_fraction
    return _seal({
        "status": "PAIRED_TASK_GAINS_VALID" if passed else "PAIRED_TASK_GAINS_BELOW_GATE",
        "task_count": len(gains), "mean_gain": mean_gain,
        "positive_task_fraction": positive_fraction,
        "minimum_mean_gain": float(minimum_mean_gain),
        "minimum_positive_fraction": float(minimum_positive_fraction),
        "task_scores_authenticated": False,
    })


def stage323_check_domain_gain_floors(*, domain_task_scores: Mapping,
                                      minimum_tasks_per_domain: int = 3,
                                      minimum_domain_gain: float = 0.0,
                                      held: bool = False):
    """Require every declared domain to meet task-count and mean paired-gain floors."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(domain_task_scores, Mapping) or not domain_task_scores
            or isinstance(minimum_tasks_per_domain, bool)
            or not isinstance(minimum_tasks_per_domain, int) or minimum_tasks_per_domain < 1
            or not _finite(minimum_domain_gain) or minimum_domain_gain < 0):
        return _blocked("domain score inputs or thresholds are invalid")
    results = {}
    for domain, tasks in domain_task_scores.items():
        if not isinstance(domain, str) or not domain.strip() or not isinstance(tasks, Mapping):
            return _blocked("domain IDs and task score mappings are malformed")
        if len(tasks) < minimum_tasks_per_domain:
            return _blocked("one or more domains have insufficient paired tasks")
        gains = []
        for task, pair in tasks.items():
            if (not isinstance(task, str) or not task.strip() or not isinstance(pair, Mapping)
                    or set(pair) != {"baseline", "candidate"}
                    or not _finite(pair["baseline"]) or not _finite(pair["candidate"])):
                return _blocked("domain task scores are malformed")
            gains.append(float(pair["candidate"] - pair["baseline"]))
        mean_gain = sum(gains) / len(gains)
        results[domain] = {"task_count": len(gains), "mean_gain": mean_gain}
    passed = all(row["mean_gain"] > minimum_domain_gain for row in results.values())
    return _seal({
        "status": "DOMAIN_GAIN_FLOORS_PASSED" if passed else "DOMAIN_GAIN_FLOOR_FAILED",
        "domain_results": dict(sorted(results.items())),
        "minimum_tasks_per_domain": minimum_tasks_per_domain,
        "minimum_domain_gain": float(minimum_domain_gain),
        "domain_labels_authenticated": False,
    })


def stage324_check_cross_domain_gain_dispersion(*, domain_result: Mapping,
                                                maximum_gain_spread: float = 0.25,
                                                held: bool = False):
    """Bound the spread between domain mean gains using a sealed Stage 323 result."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not _sealed(domain_result, "DOMAIN_GAIN_FLOORS_PASSED")
            or not _finite(maximum_gain_spread) or maximum_gain_spread < 0):
        return _blocked("sealed passing domain result and valid spread threshold required")
    try:
        values = [row["mean_gain"] for row in domain_result["domain_results"].values()]
        if not values or any(not _finite(value) for value in values):
            return _blocked("domain gain evidence is malformed")
        spread = max(values) - min(values)
    except (KeyError, TypeError, ValueError):
        return _blocked("domain gain evidence is malformed")
    passed = spread <= maximum_gain_spread
    return _seal({
        "status": "CROSS_DOMAIN_GAIN_SPREAD_PASSED" if passed else "CROSS_DOMAIN_GAIN_SPREAD_FAILED",
        "domain_result_digest": domain_result["result_digest"],
        "minimum_domain_gain": min(values), "maximum_domain_gain": max(values),
        "gain_spread": spread, "maximum_gain_spread": float(maximum_gain_spread),
        "domain_comparability_proven": False,
    })


def stage325_integrate_task_evaluator_robustness(*, evaluator_result: Mapping,
                                                 task_result: Mapping,
                                                 domain_result: Mapping,
                                                 dispersion_result: Mapping,
                                                 held: bool = False):
    """Fail closed unless all four sealed robustness checks pass; proposal-only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates = (
        (evaluator_result, "LEAVE_ONE_EVALUATOR_OUT_ROBUST"),
        (task_result, "PAIRED_TASK_GAINS_VALID"),
        (domain_result, "DOMAIN_GAIN_FLOORS_PASSED"),
        (dispersion_result, "CROSS_DOMAIN_GAIN_SPREAD_PASSED"),
    )
    if not all(_sealed(result, status) for result, status in gates):
        return _blocked("all four sealed evaluator/task/domain robustness gates must pass")
    return _seal({
        "status": "TASK_EVALUATOR_ROBUSTNESS_PASSED",
        "evidence_digests": [result["result_digest"] for result, _ in gates],
        "decision_scope": "proposal eligibility for separate review only",
        "evaluator_independence_proven": False, "task_representativeness_proven": False,
        "domain_comparability_proven": False, "causal_gain_proven": False,
        "recursive_self_improvement_proven": False, "asi_demonstrated": False,
    })
