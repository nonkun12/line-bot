"""Proposal-only improvement-evidence gates for AI Factory stages 386-390."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_paired_sample_alignment(candidate: Sequence[Mapping[str, Any]],
                                  baseline: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 386: require unique, nonempty, exactly aligned paired sample IDs."""
    errors = []
    def ids(rows: Sequence[Mapping[str, Any]], label: str) -> list[str]:
        values = [str(row.get("sample_id", "")).strip() for row in rows]
        if not values:
            errors.append(f"{label}_empty")
        if any(not value for value in values):
            errors.append(f"{label}_sample_id_missing")
        if len(set(values)) != len(values):
            errors.append(f"{label}_sample_id_duplicate")
        return values
    candidate_ids = ids(candidate, "candidate")
    baseline_ids = ids(baseline, "baseline")
    missing = sorted(set(baseline_ids) - set(candidate_ids))
    unexpected = sorted(set(candidate_ids) - set(baseline_ids))
    if missing:
        errors.append("candidate_sample_missing")
    if unexpected:
        errors.append("unexpected_candidate_sample")
    return {"stage": 386, "pass": not errors, "errors": errors,
            "missing_candidate_samples": missing, "unexpected_candidate_samples": unexpected,
            "paired_sample_count": len(set(candidate_ids) & set(baseline_ids))}


def check_minimum_improvement(paired_deltas: Sequence[Any], *,
                              minimum_mean_improvement: float) -> dict[str, Any]:
    """Stage 387: require a minimum mean paired improvement; values are oriented positive=better."""
    errors = []
    if not paired_deltas:
        errors.append("paired_deltas_empty")
    if not _finite(minimum_mean_improvement) or minimum_mean_improvement < 0:
        errors.append("minimum_mean_improvement_invalid")
    if any(not _finite(value) for value in paired_deltas):
        errors.append("paired_delta_invalid")
    mean = sum(float(value) for value in paired_deltas) / len(paired_deltas) if paired_deltas and not any(not _finite(v) for v in paired_deltas) else None
    if mean is not None and _finite(minimum_mean_improvement) and mean + 1e-12 < minimum_mean_improvement:
        errors.append("minimum_improvement_not_met")
    return {"stage": 387, "pass": not errors, "errors": errors,
            "mean_improvement": mean, "sample_count": len(paired_deltas)}


def check_guardrail_metrics(metrics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 388: require each guardrail metric to remain within declared degradation limits."""
    errors = []
    results = []
    if not metrics:
        errors.append("guardrail_metrics_empty")
    for index, item in enumerate(metrics):
        baseline, candidate = item.get("baseline"), item.get("candidate")
        direction, limit = item.get("direction"), item.get("maximum_degradation")
        if not _finite(baseline) or not _finite(candidate):
            errors.append(f"guardrail_value_invalid:{index}")
            continue
        if direction not in ("higher", "lower"):
            errors.append(f"guardrail_direction_invalid:{index}")
            continue
        if not _finite(limit) or limit < 0:
            errors.append(f"maximum_degradation_invalid:{index}")
            continue
        degradation = baseline - candidate if direction == "higher" else candidate - baseline
        passed = degradation <= limit + 1e-12
        results.append({"index": index, "degradation": max(0.0, degradation), "pass": passed})
        if not passed:
            errors.append(f"guardrail_degradation_exceeded:{index}")
    return {"stage": 388, "pass": not errors, "errors": errors, "metrics": results}


def check_benchmark_compatibility(candidate: Mapping[str, Any],
                                  baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Stage 389: require exact benchmark, protocol, and metric-definition identity."""
    errors = []
    fields = ("benchmark_id", "protocol_digest", "metric_schema_digest")
    for field in fields:
        left, right = str(candidate.get(field, "")).strip(), str(baseline.get(field, "")).strip()
        if not left or not right:
            errors.append(f"benchmark_identity_missing:{field}")
        elif left != right:
            errors.append(f"benchmark_identity_mismatch:{field}")
    return {"stage": 389, "pass": not errors, "errors": errors}


def evaluate_stages_386_390(*, candidate_samples: Sequence[Mapping[str, Any]],
                            baseline_samples: Sequence[Mapping[str, Any]],
                            paired_improvements: Sequence[Any],
                            minimum_mean_improvement: float,
                            guardrail_metrics: Sequence[Mapping[str, Any]],
                            candidate_benchmark: Mapping[str, Any],
                            baseline_benchmark: Mapping[str, Any]) -> dict[str, Any]:
    """Stage 390: integrated evidence gate; never authorizes execution or promotion."""
    checks = [
        check_paired_sample_alignment(candidate_samples, baseline_samples),
        check_minimum_improvement(paired_improvements,
                                  minimum_mean_improvement=minimum_mean_improvement),
        check_guardrail_metrics(guardrail_metrics),
        check_benchmark_compatibility(candidate_benchmark, baseline_benchmark),
    ]
    payload = {"checks": checks, "all_pass": all(check["pass"] for check in checks),
               "execution_authorized": False, "promotion_authorized": False,
               "proposal_only": True}
    return {"stage": 390, "status": "PASS" if payload["all_pass"] else "BLOCKED",
            "checks": checks, "seal": _seal(payload),
            "execution_authorized": False, "promotion_authorized": False,
            "proposal_only": True}
