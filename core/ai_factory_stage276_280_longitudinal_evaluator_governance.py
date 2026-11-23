"""Stages 276-280: longitudinal capability history and evaluator governance.

All evaluator identities, timestamps, strata and scores are caller declarations.
This module validates structure and consistency; it does not authenticate actors,
attest execution, run experiments, or authorize model changes.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
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


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _valid(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    try:
        excluded = {"result_digest"}
        if status == "CAPABILITY_HISTORY_RECORD":
            excluded.add("record_digest")
        return _digest(result.get("result_digest")) and result["result_digest"] == _hash(
            {k: v for k, v in result.items() if k not in excluded}
        )
    except (TypeError, ValueError):
        return False


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def stage276_append_capability_history(*, previous: Mapping | None, observation: Mapping,
                                       recorded_at: str, held: bool = False):
    """Create a hash-linked longitudinal record from a sealed regression-guard result."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not _valid(observation, "CAPABILITY_REGRESSION_GUARD_PASSED"):
        return _blocked("observation must be a sealed passing regression guard")
    if previous is None:
        sequence, previous_digest = 1, "0" * 64
    else:
        if not _valid(previous, "CAPABILITY_HISTORY_RECORD"):
            return _blocked("previous history record is invalid")
        sequence = previous.get("sequence")
        previous_digest = previous.get("record_digest")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1 or not _digest(previous_digest):
            return _blocked("previous sequence or digest is invalid")
        sequence += 1
    parsed = _time(recorded_at)
    if parsed is None:
        return _blocked("observation requires a timezone-aware recorded_at timestamp")
    payload = {
        "status": "CAPABILITY_HISTORY_RECORD",
        "sequence": sequence,
        "previous_record_digest": previous_digest,
        "observation_digest": observation["result_digest"],
        "recorded_at": recorded_at,
        "domain_comparisons": observation["domain_comparisons"],
        "history_is_append_only_enforced": False,
        "trusted_timestamping_verified": False,
    }
    sealed = _seal(payload)
    sealed["record_digest"] = sealed["result_digest"]
    return sealed


def stage277_measure_evaluator_disagreement(*, evaluations: Sequence[Mapping],
                                            maximum_score_spread: float = 0.10,
                                            minimum_evaluators: int = 3,
                                            held: bool = False):
    """Require unique evaluator declarations and bound the spread of domain scores."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluations, Sequence) or isinstance(evaluations, (str, bytes))
            or isinstance(minimum_evaluators, bool) or not isinstance(minimum_evaluators, int)
            or minimum_evaluators < 3 or len(evaluations) < minimum_evaluators
            or not _number(maximum_score_spread) or not 0 <= maximum_score_spread <= 1):
        return _blocked("at least three evaluations and a valid spread threshold are required")
    evaluators, domains = set(), {}
    for row in evaluations:
        if not isinstance(row, Mapping):
            return _blocked("each evaluation must be a mapping")
        evaluator, domain, score = row.get("evaluator_id"), row.get("domain"), row.get("score")
        if (not isinstance(evaluator, str) or not evaluator.strip() or evaluator in evaluators
                or not isinstance(domain, str) or not domain.strip() or not _number(score)
                or not 0 <= score <= 1 or not _digest(row.get("evidence_digest"))):
            return _blocked("evaluator, domain, score or evidence digest is invalid")
        evaluators.add(evaluator)
        domains.setdefault(domain, []).append(float(score))
    if any(len(scores) < minimum_evaluators for scores in domains.values()):
        return _blocked("every domain must have the minimum number of evaluator scores")
    summaries, disagreements = [], []
    for domain, scores in sorted(domains.items()):
        spread = max(scores) - min(scores)
        summaries.append({"domain": domain, "evaluator_count": len(scores),
                          "mean_score": sum(scores) / len(scores), "score_spread": spread})
        if spread > maximum_score_spread:
            disagreements.append(domain)
    return _seal({
        "status": "EVALUATOR_DISAGREEMENT_DETECTED" if disagreements else "EVALUATOR_AGREEMENT_WITHIN_LIMIT",
        "evaluator_count": len(evaluators), "domain_summaries": summaries,
        "disagreement_domains": disagreements, "maximum_score_spread": float(maximum_score_spread),
        "evaluator_independence_authenticated": False,
    })


def stage278_validate_improvement_durability(*, history: Sequence[Mapping],
                                             minimum_observations: int = 3,
                                             maximum_score_drop: float = 0.05,
                                             held: bool = False):
    """Check a minimum number of time-ordered observations for bounded score decay."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(history, Sequence) or isinstance(history, (str, bytes))
            or isinstance(minimum_observations, bool) or not isinstance(minimum_observations, int)
            or minimum_observations < 3 or len(history) < minimum_observations
            or not _number(maximum_score_drop) or not 0 <= maximum_score_drop <= 1):
        return _blocked("at least three observations and a valid decay limit are required")
    parsed, rows = [], []
    for item in history:
        if not isinstance(item, Mapping):
            return _blocked("each durability observation must be a mapping")
        stamp, domain, score, evidence = item.get("recorded_at"), item.get("domain"), item.get("score"), item.get("evidence_digest")
        dt = _time(stamp)
        if dt is None or not isinstance(domain, str) or not domain.strip() or not _number(score) or not 0 <= score <= 1 or not _digest(evidence):
            return _blocked("durability observation fields are invalid")
        parsed.append(dt)
        rows.append({"recorded_at": stamp, "domain": domain, "score": float(score), "evidence_digest": evidence})
    if parsed != sorted(parsed) or len(set((x["recorded_at"], x["domain"]) for x in rows)) != len(rows):
        return _blocked("observations must be chronologically ordered and unique per timestamp/domain")
    domains = sorted({x["domain"] for x in rows})
    results, failures = [], []
    for domain in domains:
        values = [x["score"] for x in rows if x["domain"] == domain]
        if len(values) < minimum_observations:
            return _blocked("every domain must meet the minimum observation count")
        drop = values[0] - min(values[1:])
        results.append({"domain": domain, "initial_score": values[0],
                        "minimum_followup_score": min(values[1:]), "maximum_observed_drop": drop})
        if drop > maximum_score_drop:
            failures.append(domain)
    return _seal({
        "status": "IMPROVEMENT_DURABILITY_FAILED" if failures else "IMPROVEMENT_DURABILITY_PASSED",
        "observation_count": len(rows), "domain_results": results,
        "failed_domains": failures, "maximum_score_drop": float(maximum_score_drop),
        "future_durability_proven": False,
    })


