"""Proposal-only generalization evidence gates for AI Factory stages 391-395."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _seal(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check_slice_coverage(slices: Sequence[Mapping[str, Any]], *,
                         required_slice_ids: Sequence[str],
                         minimum_samples_per_slice: int) -> dict[str, Any]:
    """Stage 391: require exact, unique declared slice coverage and minimum counts."""
    errors: list[str] = []
    required = list(required_slice_ids)
    if not required or any(not isinstance(x, str) or not x.strip() for x in required):
        errors.append("required_slice_ids_invalid")
    if len(set(required)) != len(required):
        errors.append("required_slice_ids_duplicate")
    if isinstance(minimum_samples_per_slice, bool) or not isinstance(minimum_samples_per_slice, int) or minimum_samples_per_slice <= 0:
        errors.append("minimum_samples_per_slice_invalid")
    seen: set[str] = set()
    for i, item in enumerate(slices):
        sid, count = item.get("slice_id"), item.get("sample_count")
        if not isinstance(sid, str) or not sid.strip():
            errors.append(f"slice_id_invalid:{i}")
            continue
        if sid in seen:
            errors.append(f"slice_id_duplicate:{sid}")
        seen.add(sid)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            errors.append(f"slice_sample_count_invalid:{sid}")
        elif isinstance(minimum_samples_per_slice, int) and not isinstance(minimum_samples_per_slice, bool) and minimum_samples_per_slice > 0 and count < minimum_samples_per_slice:
            errors.append(f"slice_below_minimum:{sid}")
    missing = sorted(set(required) - seen)
    unexpected = sorted(seen - set(required))
    errors.extend(f"slice_missing:{x}" for x in missing)
    errors.extend(f"slice_unexpected:{x}" for x in unexpected)
    return {"stage": 391, "pass": not errors, "errors": errors,
            "required_slice_count": len(required), "observed_slice_count": len(seen)}


def check_worst_case_improvement(improvements: Sequence[Any], *,
                                 minimum_improvement: float) -> dict[str, Any]:
    """Stage 392: enforce a declared lower bound on every slice improvement."""
    errors: list[str] = []
    if not improvements:
        errors.append("improvements_empty")
    if not _finite(minimum_improvement):
        errors.append("minimum_improvement_invalid")
    valid = []
    for i, value in enumerate(improvements):
        if not _finite(value):
            errors.append(f"improvement_invalid:{i}")
        else:
            valid.append(float(value))
            if _finite(minimum_improvement) and value < minimum_improvement:
                errors.append(f"worst_case_improvement_below_minimum:{i}")
    return {"stage": 392, "pass": not errors, "errors": errors,
            "worst_case_improvement": min(valid) if len(valid) == len(improvements) and valid else None}


def check_guardrail_coverage(guardrails: Sequence[Mapping[str, Any]], *,
                             required_guardrail_ids: Sequence[str]) -> dict[str, Any]:
    """Stage 393: require every named guardrail and enforce its directional tolerance."""
    errors: list[str] = []
    required = list(required_guardrail_ids)
    if not required or any(not isinstance(x, str) or not x.strip() for x in required):
        errors.append("required_guardrail_ids_invalid")
    if len(set(required)) != len(required):
        errors.append("required_guardrail_ids_duplicate")
    seen: set[str] = set()
    for i, item in enumerate(guardrails):
        gid = item.get("guardrail_id")
        if not isinstance(gid, str) or not gid.strip():
            errors.append(f"guardrail_id_invalid:{i}")
            continue
        if gid in seen:
            errors.append(f"guardrail_id_duplicate:{gid}")
        seen.add(gid)
        baseline, current, direction, tolerance = (
            item.get("baseline"), item.get("current"), item.get("direction"),
            item.get("maximum_regression"))
        if not _finite(baseline) or not _finite(current):
            errors.append(f"guardrail_value_invalid:{gid}")
            continue
        if direction not in ("higher", "lower"):
            errors.append(f"guardrail_direction_invalid:{gid}")
            continue
        if not _finite(tolerance) or tolerance < 0:
            errors.append(f"guardrail_tolerance_invalid:{gid}")
            continue
        regression = baseline - current if direction == "higher" else current - baseline
        if regression > tolerance + 1e-12:
            errors.append(f"guardrail_regression_exceeded:{gid}")
    errors.extend(f"guardrail_missing:{x}" for x in sorted(set(required) - seen))
    errors.extend(f"guardrail_unexpected:{x}" for x in sorted(seen - set(required)))
    return {"stage": 393, "pass": not errors, "errors": errors,
            "required_guardrail_count": len(required), "observed_guardrail_count": len(seen)}


def check_cohort_replicates(cohorts: Sequence[Mapping[str, Any]], *,
                            minimum_cohorts: int,
                            minimum_improvement: float) -> dict[str, Any]:
    """Stage 394: require unique independent-cohort declarations meeting improvement floor."""
    errors: list[str] = []
    if isinstance(minimum_cohorts, bool) or not isinstance(minimum_cohorts, int) or minimum_cohorts <= 0:
        errors.append("minimum_cohorts_invalid")
    if not _finite(minimum_improvement):
        errors.append("minimum_improvement_invalid")
    seen: set[str] = set()
    for i, cohort in enumerate(cohorts):
        cid, improvement = cohort.get("cohort_id"), cohort.get("improvement")
        if not isinstance(cid, str) or not cid.strip():
            errors.append(f"cohort_id_invalid:{i}")
            continue
        if cid in seen:
            errors.append(f"cohort_id_duplicate:{cid}")
        seen.add(cid)
        if not _finite(improvement):
            errors.append(f"cohort_improvement_invalid:{cid}")
        elif _finite(minimum_improvement) and improvement < minimum_improvement:
            errors.append(f"cohort_improvement_below_minimum:{cid}")
    if isinstance(minimum_cohorts, int) and not isinstance(minimum_cohorts, bool) and minimum_cohorts > 0 and len(seen) < minimum_cohorts:
        errors.append("cohort_count_below_minimum")
    return {"stage": 394, "pass": not errors, "errors": errors,
            "observed_cohort_count": len(seen)}


def evaluate_stages_391_395(*, slices: Sequence[Mapping[str, Any]],
                            required_slice_ids: Sequence[str],
                            minimum_samples_per_slice: int,
                            slice_improvements: Sequence[Any],
                            minimum_worst_case_improvement: float,
                            guardrails: Sequence[Mapping[str, Any]],
                            required_guardrail_ids: Sequence[str],
                            cohorts: Sequence[Mapping[str, Any]],
                            minimum_cohorts: int,
                            minimum_cohort_improvement: float) -> dict[str, Any]:
    """Stage 395: aggregate generalization evidence; proposal-only and fail-closed."""
    checks = [
        check_slice_coverage(slices, required_slice_ids=required_slice_ids,
                             minimum_samples_per_slice=minimum_samples_per_slice),
        check_worst_case_improvement(slice_improvements,
                                     minimum_improvement=minimum_worst_case_improvement),
        check_guardrail_coverage(guardrails, required_guardrail_ids=required_guardrail_ids),
        check_cohort_replicates(cohorts, minimum_cohorts=minimum_cohorts,
                                minimum_improvement=minimum_cohort_improvement),
    ]
    payload = {"checks": checks, "all_pass": all(x["pass"] for x in checks),
               "proposal_only": True, "execution_authorized": False,
               "promotion_authorized": False}
    return {"stage": 395, "status": "PASS" if payload["all_pass"] else "BLOCKED",
            "checks": checks, "seal": _seal(payload), "proposal_only": True,
            "execution_authorized": False, "promotion_authorized": False}
