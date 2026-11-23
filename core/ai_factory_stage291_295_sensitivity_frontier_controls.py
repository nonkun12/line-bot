"""Stages 291-295: sensitivity, evaluator drift, capability frontier and controls.

All inputs are caller-supplied evidence. Digests provide integrity linkage only;
they do not authenticate actors, timestamps, custody or task independence.
No stage authorizes execution, experiments, model changes, merge/deploy or HOLD release.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import math

_FALSE = {"proposal_only": True, "task_execution_authorized": False,
          "experiment_execution_authorized": False, "model_change_authorized": False,
          "merge_deploy_authorized": False, "hold_release_authorized": False}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _sealed(result, expected):
    if not isinstance(result, Mapping) or result.get("status") != expected:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    try:
        return _digest(result.get("result_digest")) and result["result_digest"] == _hash(
            {k: v for k, v in result.items() if k != "result_digest"})
    except (TypeError, ValueError):
        return False


def stage291_test_threshold_sensitivity(*, domain_deltas: Sequence[Mapping],
                                        regression_budgets: Sequence[float],
                                        minimum_robust_budgets: int = 2,
                                        held: bool = False):
    """Re-evaluate domain regressions over a declared threshold grid."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(domain_deltas, Sequence) or isinstance(domain_deltas, (str, bytes))
            or not isinstance(regression_budgets, Sequence) or isinstance(regression_budgets, (str, bytes))
            or isinstance(minimum_robust_budgets, bool) or not isinstance(minimum_robust_budgets, int)
            or minimum_robust_budgets < 1 or len(regression_budgets) < minimum_robust_budgets):
        return _blocked("domain deltas or sensitivity grid is invalid")
    budgets = list(regression_budgets)
    if (any(not _number(x) or not 0 <= x <= 1 for x in budgets)
            or len(set(budgets)) != len(budgets)):
        return _blocked("regression budgets must be unique finite values in [0, 1]")
    domains = {}
    for row in domain_deltas:
        if not isinstance(row, Mapping):
            return _blocked("each domain delta must be a mapping")
        name, delta, evidence = row.get("domain"), row.get("delta"), row.get("evidence_digest")
        if (not isinstance(name, str) or not name.strip() or name in domains
                or not _number(delta) or not -1 <= delta <= 1 or not _digest(evidence)):
            return _blocked("domain delta identity, value or digest is invalid")
        domains[name] = float(delta)
    if not domains:
        return _blocked("at least one domain is required")
    evaluations = []
    for budget in sorted(budgets):
        failing = sorted(name for name, delta in domains.items() if delta < -budget)
        evaluations.append({"regression_budget": float(budget), "failing_domains": failing,
                            "passed": not failing})
    passed_count = sum(row["passed"] for row in evaluations)
    robust = passed_count >= minimum_robust_budgets
    return _seal({"status": "SENSITIVITY_ROBUST" if robust else "SENSITIVITY_FRAGILE",
                  "evaluations": evaluations, "passed_budget_count": passed_count,
                  "required_passed_budget_count": minimum_robust_budgets,
                  "domain_deltas_digest": _hash(domains),
                  "interpretation": "threshold sensitivity only; not proof of causal gain"})


