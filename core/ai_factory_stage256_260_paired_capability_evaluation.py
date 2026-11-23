"""Stages 256-260: reproducible paired capability evaluation.

The stages evaluate already-recorded outputs. They do not run models, alter weights,
or authorize experiments. Confidence bounds are conservative Hoeffding bounds for
paired per-task score differences in [-1, 1].
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from collections.abc import Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")
_FALSE = {
    "proposal_only": True, "task_execution_authorized": False,
    "experiment_execution_authorized": False, "model_change_authorized": False,
    "merge_deploy_authorized": False, "hold_release_authorized": False,
}


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    body = {k: v for k, v in result.items() if k != "result_digest"}
    result["result_digest"] = sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return result


def _valid(result, expected_status):
    if not isinstance(result, Mapping) or result.get("status") != expected_status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    claimed = result.get("result_digest")
    if not _digest(claimed):
        return False
    try:
        body = {k: v for k, v in result.items() if k != "result_digest"}
        actual = sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        return False
    return claimed == actual


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stage256_preregister_evaluation(*, protocol_id: str, metric_name: str,
                                    metric_direction: str, minimum_gain: float,
                                    alpha: float, minimum_pairs: int,
                                    task_set_digest: str, held: bool = False):
    """Freeze evaluation parameters and task-set identity before scoring."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(protocol_id, str) or not protocol_id.strip()
            or not isinstance(metric_name, str) or not metric_name.strip()
            or metric_direction not in {"higher_is_better", "lower_is_better"}
            or not _finite_number(minimum_gain) or minimum_gain <= 0
            or not _finite_number(alpha) or not 0 < alpha < 0.5
            or isinstance(minimum_pairs, bool) or not isinstance(minimum_pairs, int) or minimum_pairs < 30
            or not _digest(task_set_digest)):
        return _blocked("invalid preregistered metric, threshold, sample size or task-set digest")
    protocol = {
        "protocol_id": protocol_id, "metric_name": metric_name,
        "metric_direction": metric_direction, "minimum_gain": float(minimum_gain),
        "alpha": float(alpha), "minimum_pairs": minimum_pairs,
        "task_set_digest": task_set_digest,
    }
    return _seal({
        "status": "EVALUATION_PREREGISTERED",
        "protocol": protocol,
        "protocol_digest": sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    })


def stage257_validate_paired_results(*, preregistration: Mapping, observations: Sequence[Mapping],
                                     held: bool = False):
    """Validate one baseline and one candidate score for every preregistered task."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _valid(preregistration, "EVALUATION_PREREGISTERED"):
        return _blocked("preregistration digest or authority flags invalid")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)) or not observations:
        return _blocked("paired observations are required")
    protocol = preregistration["protocol"]
    task_ids, normalized = set(), []
    for row in observations:
        if not isinstance(row, Mapping):
            return _blocked("each observation must be a mapping")
        task_id, task_digest = row.get("task_id"), row.get("task_digest")
        baseline, candidate = row.get("baseline_score"), row.get("candidate_score")
        if (not isinstance(task_id, str) or not task_id.strip() or task_id in task_ids
                or not _digest(task_digest) or not _finite_number(baseline)
                or not _finite_number(candidate) or not 0 <= baseline <= 1
                or not 0 <= candidate <= 1):
            return _blocked("invalid or duplicate task identity, digest, or score")
        task_ids.add(task_id)
        normalized.append({
            "task_id": task_id, "task_digest": task_digest,
            "baseline_score": float(baseline), "candidate_score": float(candidate),
        })
    if len(normalized) < protocol["minimum_pairs"]:
        return _blocked("paired sample count below preregistered minimum")
    normalized.sort(key=lambda row: row["task_id"])
    task_set_digest = sha256(json.dumps(
        [{"task_id": row["task_id"], "task_digest": row["task_digest"]} for row in normalized],
        sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    if task_set_digest != protocol["task_set_digest"]:
        return _blocked("observed task set differs from preregistered task set")
    payload_digest = sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return _seal({
        "status": "PAIRED_RESULTS_VALIDATED", "protocol_digest": preregistration["protocol_digest"],
        "task_set_digest": task_set_digest, "observation_count": len(normalized),
        "observations": normalized, "observations_digest": payload_digest,
    })


def stage258_estimate_paired_gain(*, preregistration: Mapping, paired_results: Mapping,
                                  held: bool = False):
    """Estimate direction-adjusted paired gain and a conservative Hoeffding interval."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _valid(preregistration, "EVALUATION_PREREGISTERED") or not _valid(paired_results, "PAIRED_RESULTS_VALIDATED"):
        return _blocked("preregistration or paired result integrity invalid")
    if paired_results["protocol_digest"] != preregistration["protocol_digest"]:
        return _blocked("protocol digest mismatch")
    direction = preregistration["protocol"]["metric_direction"]
    diffs = [
        (row["candidate_score"] - row["baseline_score"])
        * (1 if direction == "higher_is_better" else -1)
        for row in paired_results["observations"]
    ]
    n = len(diffs)
    mean = sum(diffs) / n
    alpha = preregistration["protocol"]["alpha"]
    radius = math.sqrt(2.0 * math.log(2.0 / alpha) / n)
    lower, upper = max(-1.0, mean - radius), min(1.0, mean + radius)
    return _seal({
        "status": "PAIRED_GAIN_ESTIMATED", "protocol_digest": preregistration["protocol_digest"],
        "observations_digest": paired_results["observations_digest"],
        "sample_count": n, "mean_gain": mean, "confidence_level": 1.0 - alpha,
        "lower_bound": lower, "upper_bound": upper,
        "bound_method": "two-sided Hoeffding; paired differences bounded in [-1,1]",
    })


