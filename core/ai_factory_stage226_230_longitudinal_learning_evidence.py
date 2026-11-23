"""Stages 226-230: longitudinal evidence and improvement proposal helpers.

Deterministic, proposal-only. No experiment execution, training, model mutation,
rollback, merge, deployment, or authorization is performed here.
"""
from __future__ import annotations

import math
from typing import Mapping, Sequence

_FAILURES = {
    "DATA_GAP", "QUALITY_REGRESSION", "SAFETY_REGRESSION",
    "COST_OVERRUN", "NON_REPRODUCIBLE", "EVALUATOR_DISAGREEMENT", "UNKNOWN",
}


def _blocked(reason: str) -> dict:
    return {
        "status": "INSUFFICIENT_EVIDENCE", "reason": reason,
        "proposal_only": True, "experiment_execution_authorized": False,
        "model_change_authorized": False, "merge_deploy_authorized": False,
    }


def _finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stage226_longitudinal_ledger(*, events: Sequence[Mapping], held: bool = False):
    """Validate ordered append-only ledger structure; signatures are caller-verified."""
    if held:
        return _blocked("HOLD is active")
    if not events:
        return _blocked("ledger is empty")
    seen = set()
    previous = "GENESIS"
    for expected_seq, event in enumerate(events, start=1):
        event_id = event.get("event_id")
        digest = event.get("event_digest")
        if not event_id or not digest or event_id in seen:
            return _blocked("missing or duplicate event identity/digest")
        if event.get("sequence") != expected_seq:
            return _blocked("ledger sequence is not contiguous")
        if event.get("previous_digest") != previous:
            return _blocked("ledger digest-chain link mismatch")
        if event.get("signature_valid") is not True:
            return _blocked("event signature not independently verified")
        seen.add(event_id)
        previous = digest
    return {
        "status": "LONGITUDINAL_LEDGER_STRUCTURALLY_VALID",
        "event_count": len(events), "head_digest": previous,
        "append_only_check": "ordered chain validated; storage immutability not proven",
        "signature_scope": "caller-supplied verification flag; cryptographic verification not performed",
        "proposal_only": True, "experiment_execution_authorized": False,
        "model_change_authorized": False, "merge_deploy_authorized": False,
    }


def stage227_failure_classification(*, outcomes: Sequence[Mapping], held: bool = False):
    if held:
        return _blocked("HOLD is active")
    if not outcomes:
        return _blocked("no outcomes supplied")
    counts = {name: 0 for name in sorted(_FAILURES)}
    for outcome in outcomes:
        reason = outcome.get("failure_reason")
        if reason not in _FAILURES:
            return _blocked("missing or unrecognized failure reason")
        counts[reason] += 1
    return {
        "status": "FAILURE_PROFILE_READY", "outcome_count": len(outcomes),
        "failure_counts": counts, "classified_failure_count": sum(counts.values()),
        "proposal_only": True, "experiment_execution_authorized": False,
        "model_change_authorized": False, "merge_deploy_authorized": False,
    }


def stage228_compare_hypotheses(*, hypotheses: Sequence[Mapping], held: bool = False):
    """Compare only directly comparable evidence; ranking is descriptive, not causal."""
    if held:
        return _blocked("HOLD is active")
    if len(hypotheses) < 2:
        return _blocked("at least two hypotheses are required")
    common = ("suite_id", "dataset_id", "environment_id", "design_id")
    reference = tuple(hypotheses[0].get(k) for k in common)
    if not all(reference) or any(tuple(h.get(k) for k in common) != reference for h in hypotheses):
        return _blocked("hypothesis evidence is not directly comparable")
    rows = []
    ids = set()
    for h in hypotheses:
        hid = h.get("hypothesis_id")
        gain = h.get("gain_lower_bound")
        safety = h.get("safety_score")
        cost = h.get("cost_ratio")
        if not hid or hid in ids or not all(_finite_number(v) for v in (gain, safety, cost)):
            return _blocked("invalid or duplicate hypothesis metrics")
        if not 0 <= safety <= 1 or cost <= 0:
            return _blocked("safety or cost metric outside valid range")
        ids.add(hid)
        rows.append({"hypothesis_id": hid, "gain_lower_bound": gain,
                     "safety_score": safety, "cost_ratio": cost,
                     "eligible": gain > 0 and safety >= .95 and cost <= 1.10})
    rows.sort(key=lambda r: (not r["eligible"], -r["gain_lower_bound"], r["cost_ratio"], r["hypothesis_id"]))
    return {
        "status": "HYPOTHESIS_COMPARISON_READY",
        "ranked_hypotheses": rows,
        "recommended_hypothesis_id": next((r["hypothesis_id"] for r in rows if r["eligible"]), None),
        "comparison_basis": dict(zip(common, reference)),
        "interpretation": "descriptive ranking only; no causal conclusion or execution authority",
        "proposal_only": True, "experiment_execution_authorized": False,
        "model_change_authorized": False, "merge_deploy_authorized": False,
    }


