"""Stages 316-320: stratified sampling, evaluator overlap and attrition sensitivity.

Caller-supplied evidence screens only. No execution or authorization is granted.
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


def stage316_check_stratified_sampling(*, task_strata: Mapping,
                                       inclusion_probabilities: Mapping,
                                       minimum_tasks_per_stratum: int = 2,
                                       minimum_probability: float = 0.001,
                                       held: bool = False):
    """Require exact task coverage, valid strata and positive inclusion probabilities."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(task_strata, Mapping) or not task_strata
            or not isinstance(inclusion_probabilities, Mapping)
            or set(task_strata) != set(inclusion_probabilities)
            or isinstance(minimum_tasks_per_stratum, bool)
            or not isinstance(minimum_tasks_per_stratum, int) or minimum_tasks_per_stratum < 1
            or isinstance(minimum_probability, bool)
            or not isinstance(minimum_probability, (int, float))
            or not math.isfinite(minimum_probability) or not 0 < minimum_probability <= 1):
        return _blocked("stratified sampling inputs or thresholds are invalid")
    if any(not isinstance(k, str) or not k.strip() for k in task_strata):
        return _blocked("task identifiers must be nonempty strings")
    counts = {}
    for task_id, stratum in task_strata.items():
        probability = inclusion_probabilities[task_id]
        if (not isinstance(stratum, str) or not stratum.strip()
                or isinstance(probability, bool) or not isinstance(probability, (int, float))
                or not math.isfinite(probability) or not minimum_probability <= probability <= 1):
            return _blocked("each task needs a valid stratum and bounded positive probability")
        counts[stratum] = counts.get(stratum, 0) + 1
    if min(counts.values()) < minimum_tasks_per_stratum:
        return _blocked("one or more strata have insufficient task coverage")
    return _seal({
        "status": "STRATIFIED_SAMPLING_VALID",
        "task_count": len(task_strata), "stratum_counts": dict(sorted(counts.items())),
        "stratum_count": len(counts), "minimum_tasks_per_stratum": minimum_tasks_per_stratum,
        "sampling_frame_authenticated": False, "random_selection_verified": False,
    })


