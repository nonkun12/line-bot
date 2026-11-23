"""Stages 241-245: reproducibility, robustness, safety non-regression and gain attribution.

Proposal-only evidence validators. No experiment is executed and no model is changed.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from typing import Mapping, Sequence

_HEX = re.compile(r"^[0-9a-f]{64}$")


def _blocked(reason):
    return {
        "status": "INSUFFICIENT_EVIDENCE", "reason": reason, "proposal_only": True,
        "task_execution_authorized": False, "experiment_execution_authorized": False,
        "model_change_authorized": False, "merge_deploy_authorized": False,
        "hold_release_authorized": False,
    }


def _out(payload):
    payload.update({
        "proposal_only": True, "task_execution_authorized": False,
        "experiment_execution_authorized": False, "model_change_authorized": False,
        "merge_deploy_authorized": False, "hold_release_authorized": False,
    })
    return payload


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def stage241_reproducibility_check(
    *, runs: Sequence[Mapping], required_runs: int = 3,
    metric_tolerance: float = 0.0, held: bool = False,
):
    """Require repeated runs bound to identical artifact/protocol/environment inputs."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(runs, Sequence) or isinstance(runs, (str, bytes))
            or not isinstance(required_runs, int) or isinstance(required_runs, bool)
            or required_runs < 2 or len(runs) < required_runs
            or not _finite(metric_tolerance) or metric_tolerance < 0):
        return _blocked("invalid run count or metric tolerance")
    identity_fields = ("artifact_digest", "protocol_digest", "dataset_digest", "suite_digest", "environment_id")
    identities, run_ids, metrics = set(), set(), []
    for run in runs:
        if not isinstance(run, Mapping):
            return _blocked("run entry must be a mapping")
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip() or run_id in run_ids:
            return _blocked("run IDs must be present and unique")
        run_ids.add(run_id)
        values = tuple(run.get(key) for key in identity_fields)
        if any(not _digest(v) for v in values[:4]) or not isinstance(values[4], str) or not values[4].strip():
            return _blocked("invalid artifact, protocol, dataset, suite or environment identity")
        identities.add(values)
        metric = run.get("primary_metric")
        if not _finite(metric):
            return _blocked("primary metric must be finite")
        metrics.append(float(metric))
    if len(identities) != 1:
        return _blocked("run inputs are not identical")
    spread = max(metrics) - min(metrics)
    return _out({
        "status": "REPRODUCIBLE" if spread <= metric_tolerance else "REPRODUCIBILITY_FAILED",
        "run_count": len(runs), "metric_min": min(metrics), "metric_max": max(metrics),
        "metric_spread": spread, "metric_tolerance": metric_tolerance,
        "identity_digest": sha256(json.dumps(sorted(next(iter(identities))), separators=(",", ":")).encode()).hexdigest(),
    })


