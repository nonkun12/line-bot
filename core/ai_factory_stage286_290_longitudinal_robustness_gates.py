"""Stages 286-290: longitudinal robustness, regression budgets and holdout integrity.

Caller-declared evidence only. Digests provide integrity linkage, not authentication.
No stage authorizes model execution, training, merge, deployment or HOLD release.
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


def _valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE}


def _seal(payload):
    result = {**payload, **_FALSE}
    result["result_digest"] = _hash(result)
    return result


def _sealed(result, status):
    if not isinstance(result, Mapping) or result.get("status") != status:
        return False
    if any(result.get(k) is not v for k, v in _FALSE.items()):
        return False
    try:
        return _valid_digest(result.get("result_digest")) and result["result_digest"] == _hash(
            {k: v for k, v in result.items() if k != "result_digest"})
    except (TypeError, ValueError):
        return False


def stage286_measure_longitudinal_stability(*, rounds: Sequence[Mapping],
                                            minimum_rounds: int = 3,
                                            maximum_domain_range: float = 0.10,
                                            held: bool = False):
    """Require chronological, unique rounds and bounded per-domain score range."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(rounds, Sequence) or isinstance(rounds, (str, bytes))
            or isinstance(minimum_rounds, bool) or not isinstance(minimum_rounds, int)
            or minimum_rounds < 3 or not _finite(maximum_domain_range)
            or not 0 <= maximum_domain_range <= 1):
        return _blocked("rounds or stability thresholds are invalid")
    seen, grouped, previous = set(), {}, None
    for row in rounds:
        if not isinstance(row, Mapping):
            return _blocked("each round must be a mapping")
        rid, timestamp, domain, score, evidence = (row.get("round_id"), row.get("timestamp"),
                                                    row.get("domain"), row.get("score"),
                                                    row.get("evidence_digest"))
        if (not isinstance(rid, str) or not rid.strip() or rid in seen
                or not isinstance(timestamp, int) or isinstance(timestamp, bool)
                or not isinstance(domain, str) or not domain.strip()
                or not _finite(score) or not 0 <= score <= 1 or not _valid_digest(evidence)):
            return _blocked("round identity, timestamp, domain, score or digest is invalid")
        if previous is not None and timestamp <= previous:
            return _blocked("round timestamps must be strictly increasing")
        previous = timestamp
        seen.add(rid)
        grouped.setdefault(domain, []).append(float(score))
    if len(seen) < minimum_rounds or not grouped or any(len(v) < minimum_rounds for v in grouped.values()):
        return _blocked("each domain must contain the minimum number of chronological rounds")
    summary, unstable = [], []
    for domain, scores in sorted(grouped.items()):
        spread = max(scores) - min(scores)
        summary.append({"domain": domain, "round_count": len(scores), "score_range": spread})
        if spread > maximum_domain_range:
            unstable.append(domain)
    return _seal({"status": "LONGITUDINAL_STABILITY_PASSED" if not unstable else "LONGITUDINAL_INSTABILITY_DETECTED",
                  "domain_stability": summary, "unstable_domains": unstable,
                  "round_ids_digest": _hash(sorted(seen)), "external_round_custody_verified": False})


