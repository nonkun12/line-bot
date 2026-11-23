"""Stages 311-315: sampling, evaluator assignment, config and attrition gates.

All inputs are caller-supplied declarations. These are evidence-quality screens;
they never execute tasks or authorize experiments, model changes, HOLD release,
merge or deployment.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
import math

_FALSE = {
    "proposal_only": True,
    "task_execution_authorized": False,
    "experiment_execution_authorized": False,
    "model_change_authorized": False,
    "merge_deploy_authorized": False,
    "hold_release_authorized": False,
}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _sealed(value, status):
    if not isinstance(value, Mapping) or value.get("status") != status:
        return False
    if any(value.get(key) is not flag for key, flag in _FALSE.items()):
        return False
    try:
        return _digest(value.get("result_digest")) and value["result_digest"] == _hash(
            {key: item for key, item in value.items() if key != "result_digest"}
        )
    except (TypeError, ValueError, OverflowError):
        return False


def stage311_check_inclusion_probabilities(*, sampling_design: str,
                                           baseline_probabilities: Mapping,
                                           candidate_probabilities: Mapping,
                                           minimum_probability: float = 0.001,
                                           maximum_probability: float = 1.0,
                                           held: bool = False):
    """Require a declared design and valid positive probabilities for every paired task."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(sampling_design, str) or not sampling_design.strip()
            or not isinstance(baseline_probabilities, Mapping)
            or not isinstance(candidate_probabilities, Mapping)
            or not baseline_probabilities
            or set(baseline_probabilities) != set(candidate_probabilities)
            or isinstance(minimum_probability, bool) or not isinstance(minimum_probability, (int, float))
            or not math.isfinite(minimum_probability)
            or isinstance(maximum_probability, bool) or not isinstance(maximum_probability, (int, float))
            or not math.isfinite(maximum_probability)
            or not 0 < minimum_probability <= maximum_probability <= 1):
        return _blocked("sampling design, task keys or probability bounds are invalid")
    if any(not isinstance(task_id, str) or not task_id.strip() for task_id in baseline_probabilities):
        return _blocked("task identifiers must be nonempty strings")
    rows = {}
    for task_id in sorted(baseline_probabilities):
        bp, cp = baseline_probabilities[task_id], candidate_probabilities[task_id]
        if any(isinstance(p, bool) or not isinstance(p, (int, float))
               or not math.isfinite(p) or not minimum_probability <= p <= maximum_probability
               for p in (bp, cp)):
            return _blocked("every inclusion probability must be finite, positive and within bounds")
        rows[task_id] = {"baseline": float(bp), "candidate": float(cp)}
    return _seal({
        "status": "SAMPLING_PROBABILITIES_VALID",
        "sampling_design": sampling_design.strip(),
        "paired_task_count": len(rows), "probabilities": rows,
        "randomization_independently_verified": False,
    })


def stage312_check_evaluator_assignment_balance(*, evaluator_tasks: Mapping,
                                                minimum_tasks_per_evaluator: int = 1,
                                                maximum_task_share: float = 0.80,
                                                minimum_evaluators: int = 2,
                                                held: bool = False):
    """Require multiple evaluators, minimum workloads and no dominant assignment share."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluator_tasks, Mapping) or not evaluator_tasks
            or isinstance(minimum_tasks_per_evaluator, bool)
            or not isinstance(minimum_tasks_per_evaluator, int) or minimum_tasks_per_evaluator < 1
            or isinstance(minimum_evaluators, bool) or not isinstance(minimum_evaluators, int)
            or minimum_evaluators < 2
            or isinstance(maximum_task_share, bool) or not isinstance(maximum_task_share, (int, float))
            or not math.isfinite(maximum_task_share) or not 0 < maximum_task_share <= 1):
        return _blocked("evaluator assignment inputs or thresholds are invalid")
    if len(evaluator_tasks) < minimum_evaluators:
        return _blocked("too few declared evaluators")
    rows, all_tasks = {}, []
    for evaluator, tasks in evaluator_tasks.items():
        if not isinstance(evaluator, str) or not evaluator.strip() or not isinstance(tasks, (list, tuple)):
            return _blocked("evaluator IDs and task assignments are malformed")
        if len(tasks) < minimum_tasks_per_evaluator or any(not isinstance(t, str) or not t.strip() for t in tasks):
            return _blocked("each evaluator must have enough valid task assignments")
        if len(set(tasks)) != len(tasks):
            return _blocked("duplicate task assignment within evaluator")
        rows[evaluator] = len(tasks)
        all_tasks.extend(tasks)
    total = sum(rows.values())
    shares = {key: value / total for key, value in rows.items()}
    passed = max(shares.values()) <= maximum_task_share
    return _seal({
        "status": "EVALUATOR_ASSIGNMENT_BALANCED" if passed else "EVALUATOR_ASSIGNMENT_IMBALANCED",
        "evaluator_count": len(rows), "assignment_count": total,
        "task_counts": {key: rows[key] for key in sorted(rows)},
        "maximum_observed_share": max(shares.values()),
        "maximum_task_share": float(maximum_task_share),
        "evaluator_independence_proven": False,
    })


def stage313_check_configuration_scope(*, baseline_invariant_digest: str,
                                       candidate_invariant_digest: str,
                                       changed_fields: list,
                                       allowed_change_fields: list,
                                       held: bool = False):
    """Require invariant config parity and explicitly scoped declared changes."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not _digest(baseline_invariant_digest) or not _digest(candidate_invariant_digest)
            or not isinstance(changed_fields, list) or not isinstance(allowed_change_fields, list)
            or any(not isinstance(x, str) or not x.strip() for x in changed_fields + allowed_change_fields)
            or len(set(changed_fields)) != len(changed_fields)
            or len(set(allowed_change_fields)) != len(allowed_change_fields)):
        return _blocked("configuration digests or change declarations are invalid")
    if baseline_invariant_digest != candidate_invariant_digest:
        status = "INVARIANT_CONFIGURATION_DRIFT"
    elif not set(changed_fields).issubset(set(allowed_change_fields)):
        status = "UNSCOPED_CONFIGURATION_CHANGE"
    else:
        status = "CONFIGURATION_SCOPE_VALID"
    return _seal({
        "status": status, "invariant_configuration_parity": baseline_invariant_digest == candidate_invariant_digest,
        "changed_fields": sorted(changed_fields), "allowed_change_fields": sorted(allowed_change_fields),
        "configuration_source_authenticated": False,
    })