def stage242_stratified_robustness(
    *, strata: Sequence[Mapping], required_strata: Sequence[str],
    minimum_coverage: float = 1.0, minimum_gain: float = 0.0, held: bool = False,
):
    """Require declared stratum coverage and a non-negative minimum gain per stratum."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(strata, Sequence) or isinstance(strata, (str, bytes))
            or not isinstance(required_strata, Sequence) or isinstance(required_strata, (str, bytes))
            or not required_strata or not _finite(minimum_coverage)
            or not 0 < minimum_coverage <= 1 or not _finite(minimum_gain)):
        return _blocked("invalid robustness inputs")
    required = list(required_strata)
    if any(not isinstance(x, str) or not x.strip() for x in required) or len(set(required)) != len(required):
        return _blocked("required stratum IDs must be unique non-empty strings")
    observed = {}
    for row in strata:
        if not isinstance(row, Mapping):
            return _blocked("stratum row must be a mapping")
        key, gain, count = row.get("stratum_id"), row.get("gain"), row.get("sample_count")
        if not isinstance(key, str) or key not in required or key in observed:
            return _blocked("unknown or duplicate stratum")
        if not _finite(gain) or not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return _blocked("invalid stratum gain or sample count")
        observed[key] = (float(gain), count)
    coverage = len(observed) / len(required)
    missing = sorted(set(required) - set(observed))
    regressions = sorted(key for key, (gain, _) in observed.items() if gain < minimum_gain)
    passed = coverage >= minimum_coverage and not regressions
    return _out({
        "status": "ROBUSTNESS_SUPPORTED" if passed else "ROBUSTNESS_INSUFFICIENT",
        "coverage": coverage, "minimum_coverage": minimum_coverage,
        "missing_strata": missing, "below_threshold_strata": regressions,
        "stratum_count": len(observed),
    })


def stage243_safety_non_regression(
    *, baseline: Mapping, candidate: Mapping, metric_limits: Mapping,
    held: bool = False,
):
    """Check each safety metric against a declared maximum allowed degradation."""
    if held:
        return _blocked("HOLD is active")
    if (not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping)
            or not isinstance(metric_limits, Mapping) or not metric_limits):
        return _blocked("safety metric maps and limits are required")
    if set(baseline) != set(candidate) or set(baseline) != set(metric_limits):
        return _blocked("safety metric keys do not match exactly")
    deltas = {}
    failures = []
    for key, limit in metric_limits.items():
        before, after = baseline[key], candidate[key]
        if not isinstance(key, str) or not key or not all(_finite(v) for v in (before, after, limit)) or limit < 0:
            return _blocked("safety metrics and non-negative limits must be finite")
        delta = after - before
        deltas[key] = delta
        if delta > limit:
            failures.append(key)
    return _out({
        "status": "SAFETY_NON_REGRESSION_SUPPORTED" if not failures else "SAFETY_REGRESSION_DETECTED",
        "metric_deltas": deltas, "exceeded_limits": sorted(failures),
        "metric_count": len(deltas),
    })


def stage244_gain_attribution(
    *, design: Mapping, effect_estimate: float, lower_confidence_bound: float,
    evaluator_id: str, independent_evaluator_id: str, held: bool = False,
):
    """Require a declared controlled design and positive lower bound for attribution support."""
    if held:
        return _blocked("HOLD is active")
    if not isinstance(design, Mapping):
        return _blocked("experiment design is missing")
    required = ("design_type", "treatment_group", "control_group", "assignment_method", "preregistration_digest")
    if any(not isinstance(design.get(key), str) or not design[key].strip() for key in required):
        return _blocked("controlled design fields are incomplete")
    if design["design_type"] not in {"randomized_controlled", "matched_control"}:
        return _blocked("unsupported design type")
    if design["treatment_group"] == design["control_group"]:
        return _blocked("treatment and control groups must differ")
    if not _digest(design["preregistration_digest"]):
        return _blocked("invalid preregistration digest")
    if (not isinstance(evaluator_id, str) or not evaluator_id.strip()
            or evaluator_id != independent_evaluator_id):
        return _blocked("independent evaluator identity is not established")
    if not _finite(effect_estimate) or not _finite(lower_confidence_bound):
        return _blocked("effect estimate and confidence bound must be finite")
    supported = effect_estimate > 0 and lower_confidence_bound > 0
    return _out({
        "status": "GAIN_ATTRIBUTION_SUPPORTED" if supported else "GAIN_ATTRIBUTION_NOT_SUPPORTED",
        "effect_estimate": effect_estimate, "lower_confidence_bound": lower_confidence_bound,
        "design_type": design["design_type"], "evaluator_id": evaluator_id,
        "causal_claim_scope": "bounded to the declared design and assumptions",
    })


def stage245_cycle_evidence_gate(
    *, reproducibility: Mapping, robustness: Mapping,
    safety: Mapping, attribution: Mapping, held: bool = False,
):
    """Combine evidence gates; a pass is review readiness, never runtime permission."""
    if held:
        return _blocked("HOLD is active")
    expected = {
        "reproducibility": (reproducibility, "REPRODUCIBLE"),
        "robustness": (robustness, "ROBUSTNESS_SUPPORTED"),
        "safety": (safety, "SAFETY_NON_REGRESSION_SUPPORTED"),
        "attribution": (attribution, "GAIN_ATTRIBUTION_SUPPORTED"),
    }
    failed = [name for name, (result, status) in expected.items()
              if not isinstance(result, Mapping) or result.get("status") != status]
    return _out({
        "status": "CYCLE_EVIDENCE_READY_FOR_SEPARATE_REVIEW" if not failed else "CYCLE_EVIDENCE_BLOCKED",
        "failed_gates": failed,
        "passed_gates": [name for name in expected if name not in failed],
        "required_next_step": "independent review and separate explicit authorization" if not failed else "resolve evidence gaps without executing",
        "authority": "evidence summary only; no execution or state-transition authority",
        "asi_or_rsi_claim": False,
    })
