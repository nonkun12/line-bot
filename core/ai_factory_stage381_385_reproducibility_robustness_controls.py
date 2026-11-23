"""Proposal-only reproducibility and robustness gates for AI Factory stages 381-385."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_reproducibility_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Stage 381: require declared code, config, data, seed, and environment digests."""
    required = ("code_digest", "config_digest", "data_digest", "seed", "environment_digest")
    errors = [f"manifest_field_missing:{key}" for key in required
              if manifest.get(key) is None or str(manifest.get(key)).strip() == ""]
    return {"stage": 381, "pass": not errors, "errors": errors,
            "manifest_digest": _seal({key: manifest.get(key) for key in required})}


def check_perturbation_coverage(required: Sequence[str],
                                observed: Sequence[str]) -> dict[str, Any]:
    """Stage 382: require exact coverage of predeclared perturbation classes."""
    errors = []
    req, got = set(required), set(observed)
    if not req:
        errors.append("required_perturbations_empty")
    if len(req) != len(required):
        errors.append("required_perturbation_duplicate")
    if len(got) != len(observed):
        errors.append("observed_perturbation_duplicate")
    missing, unexpected = sorted(req - got), sorted(got - req)
    if missing:
        errors.append("perturbation_missing")
    if unexpected:
        errors.append("unexpected_perturbation")
    return {"stage": 382, "pass": not errors, "errors": errors,
            "missing": missing, "unexpected": unexpected}


def check_sensitivity_bounds(observations: Sequence[Mapping[str, Any]], *,
                             maximum_absolute_change: float) -> dict[str, Any]:
    """Stage 383: bound absolute score changes under declared perturbations."""
    errors = []
    changes = []
    if not observations:
        errors.append("sensitivity_observations_empty")
    if not _number(maximum_absolute_change) or maximum_absolute_change < 0:
        errors.append("maximum_absolute_change_invalid")
    for index, item in enumerate(observations):
        baseline, perturbed = item.get("baseline"), item.get("perturbed")
        if not _number(baseline) or not _number(perturbed):
            errors.append(f"sensitivity_value_invalid:{index}")
            continue
        change = abs(perturbed - baseline)
        changes.append(change)
        if _number(maximum_absolute_change) and change - maximum_absolute_change > 1e-12:
            errors.append(f"sensitivity_bound_exceeded:{index}")
    return {"stage": 383, "pass": not errors, "errors": errors,
            "absolute_changes": changes}


def check_repeat_run_stability(scores: Sequence[Any], *,
                               maximum_range: float) -> dict[str, Any]:
    """Stage 384: bound range across repeated declared run scores."""
    errors = []
    valid = []
    if len(scores) < 2:
        errors.append("at_least_two_repeats_required")
    if not _number(maximum_range) or maximum_range < 0:
        errors.append("maximum_range_invalid")
    for index, score in enumerate(scores):
        if not _number(score):
            errors.append(f"repeat_score_invalid:{index}")
        else:
            valid.append(float(score))
    observed_range = max(valid) - min(valid) if len(valid) == len(scores) and valid else None
    if observed_range is not None and _number(maximum_range) and observed_range - maximum_range > 1e-12:
        errors.append("repeat_run_range_exceeded")
    return {"stage": 384, "pass": not errors, "errors": errors,
            "observed_range": observed_range, "repeat_count": len(scores)}


def evaluate_stages_381_385(*, manifest: Mapping[str, Any],
                            required_perturbations: Sequence[str],
                            observed_perturbations: Sequence[str],
                            sensitivity_observations: Sequence[Mapping[str, Any]],
                            maximum_absolute_change: float,
                            repeat_scores: Sequence[Any],
                            maximum_repeat_range: float) -> dict[str, Any]:
    """Stage 385: aggregate reproducibility/robustness gates, proposal-only."""
    checks = [
        check_reproducibility_manifest(manifest),
        check_perturbation_coverage(required_perturbations, observed_perturbations),
        check_sensitivity_bounds(sensitivity_observations,
                                 maximum_absolute_change=maximum_absolute_change),
        check_repeat_run_stability(repeat_scores, maximum_range=maximum_repeat_range),
    ]
    payload = {"checks": checks, "all_pass": all(check["pass"] for check in checks),
               "execution_authorized": False, "proposal_only": True}
    return {"stage": 385, "status": "PASS" if payload["all_pass"] else "BLOCKED",
            "checks": checks, "seal": _seal(payload),
            "execution_authorized": False, "proposal_only": True}