def stage292_detect_evaluator_drift(*, calibration_rounds: Sequence[Mapping],
                                    maximum_absolute_error_drift: float = 0.10,
                                    minimum_rounds: int = 3, held: bool = False):
    """Detect chronological changes in evaluator calibration error."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(calibration_rounds, Sequence) or isinstance(calibration_rounds, (str, bytes))
            or isinstance(minimum_rounds, bool) or not isinstance(minimum_rounds, int)
            or minimum_rounds < 3 or not _number(maximum_absolute_error_drift)
            or not 0 <= maximum_absolute_error_drift <= 1):
        return _blocked("calibration rounds or drift threshold is invalid")
    seen, grouped, previous = set(), {}, None
    for row in calibration_rounds:
        if not isinstance(row, Mapping):
            return _blocked("each calibration row must be a mapping")
        evaluator, timestamp, error, evidence = (row.get("evaluator_id"), row.get("timestamp"),
                                                  row.get("absolute_error"), row.get("evidence_digest"))
        if (not isinstance(evaluator, str) or not evaluator.strip()
                or not isinstance(timestamp, int) or isinstance(timestamp, bool)
                or not _number(error) or not 0 <= error <= 1 or not _digest(evidence)):
            return _blocked("evaluator, timestamp, error or digest is invalid")
        key = (evaluator, timestamp)
        if key in seen:
            return _blocked("duplicate evaluator timestamp")
        seen.add(key)
        if previous is not None and timestamp <= previous:
            return _blocked("timestamps must be strictly increasing")
        previous = timestamp
        grouped.setdefault(evaluator, []).append(float(error))
    if not grouped or any(len(values) < minimum_rounds for values in grouped.values()):
        return _blocked("each evaluator needs the minimum chronological calibration rounds")
    summary, drifted = [], []
    for evaluator, errors in sorted(grouped.items()):
        drift = abs(errors[-1] - errors[0])
        summary.append({"evaluator_id": evaluator, "round_count": len(errors),
                        "initial_error": errors[0], "latest_error": errors[-1],
                        "absolute_error_drift": drift})
        if drift > maximum_absolute_error_drift:
            drifted.append(evaluator)
    return _seal({"status": "EVALUATOR_DRIFT_WITHIN_LIMIT" if not drifted else "EVALUATOR_DRIFT_DETECTED",
                  "evaluators": summary, "drifted_evaluators": drifted,
                  "evaluator_identity_independence_verified": False})


def stage293_track_capability_frontier(*, observations: Sequence[Mapping],
                                       minimum_complexity_levels: int = 3,
                                       maximum_score_drop: float = 0.05,
                                       held: bool = False):
    """Track score by declared domain/complexity; flag frontier regressions."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(observations, Sequence) or isinstance(observations, (str, bytes))
            or isinstance(minimum_complexity_levels, bool) or not isinstance(minimum_complexity_levels, int)
            or minimum_complexity_levels < 2 or not _number(maximum_score_drop)
            or not 0 <= maximum_score_drop <= 1):
        return _blocked("frontier observations or thresholds are invalid")
    seen, grouped = set(), {}
    for row in observations:
        if not isinstance(row, Mapping):
            return _blocked("each frontier observation must be a mapping")
        domain, level, score, evidence = (row.get("domain"), row.get("complexity_level"),
                                          row.get("score"), row.get("evidence_digest"))
        if (not isinstance(domain, str) or not domain.strip()
                or isinstance(level, bool) or not isinstance(level, int) or level < 1
                or not _number(score) or not 0 <= score <= 1 or not _digest(evidence)
                or (domain, level) in seen):
            return _blocked("domain/level pair, score or evidence digest is invalid or duplicated")
        seen.add((domain, level))
        grouped.setdefault(domain, []).append((level, float(score)))
    if not grouped or any(len(values) < minimum_complexity_levels for values in grouped.values()):
        return _blocked("each domain needs enough distinct complexity levels")
    summary, regressed = [], []
    for domain, values in sorted(grouped.items()):
        values.sort()
        levels = [level for level, _ in values]
        scores = [score for _, score in values]
        if len(set(levels)) != len(levels):
            return _blocked("complexity levels must be unique per domain")
        drops = [{"from_level": levels[i], "to_level": levels[i + 1],
                  "score_drop": scores[i] - scores[i + 1]}
                 for i in range(len(scores) - 1) if scores[i] - scores[i + 1] > maximum_score_drop]
        summary.append({"domain": domain, "complexity_levels": levels, "scores": scores,
                        "frontier_score": scores[-1], "excessive_drops": drops})
        if drops:
            regressed.append(domain)
    return _seal({"status": "CAPABILITY_FRONTIER_TRACKED" if not regressed else "FRONTIER_REGRESSION_DETECTED",
                  "domain_frontiers": summary, "regressed_domains": regressed,
                  "complexity_labels_caller_declared": True})


def stage294_compare_controlled_gain(*, paired_observations: Sequence[Mapping],
                                     minimum_net_gain: float = 0.02,
                                     held: bool = False):
    """Compare candidate-vs-baseline change against a matched control change."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(paired_observations, Sequence) or isinstance(paired_observations, (str, bytes))
            or not _number(minimum_net_gain) or not 0 <= minimum_net_gain <= 1):
        return _blocked("paired observations or minimum net gain is invalid")
    seen, net_gains = set(), []
    for row in paired_observations:
        if not isinstance(row, Mapping):
            return _blocked("each paired observation must be a mapping")
        pair_id = row.get("pair_id")
        candidate_before, candidate_after = row.get("candidate_before"), row.get("candidate_after")
        control_before, control_after = row.get("control_before"), row.get("control_after")
        evidence = row.get("evidence_digest")
        values = (candidate_before, candidate_after, control_before, control_after)
        if (not isinstance(pair_id, str) or not pair_id.strip() or pair_id in seen
                or any(not _number(x) or not 0 <= x <= 1 for x in values) or not _digest(evidence)):
            return _blocked("pair identity, bounded scores or evidence digest is invalid")
        seen.add(pair_id)
        candidate_gain = candidate_after - candidate_before
        control_gain = control_after - control_before
        net_gains.append(candidate_gain - control_gain)
    if len(net_gains) < 3:
        return _blocked("at least three unique matched pairs are required")
    mean_net_gain = sum(net_gains) / len(net_gains)
    passed = mean_net_gain > minimum_net_gain
    return _seal({"status": "CONTROL_ADJUSTED_GAIN_PASSED" if passed else "CONTROL_ADJUSTED_GAIN_NOT_ESTABLISHED",
                  "pair_count": len(net_gains), "mean_net_gain": mean_net_gain,
                  "minimum_net_gain": float(minimum_net_gain),
                  "paired_net_gains_digest": _hash(net_gains),
                  "randomization_or_causal_identification_verified": False})


def stage295_integrate_research_readiness(*, sensitivity_result: Mapping,
                                         evaluator_drift_result: Mapping,
                                         frontier_result: Mapping,
                                         control_result: Mapping,
                                         held: bool = False):
    """Require all four sealed research-readiness checks; never authorizes execution."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    required = ((sensitivity_result, "SENSITIVITY_ROBUST"),
                (evaluator_drift_result, "EVALUATOR_DRIFT_WITHIN_LIMIT"),
                (frontier_result, "CAPABILITY_FRONTIER_TRACKED"),
                (control_result, "CONTROL_ADJUSTED_GAIN_PASSED"))
    if not all(_sealed(item, status) for item, status in required):
        return _blocked("all four sealed research-readiness gates must pass")
    return _seal({"status": "RESEARCH_READINESS_EVIDENCE_PASSED",
                  "evidence_digests": [item["result_digest"] for item, _ in required],
                  "decision_scope": "proposal eligibility for separate independent review only",
                  "model_improvement_proven": False, "recursive_self_improvement_proven": False,
                  "asi_demonstrated": False, "next_step": "ELIGIBLE_FOR_SEPARATE_RESEARCH_REVIEW"})