def stage259_gate_capability_gain(*, preregistration: Mapping, estimate: Mapping,
                                  held: bool = False):
    """Require the conservative lower bound to exceed the preregistered gain."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _valid(preregistration, "EVALUATION_PREREGISTERED") or not _valid(estimate, "PAIRED_GAIN_ESTIMATED"):
        return _blocked("preregistration or estimate integrity invalid")
    if estimate["protocol_digest"] != preregistration["protocol_digest"]:
        return _blocked("protocol digest mismatch")
    threshold = preregistration["protocol"]["minimum_gain"]
    passed = estimate["lower_bound"] > threshold
    return _seal({
        "status": "CAPABILITY_GAIN_SUPPORTED" if passed else "CAPABILITY_GAIN_NOT_ESTABLISHED",
        "protocol_digest": preregistration["protocol_digest"],
        "estimate_digest": estimate["result_digest"],
        "minimum_gain": threshold, "lower_bound": estimate["lower_bound"],
        "recommendation": "eligible for independent replication review" if passed else "collect more evidence or revise the hypothesis",
        "model_change_authorized": False,
    })


def stage260_capability_evidence_package(*, preregistration: Mapping, paired_results: Mapping,
                                         estimate: Mapping, gate: Mapping, held: bool = False):
    """Seal a complete evidence package; never claim RSI/ASI or authorize mutation."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not _valid(preregistration, "EVALUATION_PREREGISTERED")
            or not _valid(paired_results, "PAIRED_RESULTS_VALIDATED")
            or not _valid(estimate, "PAIRED_GAIN_ESTIMATED")
            or not _valid(gate, gate.get("status") if isinstance(gate, Mapping) else "")):
        return _blocked("one or more stage results failed integrity validation")
    digest = preregistration["protocol_digest"]
    if any(item["protocol_digest"] != digest for item in (paired_results, estimate, gate)):
        return _blocked("cross-stage protocol identity mismatch")
    if estimate["observations_digest"] != paired_results["observations_digest"] or gate["estimate_digest"] != estimate["result_digest"]:
        return _blocked("cross-stage evidence linkage mismatch")
    return _seal({
        "status": "CAPABILITY_EVIDENCE_PACKAGE_READY",
        "protocol_digest": digest, "task_set_digest": paired_results["task_set_digest"],
        "observations_digest": paired_results["observations_digest"],
        "estimate_digest": estimate["result_digest"], "gate_status": gate["status"],
        "sample_count": estimate["sample_count"], "mean_gain": estimate["mean_gain"],
        "lower_bound": estimate["lower_bound"], "upper_bound": estimate["upper_bound"],
        "requires_independent_replication": True,
        "rsi_or_asi_demonstrated": False,
    })