def stage317_check_evaluator_overlap(*, evaluator_tasks: Mapping,
                                     minimum_shared_tasks: int = 1,
                                     maximum_pairwise_jaccard: float = 1.0,
                                     minimum_evaluators: int = 2,
                                     held: bool = False):
    """Quantify declared pairwise task overlap without claiming evaluator independence."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluator_tasks, Mapping) or len(evaluator_tasks) < minimum_evaluators
            or isinstance(minimum_evaluators, bool) or not isinstance(minimum_evaluators, int)
            or minimum_evaluators < 2 or isinstance(minimum_shared_tasks, bool)
            or not isinstance(minimum_shared_tasks, int) or minimum_shared_tasks < 0
            or isinstance(maximum_pairwise_jaccard, bool)
            or not isinstance(maximum_pairwise_jaccard, (int, float))
            or not math.isfinite(maximum_pairwise_jaccard)
            or not 0 <= maximum_pairwise_jaccard <= 1):
        return _blocked("evaluator overlap inputs or thresholds are invalid")
    sets = {}
    for evaluator, tasks in evaluator_tasks.items():
        if (not isinstance(evaluator, str) or not evaluator.strip()
                or not isinstance(tasks, (list, tuple)) or not tasks
                or any(not isinstance(t, str) or not t.strip() for t in tasks)
                or len(set(tasks)) != len(tasks)):
            return _blocked("evaluator task lists must contain unique nonempty task IDs")
        sets[evaluator] = set(tasks)
    pairs = {}
    for i, left in enumerate(sorted(sets)):
        for right in sorted(sets)[i + 1:]:
            shared = len(sets[left] & sets[right])
            union = len(sets[left] | sets[right])
            jaccard = shared / union if union else 0.0
            pairs[f"{left}|{right}"] = {"shared_tasks": shared, "jaccard": jaccard}
    if any(row["shared_tasks"] < minimum_shared_tasks
           or row["jaccard"] > maximum_pairwise_jaccard for row in pairs.values()):
        status = "EVALUATOR_OVERLAP_OUT_OF_BOUNDS"
    else:
        status = "EVALUATOR_OVERLAP_WITHIN_BOUNDS"
    return _seal({
        "status": status, "evaluator_count": len(sets), "pairwise_overlap": pairs,
        "evaluator_independence_proven": False, "blinding_proven": False,
    })


def stage318_check_evaluator_domain_coverage(*, evaluator_domain_counts: Mapping,
                                             required_domains: list,
                                             minimum_per_evaluator_domain: int = 1,
                                             minimum_evaluators_per_domain: int = 2,
                                             held: bool = False):
    """Require each required domain to be covered by enough evaluators and observations."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluator_domain_counts, Mapping) or not evaluator_domain_counts
            or not isinstance(required_domains, list) or not required_domains
            or any(not isinstance(d, str) or not d.strip() for d in required_domains)
            or len(set(required_domains)) != len(required_domains)
            or isinstance(minimum_per_evaluator_domain, bool)
            or not isinstance(minimum_per_evaluator_domain, int) or minimum_per_evaluator_domain < 1
            or isinstance(minimum_evaluators_per_domain, bool)
            or not isinstance(minimum_evaluators_per_domain, int) or minimum_evaluators_per_domain < 1):
        return _blocked("domain coverage inputs or thresholds are invalid")
    coverage = {domain: 0 for domain in required_domains}
    normalized = {}
    for evaluator, domains in evaluator_domain_counts.items():
        if not isinstance(evaluator, str) or not evaluator.strip() or not isinstance(domains, Mapping):
            return _blocked("evaluator/domain counts are malformed")
        normalized[evaluator] = {}
        for domain, count in domains.items():
            if (domain not in coverage or isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                return _blocked("unexpected domain or invalid task count")
            normalized[evaluator][domain] = count
            if count >= minimum_per_evaluator_domain:
                coverage[domain] += 1
    if any(coverage[d] < minimum_evaluators_per_domain for d in required_domains):
        return _blocked("one or more required domains lack evaluator coverage")
    return _seal({
        "status": "EVALUATOR_DOMAIN_COVERAGE_VALID",
        "required_domains": sorted(required_domains),
        "evaluator_coverage_counts": dict(sorted(coverage.items())),
        "minimum_per_evaluator_domain": minimum_per_evaluator_domain,
        "evaluator_independence_proven": False,
    })


def stage319_check_attrition_sensitivity(*, baseline_observed_scores: list,
                                         candidate_observed_scores: list,
                                         baseline_missing_count: int,
                                         candidate_missing_count: int,
                                         score_minimum: float = 0.0,
                                         score_maximum: float = 1.0,
                                         minimum_tasks: int = 10,
                                         minimum_worst_case_gain: float = 0.0,
                                         held: bool = False):
    """Bound candidate-minus-baseline gain under worst-case scores for missing outcomes."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    numeric = (score_minimum, score_maximum, minimum_worst_case_gain)
    if (not isinstance(baseline_observed_scores, list) or not isinstance(candidate_observed_scores, list)
            or isinstance(baseline_missing_count, bool) or not isinstance(baseline_missing_count, int)
            or baseline_missing_count < 0 or isinstance(candidate_missing_count, bool)
            or not isinstance(candidate_missing_count, int) or candidate_missing_count < 0
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in numeric)
            or score_minimum >= score_maximum or minimum_worst_case_gain < 0
            or isinstance(minimum_tasks, bool) or not isinstance(minimum_tasks, int) or minimum_tasks < 1):
        return _blocked("attrition sensitivity inputs or bounds are invalid")
    for scores in (baseline_observed_scores, candidate_observed_scores):
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) or not score_minimum <= x <= score_maximum for x in scores):
            return _blocked("observed scores must be finite and within declared bounds")
    b_n = len(baseline_observed_scores) + baseline_missing_count
    c_n = len(candidate_observed_scores) + candidate_missing_count
    if b_n != c_n or b_n < minimum_tasks or not baseline_observed_scores or not candidate_observed_scores:
        return _blocked("paired universe must match and contain sufficient observed scores")
    b_low = (sum(baseline_observed_scores) + baseline_missing_count * score_minimum) / b_n
    b_high = (sum(baseline_observed_scores) + baseline_missing_count * score_maximum) / b_n
    c_low = (sum(candidate_observed_scores) + candidate_missing_count * score_minimum) / c_n
    c_high = (sum(candidate_observed_scores) + candidate_missing_count * score_maximum) / c_n
    gain_low, gain_high = c_low - b_high, c_high - b_low
    passed = gain_low > minimum_worst_case_gain
    return _seal({
        "status": "ATTRITION_SENSITIVITY_ROBUST" if passed else "ATTRITION_SENSITIVITY_NOT_ROBUST",
        "paired_task_count": b_n, "baseline_score_bounds": [b_low, b_high],
        "candidate_score_bounds": [c_low, c_high],
        "candidate_minus_baseline_gain_bounds": [gain_low, gain_high],
        "minimum_worst_case_gain": float(minimum_worst_case_gain),
        "missing_outcome_values_authenticated": False,
    })


def stage320_integrate_stratified_overlap_sensitivity(*, sampling_result: Mapping,
                                                      overlap_result: Mapping,
                                                      coverage_result: Mapping,
                                                      sensitivity_result: Mapping,
                                                      held: bool = False):
    """Require all four sealed checks; return proposal eligibility only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    gates = (
        (sampling_result, "STRATIFIED_SAMPLING_VALID"),
        (overlap_result, "EVALUATOR_OVERLAP_WITHIN_BOUNDS"),
        (coverage_result, "EVALUATOR_DOMAIN_COVERAGE_VALID"),
        (sensitivity_result, "ATTRITION_SENSITIVITY_ROBUST"),
    )
    if not all(_sealed(result, status) for result, status in gates):
        return _blocked("all four sealed stratified/overlap/coverage/sensitivity gates must pass")
    return _seal({
        "status": "STRATIFIED_OVERLAP_SENSITIVITY_PASSED",
        "evidence_digests": [result["result_digest"] for result, _ in gates],
        "decision_scope": "proposal eligibility for separate review only",
        "sampling_frame_authenticated": False, "evaluator_independence_proven": False,
        "domain_representativeness_proven": False, "causal_gain_proven": False,
        "recursive_self_improvement_proven": False, "asi_demonstrated": False,
    })
