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
_FALSE_AUTHORITY = {
    "proposal_only": True, "task_execution_authorized": False,
    "experiment_execution_authorized": False, "model_change_authorized": False,
    "merge_deploy_authorized": False, "hold_release_authorized": False,
}


def _blocked(reason):
    return {"status": "INSUFFICIENT_EVIDENCE", "reason": reason, **_FALSE_AUTHORITY}


def _digest(value):
    return isinstance(value, str) and _HEX.fullmatch(value) is not None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _out(payload):
    result = {**payload, **_FALSE_AUTHORITY}
    canonical = {k: v for k, v in result.items() if k != "result_digest"}
    result["result_digest"] = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result


def _valid_result(result, expected_status):
    if not isinstance(result, Mapping) or result.get("status") != expected_status:
        return False
    if any(result.get(key) is not value for key, value in _FALSE_AUTHORITY.items()):
        return False
    claimed = result.get("result_digest")
    if not _digest(claimed):
        return False
    canonical = {k: v for k, v in result.items() if k != "result_digest"}
    try:
        actual = sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        return False
    return claimed == actual


def stage241_reproducibility_check(
    *, runs: Sequence[Mapping], required_runs: int = 3,
    metric_tolerance: float = 0.0, held: bool = False,
):
    """Require independently identified repeated runs bound to identical inputs."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(runs, Sequence) or isinstance(runs, (str, bytes))
            or not isinstance(required_runs, int) or isinstance(required_runs, bool)
            or required_runs < 3 or len(runs) < required_runs
            or not _finite(metric_tolerance) or not 0 <= metric_tolerance <= 1):
        return _blocked("invalid run count or metric tolerance")
    fields = ("artifact_digest", "protocol_digest", "dataset_digest", "suite_digest", "environment_id")
    identities, run_ids, run_digests, metrics = set(), set(), set(), []
    for run in runs:
        if not isinstance(run, Mapping):
            return _blocked("run entry must be a mapping")
        run_id, run_digest = run.get("run_id"), run.get("run_digest")
        if not isinstance(run_id, str) or not run_id.strip() or run_id in run_ids:
            return _blocked("run IDs must be present and unique")
        if not _digest(run_digest) or run_digest in run_digests:
            return _blocked("each run requires a unique valid run digest")
        run_ids.add(run_id)
        run_digests.add(run_digest)
        values = tuple(run.get(key) for key in fields)
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
    identity = next(iter(identities))
    identity_digest = sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    return _out({
        "status": "REPRODUCIBLE" if spread <= metric_tolerance else "REPRODUCIBILITY_FAILED",
        "run_count": len(runs), "metric_min": min(metrics), "metric_max": max(metrics),
        "metric_spread": spread, "metric_tolerance": metric_tolerance,
        "identity_digest": identity_digest,
    })


def stage242_stratified_robustness(
    *, strata: Sequence[Mapping], required_strata: Sequence[str],
    identity_digest: str, minimum_coverage: float = 1.0,
    minimum_gain: float = 0.0, minimum_sample_count: int = 2, held: bool = False,
):
    """Require complete declared slice coverage and minimum per-slice evidence."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(strata, Sequence) or isinstance(strata, (str, bytes))
            or not isinstance(required_strata, Sequence) or isinstance(required_strata, (str, bytes))
            or not required_strata or not _digest(identity_digest)
            or not _finite(minimum_coverage) or minimum_coverage != 1.0
            or not _finite(minimum_gain) or minimum_gain < 0
            or not isinstance(minimum_sample_count, int) or isinstance(minimum_sample_count, bool)
            or minimum_sample_count < 2):
        return _blocked("invalid robustness inputs; complete coverage and bounded thresholds are required")
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
        if not _finite(gain) or not isinstance(count, int) or isinstance(count, bool) or count < minimum_sample_count:
            return _blocked("invalid stratum gain or insufficient sample count")
        observed[key] = (float(gain), count)
    missing = sorted(set(required) - set(observed))
    regressions = sorted(key for key, (gain, _) in observed.items() if gain < minimum_gain)
    passed = not missing and not regressions
    return _out({
        "status": "ROBUSTNESS_SUPPORTED" if passed else "ROBUSTNESS_INSUFFICIENT",
        "identity_digest": identity_digest, "coverage": len(observed) / len(required),
        "minimum_coverage": 1.0, "missing_strata": missing,
        "below_threshold_strata": regressions, "stratum_count": len(observed),
    })