def stage287_enforce_regression_budget(*, domain_deltas: Sequence[Mapping],
                                       maximum_regression: float = 0.03,
                                       held: bool = False):
    """Reject any domain regression beyond the predeclared budget."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(domain_deltas, Sequence) or isinstance(domain_deltas, (str, bytes))
            or not _finite(maximum_regression) or not 0 <= maximum_regression <= 1):
        return _blocked("domain deltas or regression budget are invalid")
    seen, regressions, summary = set(), [], []
    for row in domain_deltas:
        if not isinstance(row, Mapping):
            return _blocked("each domain delta must be a mapping")
        domain, delta, evidence = row.get("domain"), row.get("delta"), row.get("evidence_digest")
        if (not isinstance(domain, str) or not domain.strip() or domain in seen
                or not _finite(delta) or not -1 <= delta <= 1 or not _valid_digest(evidence)):
            return _blocked("domain, delta or evidence digest is invalid or duplicated")
        seen.add(domain)
        summary.append({"domain": domain, "delta": float(delta)})
        if delta < -maximum_regression:
            regressions.append(domain)
    if not seen:
        return _blocked("at least one domain delta is required")
    return _seal({"status": "REGRESSION_BUDGET_PASSED" if not regressions else "REGRESSION_BUDGET_EXCEEDED",
                  "domain_deltas": sorted(summary, key=lambda x: x["domain"]),
                  "regressed_domains": sorted(regressions),
                  "maximum_regression": float(maximum_regression)})


def stage288_check_consensus_robustness(*, evaluator_scores: Sequence[Mapping],
                                        minimum_evaluators: int = 3,
                                        maximum_median_absolute_deviation: float = 0.10,
                                        held: bool = False):
    """Use median and MAD to expose evaluator disagreement without hiding outliers."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(evaluator_scores, Sequence) or isinstance(evaluator_scores, (str, bytes))
            or isinstance(minimum_evaluators, bool) or not isinstance(minimum_evaluators, int)
            or minimum_evaluators < 3 or not _finite(maximum_median_absolute_deviation)
            or not 0 <= maximum_median_absolute_deviation <= 1):
        return _blocked("evaluator scores or consensus thresholds are invalid")
    grouped = {}
    seen = set()
    for row in evaluator_scores:
        if not isinstance(row, Mapping):
            return _blocked("each evaluator score must be a mapping")
        domain, evaluator, score, evidence = (row.get("domain"), row.get("evaluator_id"),
                                               row.get("score"), row.get("evidence_digest"))
        if (not isinstance(domain, str) or not domain.strip()
                or not isinstance(evaluator, str) or not evaluator.strip()
                or (domain, evaluator) in seen or not _finite(score) or not 0 <= score <= 1
                or not _valid_digest(evidence)):
            return _blocked("domain/evaluator pair, score or evidence digest is invalid")
        seen.add((domain, evaluator))
        grouped.setdefault(domain, []).append(float(score))
    if not grouped or any(len(v) < minimum_evaluators for v in grouped.values()):
        return _blocked("each domain needs the minimum number of distinct evaluators")
    summary, disputed = [], []
    for domain, values in sorted(grouped.items()):
        ordered = sorted(values)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        deviations = sorted(abs(x - median) for x in values)
        dmid = len(deviations) // 2
        mad = deviations[dmid] if len(deviations) % 2 else (deviations[dmid - 1] + deviations[dmid]) / 2
        summary.append({"domain": domain, "evaluator_count": len(values), "median": median,
                        "median_absolute_deviation": mad, "minimum": min(values), "maximum": max(values)})
        if mad > maximum_median_absolute_deviation:
            disputed.append(domain)
    return _seal({"status": "EVALUATOR_CONSENSUS_ROBUST" if not disputed else "EVALUATOR_DISAGREEMENT",
                  "domain_consensus": summary, "disputed_domains": disputed,
                  "evaluator_independence_verified": False})


def stage289_enforce_holdout_separation(*, development_task_digests: Sequence[str],
                                        holdout_task_digests: Sequence[str],
                                        minimum_holdout_tasks: int = 10,
                                        held: bool = False):
    """Require non-overlapping, unique, digest-valid development and holdout sets."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(development_task_digests, Sequence) or isinstance(development_task_digests, (str, bytes))
            or not isinstance(holdout_task_digests, Sequence) or isinstance(holdout_task_digests, (str, bytes))
            or isinstance(minimum_holdout_tasks, bool) or not isinstance(minimum_holdout_tasks, int)
            or minimum_holdout_tasks < 1):
        return _blocked("task sets or holdout minimum are invalid")
    dev, test = list(development_task_digests), list(holdout_task_digests)
    if (not dev or len(set(dev)) != len(dev) or len(set(test)) != len(test)
            or any(not _valid_digest(x) for x in dev + test)
            or len(test) < minimum_holdout_tasks):
        return _blocked("task digests must be unique and valid with sufficient holdout size")
    overlap = set(dev) & set(test)
    if overlap:
        return _seal({"status": "HOLDOUT_CONTAMINATION_DETECTED",
                      "overlap_count": len(overlap), "development_count": len(dev),
                      "holdout_count": len(test)})
    return _seal({"status": "HOLDOUT_SEPARATION_PASSED", "overlap_count": 0,
                  "development_count": len(dev), "holdout_count": len(test),
                  "task_blinding_or_prior_exposure_verified": False,
                  "development_set_digest": _hash(sorted(dev)),
                  "holdout_set_digest": _hash(sorted(test))})


def stage290_integrate_robustness_gate(*, stability_result: Mapping,
                                       regression_result: Mapping,
                                       consensus_result: Mapping,
                                       holdout_result: Mapping,
                                       held: bool = False):
    """Integrate all robustness evidence and remain eligibility-only."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    required = ((stability_result, "LONGITUDINAL_STABILITY_PASSED"),
                (regression_result, "REGRESSION_BUDGET_PASSED"),
                (consensus_result, "EVALUATOR_CONSENSUS_ROBUST"),
                (holdout_result, "HOLDOUT_SEPARATION_PASSED"))
    if not all(_sealed(item, status) for item, status in required):
        return _blocked("all four sealed robustness gates must pass")
    return _seal({"status": "ROBUSTNESS_EVIDENCE_INTEGRATED",
                  "evidence_digests": [item["result_digest"] for item, _ in required],
                  "decision_scope": "eligibility for separate research review only",
                  "general_capability_gain_proven": False, "rsi_or_asi_demonstrated": False,
                  "next_step": "ELIGIBLE_FOR_SEPARATE_REVIEW"})