def stage229_evaluation_bias_risk(*, strata: Sequence[Mapping], max_rate_gap: float = .10,
                                  min_coverage: float = .90, held: bool = False):
    if held:
        return _blocked("HOLD is active")
    if not strata or not _finite_number(max_rate_gap) or not _finite_number(min_coverage):
        return _blocked("missing strata or invalid thresholds")
    if not 0 <= max_rate_gap <= 1 or not 0 <= min_coverage <= 1:
        return _blocked("thresholds must be within [0, 1]")
    names, rates, coverage = set(), [], []
    for item in strata:
        name, rate, cov = item.get("stratum_id"), item.get("evaluation_rate"), item.get("coverage")
        if not name or name in names or not _finite_number(rate) or not _finite_number(cov):
            return _blocked("invalid or duplicate stratum data")
        if not 0 <= rate <= 1 or not 0 <= cov <= 1:
            return _blocked("stratum rate/coverage outside [0, 1]")
        names.add(name); rates.append(rate); coverage.append(cov)
    gap = max(rates) - min(rates)
    floor = min(coverage)
    risks = []
    if gap > max_rate_gap:
        risks.append("UNEQUAL_EVALUATION_RATE")
    if floor < min_coverage:
        risks.append("LOW_STRATUM_COVERAGE")
    return {
        "status": "EVALUATION_BIAS_RISK" if risks else "NO_CONFIGURED_BIAS_RISK_DETECTED",
        "risk_flags": risks, "evaluation_rate_gap": gap, "minimum_stratum_coverage": floor,
        "stratum_count": len(strata),
        "limitation": "screening heuristic only; absence of flags does not establish absence of bias",
        "proposal_only": True, "experiment_execution_authorized": False,
        "model_change_authorized": False, "merge_deploy_authorized": False,
    }


def stage230_generate_improvement_candidates(*, failure_profile: Mapping,
                                             bias_assessment: Mapping,
                                             regression_flags: Sequence[str] = (),
                                             held: bool = False):
    if held:
        return _blocked("HOLD is active")
    counts = failure_profile.get("failure_counts")
    if not isinstance(counts, Mapping) or not counts:
        return _blocked("validated failure profile is required")
    if bias_assessment.get("status") not in {
        "EVALUATION_BIAS_RISK", "NO_CONFIGURED_BIAS_RISK_DETECTED"
    }:
        return _blocked("bias assessment is missing or invalid")
    candidates = []
    actions = {
        "DATA_GAP": "improve_dataset_coverage_and_provenance",
        "QUALITY_REGRESSION": "inspect_quality_failure_slices",
        "SAFETY_REGRESSION": "prioritize_safety_failure_analysis",
        "COST_OVERRUN": "profile_evaluation_cost",
        "NON_REPRODUCIBLE": "investigate_reproducibility",
        "EVALUATOR_DISAGREEMENT": "audit_rubric_and_evaluator_calibration",
        "UNKNOWN": "collect_failure_diagnostics",
    }
    for reason in sorted(_FAILURES):
        count = counts.get(reason, 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return _blocked("invalid failure count")
        if count:
            candidates.append({"source": reason, "observed_count": count,
                               "proposed_action": actions[reason]})
    for flag in sorted(set(regression_flags)):
        if flag not in {"QUALITY_REGRESSION", "SAFETY_REGRESSION"}:
            return _blocked("unrecognized regression flag")
        candidates.append({"source": flag, "observed_count": 1,
                           "proposed_action": actions[flag]})
    for flag in bias_assessment.get("risk_flags", []):
        if flag not in {"UNEQUAL_EVALUATION_RATE", "LOW_STRATUM_COVERAGE"}:
            return _blocked("unrecognized bias risk flag")
        candidates.append({"source": flag, "observed_count": 1,
                           "proposed_action": "repair_evaluation_sampling_and_stratum_coverage"})
    return {
        "status": "IMPROVEMENT_PROPOSALS_READY" if candidates else "NO_CANDIDATES_FROM_CURRENT_EVIDENCE",
        "candidates": candidates,
        "authority": "suggestions only; separate explicit approval and independent evidence required",
        "proposal_only": True, "task_execution_authorized": False,
        "experiment_execution_authorized": False, "model_change_authorized": False,
        "merge_deploy_authorized": False,
    }