def stage314_check_paired_attrition(*, task_presence: Mapping,
                                   maximum_attrition_gap: float = 0.05,
                                   minimum_tasks: int = 10, held: bool = False):
    """Compare baseline/candidate task attrition on the same declared task universe."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_presence, Mapping) or not task_presence
            or isinstance(maximum_attrition_gap, bool)
            or not isinstance(maximum_attrition_gap, (int, float))
            or not math.isfinite(maximum_attrition_gap) or not 0 <= maximum_attrition_gap <= 1
            or isinstance(minimum_tasks, bool) or not isinstance(minimum_tasks, int) or minimum_tasks < 1
            or len(task_presence) < minimum_tasks):
        return _blocked("paired task universe or attrition thresholds are invalid or insufficient")
    baseline_missing = candidate_missing = 0
    for task_id, presence in task_presence.items():
        if (not isinstance(task_id, str) or not task_id.strip() or not isinstance(presence, Mapping)
                or set(presence) != {"baseline", "candidate"}
                or any(type(presence[k]) is not bool for k in ("baseline", "candidate"))):
            return _blocked("each task requires boolean baseline and candidate presence")
        baseline_missing += not presence["baseline"]
        candidate_missing += not presence["candidate"]
    n = len(task_presence)
    b_rate, c_rate = baseline_missing / n, candidate_missing / n
    gap = abs(b_rate - c_rate)
    passed = gap <= maximum_attrition_gap
    return _seal({
        "status": "PAIRED_ATTRITION_PARITY_PASSED" if passed else "PAIRED_ATTRITION_GAP_FAILED",
        "task_count": n, "baseline_attrition_rate": b_rate,
        "candidate_attrition_rate": c_rate, "absolute_attrition_gap": gap,
        "maximum_attrition_gap": float(maximum_attrition_gap),
        "attrition_cause_verified": False,
    })


def stage315_integrate_sampling_evaluator_controls(*, sampling_result: Mapping,
                                                     evaluator_result: Mapping,
                                                     configuration_result: Mapping,
                                                     attrition_result: Mapping,
                                                     held: bool = False):
    """Fail closed unless all four sealed controls pass; proposal eligibility only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates = (
        (sampling_result, "SAMPLING_PROBABILITIES_VALID"),
        (evaluator_result, "EVALUATOR_ASSIGNMENT_BALANCED"),
        (configuration_result, "CONFIGURATION_SCOPE_VALID"),
        (attrition_result, "PAIRED_ATTRITION_PARITY_PASSED"),
    )
    if not all(_sealed(result, status) for result, status in gates):
        return _blocked("all four sealed sampling/evaluator/configuration/attrition gates must pass")
    return _seal({
        "status": "SAMPLING_EVALUATOR_CONTROLS_PASSED",
        "evidence_digests": [result["result_digest"] for result, _ in gates],
        "decision_scope": "proposal eligibility for separate review only",
        "sampling_randomization_proven": False, "evaluator_independence_proven": False,
        "configuration_authenticity_proven": False, "attrition_mechanism_proven": False,
        "capability_gain_proven": False, "recursive_self_improvement_proven": False,
        "asi_demonstrated": False,
    })