def stage279_detect_measurement_bias(*, subgroup_scores: Sequence[Mapping],
                                     maximum_absolute_gap: float = 0.10,
                                     minimum_groups: int = 2, held: bool = False):
    """Flag declared subgroup score gaps; caller-defined strata are not independently validated."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(subgroup_scores, Sequence) or isinstance(subgroup_scores, (str, bytes))
            or isinstance(minimum_groups, bool) or not isinstance(minimum_groups, int)
            or minimum_groups < 2 or not _number(maximum_absolute_gap)
            or not 0 <= maximum_absolute_gap <= 1):
        return _blocked("at least two declared groups and a valid gap limit are required")
    groups = {}
    for row in subgroup_scores:
        if not isinstance(row, Mapping):
            return _blocked("each subgroup score must be a mapping")
        domain, group, score, evidence = row.get("domain"), row.get("group"), row.get("score"), row.get("evidence_digest")
        if (not isinstance(domain, str) or not domain.strip() or not isinstance(group, str)
                or not group.strip() or not _number(score) or not 0 <= score <= 1 or not _digest(evidence)):
            return _blocked("subgroup score fields are invalid")
        groups.setdefault(domain, {})[group] = float(score)
    if not groups or any(len(values) < minimum_groups for values in groups.values()):
        return _blocked("every domain must include the minimum number of distinct groups")
    summaries, biased = [], []
    for domain, values in sorted(groups.items()):
        gap = max(values.values()) - min(values.values())
        summaries.append({"domain": domain, "group_count": len(values),
                          "score_gap": gap, "group_scores": dict(sorted(values.items()))})
        if gap > maximum_absolute_gap:
            biased.append(domain)
    return _seal({
        "status": "MEASUREMENT_BIAS_FLAGGED" if biased else "DECLARED_GROUP_GAPS_WITHIN_LIMIT",
        "domain_summaries": summaries, "flagged_domains": biased,
        "maximum_absolute_gap": float(maximum_absolute_gap),
        "strata_completeness_verified": False,
    })


def stage280_evaluate_capability_evidence_governance(*, history_record: Mapping,
                                                      evaluator_result: Mapping,
                                                      durability_result: Mapping,
                                                      bias_result: Mapping,
                                                      held: bool = False):
    """Unified fail-closed gate; emits a governance decision only, never execution approval."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    valid_history = _valid(history_record, "CAPABILITY_HISTORY_RECORD")
    valid_evaluators = _valid(evaluator_result, "EVALUATOR_AGREEMENT_WITHIN_LIMIT")
    valid_durability = _valid(durability_result, "IMPROVEMENT_DURABILITY_PASSED")
    valid_bias = _valid(bias_result, "DECLARED_GROUP_GAPS_WITHIN_LIMIT")
    if not all((valid_history, valid_evaluators, valid_durability, valid_bias)):
        return _blocked("all four sealed evidence governance components must pass")
    return _seal({
        "status": "CAPABILITY_EVIDENCE_GOVERNANCE_PASSED",
        "history_record_digest": history_record["record_digest"],
        "evaluator_result_digest": evaluator_result["result_digest"],
        "durability_result_digest": durability_result["result_digest"],
        "bias_result_digest": bias_result["result_digest"],
        "decision_scope": "evidence governance only",
        "capability_gain_proven": False,
        "rsi_or_asi_demonstrated": False,
        "next_step": "ELIGIBLE_FOR_SEPARATE_REVIEW",
    })