def stage243_safety_non_regression(
    *, baseline: Mapping, candidate: Mapping, metric_limits: Mapping,
    identity_digest: str, held: bool = False,
):
    """Check direction-aware safety degradation; unknown directions fail closed."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if (not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping)
            or not isinstance(metric_limits, Mapping) or not metric_limits
            or not _digest(identity_digest)):
        return _blocked("safety metric maps, limits and identity are required")
    if set(baseline) != set(candidate) or set(baseline) != set(metric_limits):
        return _blocked("safety metric keys do not match exactly")
    degradations, failures = {}, []
    for key, spec in metric_limits.items():
        before, after = baseline[key], candidate[key]
        if (not isinstance(key, str) or not key or not isinstance(spec, Mapping)
                or spec.get("direction") not in {"higher", "lower"}
                or not _finite(spec.get("max_degradation"))
                or spec["max_degradation"] < 0 or not _finite(before) or not _finite(after)):
            return _blocked("each metric needs finite values, direction and non-negative degradation limit")
        degradation = before - after if spec["direction"] == "higher" else after - before
        degradations[key] = degradation
        if degradation > spec["max_degradation"]:
            failures.append(key)
    return _out({
        "status": "SAFETY_NON_REGRESSION_SUPPORTED" if not failures else "SAFETY_REGRESSION_DETECTED",
        "identity_digest": identity_digest, "metric_degradations": degradations,
        "exceeded_limits": sorted(failures), "metric_count": len(degradations),
    })


def stage244_gain_attribution(
    *, design: Mapping, effect_estimate: float, lower_confidence_bound: float,
    evaluator_id: str, proposer_id: str, runner_id: str,
    identity_digest: str, protocol_digest: str, held: bool = False,
):
    """Require distinct proposer/runner/evaluator identities and a valid lower bound."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    if not isinstance(design, Mapping) or not _digest(identity_digest) or not _digest(protocol_digest):
        return _blocked("experiment design, identity digest and protocol digest are required")
    required = ("design_type", "treatment_group", "control_group", "assignment_method", "preregistration_digest")
    if any(not isinstance(design.get(key), str) or not design[key].strip() for key in required):
        return _blocked("controlled design fields are incomplete")
    if design["design_type"] not in {"randomized_controlled", "matched_control"}:
        return _blocked("unsupported design type")
    expected_assignment = {"randomized_controlled": "randomized", "matched_control": "matched"}[design["design_type"]]
    if design["assignment_method"] != expected_assignment:
        return _blocked("assignment method must match the declared experiment design")
    if design["treatment_group"].strip() == design["control_group"].strip():
        return _blocked("treatment and control groups must differ")
    if not _digest(design["preregistration_digest"]) or design["preregistration_digest"] != protocol_digest:
        return _blocked("preregistration digest must match the evaluated protocol digest")
    identities = (evaluator_id, proposer_id, runner_id)
    if any(not isinstance(x, str) or not x.strip() for x in identities):
        return _blocked("proposer, runner and evaluator identities are required")
    if len({x.strip() for x in identities}) != 3:
        return _blocked("proposer, runner and evaluator must be distinct")
    if (not _finite(effect_estimate) or not _finite(lower_confidence_bound)
            or lower_confidence_bound > effect_estimate):
        return _blocked("effect estimate and ordered confidence bound must be finite")
    supported = effect_estimate > 0 and lower_confidence_bound > 0
    return _out({
        "status": "GAIN_ATTRIBUTION_SUPPORTED" if supported else "GAIN_ATTRIBUTION_NOT_SUPPORTED",
        "identity_digest": identity_digest, "effect_estimate": effect_estimate,
        "lower_confidence_bound": lower_confidence_bound,
        "design_type": design["design_type"], "evaluator_id": evaluator_id,
        "causal_claim_scope": "bounded to the declared design and assumptions",
    })


def stage245_cycle_evidence_gate(
    *, reproducibility: Mapping, robustness: Mapping,
    safety: Mapping, attribution: Mapping, held: bool = False,
):
    """Verify result integrity and common experiment identity; never grants authority."""
    if held is not False:
        return _blocked("HOLD state must be explicitly false")
    expected = {
        "reproducibility": (reproducibility, "REPRODUCIBLE"),
        "robustness": (robustness, "ROBUSTNESS_SUPPORTED"),
        "safety": (safety, "SAFETY_NON_REGRESSION_SUPPORTED"),
        "attribution": (attribution, "GAIN_ATTRIBUTION_SUPPORTED"),
    }
    failed = []
    identities = set()
    for name, (result, status) in expected.items():
        if not _valid_result(result, status):
            failed.append(name)
        elif not _digest(result.get("identity_digest")):
            failed.append(name)
        else:
            identities.add(result["identity_digest"])
    if len(identities) != 1:
        failed = sorted(set(failed) | set(expected))
    return _out({
        "status": "CYCLE_EVIDENCE_READY_FOR_SEPARATE_REVIEW" if not failed else "CYCLE_EVIDENCE_BLOCKED",
        "failed_gates": failed,
        "passed_gates": [name for name in expected if name not in failed],
        "identity_digest": next(iter(identities)) if len(identities) == 1 else None,
        "required_next_step": "independent review and separate explicit authorization" if not failed else "resolve evidence gaps without executing",
        "authority": "evidence summary only; no execution or state-transition authority",
        "asi_or_rsi_claim": False,
    })
