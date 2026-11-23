"""Evaluation-integrity and aggregate governance controls for AI Factory stages 476-480."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from core.ai_factory_stage471_475_longitudinal_improvement import (
    check_evaluator_consensus, check_history_completeness, check_regression_trend,
    check_sustained_performance,
)


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_protocol_stability(cycles: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """476: require protocol/task/scoring definitions to remain stable across cycles."""
    errors: list[str] = []
    fields = ("protocol_id", "protocol_version", "task_set_id", "metric_id", "scoring_method")
    if not cycles:
        errors.append("protocol_cycles_empty")
    reference: dict[str, Any] | None = None
    for i, cycle in enumerate(cycles):
        current = {field: cycle.get(field) for field in fields}
        for field, value in current.items():
            if not _text(value):
                errors.append(f"protocol_{field}_missing:{i}")
        if reference is None:
            reference = current
        elif current != reference:
            errors.append(f"protocol_definition_drift:{i}")
    return {"stage": 476, "pass": not errors, "errors": errors,
            "protocol_definition": reference}


def check_score_contract(scores: Sequence[Mapping[str, Any]], *,
                         minimum_score: float, maximum_score: float,
                         direction: str) -> dict[str, Any]:
    """477: validate score bounds and consistent declared optimization direction."""
    errors: list[str] = []
    if not _finite(minimum_score) or not _finite(maximum_score) or minimum_score >= maximum_score:
        errors.append("score_bounds_invalid")
        lower, upper = 0.0, 1.0
    else:
        lower, upper = float(minimum_score), float(maximum_score)
    if direction not in ("higher_is_better", "lower_is_better"):
        errors.append("score_direction_invalid")
    if not scores:
        errors.append("score_records_empty")
    ids: set[str] = set()
    values: list[float] = []
    for i, row in enumerate(scores):
        metric_id, value, row_direction = row.get("metric_id"), row.get("score"), row.get("direction")
        if not _text(metric_id):
            errors.append(f"score_metric_id_invalid:{i}")
        elif metric_id in ids:
            errors.append(f"score_metric_duplicate:{metric_id}")
        else:
            ids.add(metric_id)
        if not _finite(value):
            errors.append(f"score_value_invalid:{i}")
        else:
            values.append(float(value))
            if value < lower or value > upper:
                errors.append(f"score_out_of_bounds:{i}")
        if row_direction != direction:
            errors.append(f"score_direction_mismatch:{i}")
    return {"stage": 477, "pass": not errors, "errors": errors,
            "score_count": len(values), "minimum_score": lower,
            "maximum_score": upper, "direction": direction}


def check_cycle_completion(cycles: Sequence[Mapping[str, Any]], *,
                           required_states: Sequence[str]) -> dict[str, Any]:
    """478: reject interrupted, skipped, or unknown cycle states."""
    errors: list[str] = []
    allowed = set(required_states)
    if not allowed or any(not _text(x) for x in required_states):
        errors.append("cycle_required_states_invalid")
    seen: set[str] = set()
    for i, cycle in enumerate(cycles):
        cid, state = cycle.get("cycle_id"), cycle.get("state")
        if not _text(cid):
            errors.append(f"cycle_id_invalid:{i}")
        elif cid in seen:
            errors.append(f"cycle_id_duplicate:{cid}")
        else:
            seen.add(cid)
        if state not in allowed:
            errors.append(f"cycle_state_not_allowed:{cid if _text(cid) else i}")
    return {"stage": 478, "pass": not errors, "errors": errors,
            "cycle_count": len(cycles), "required_states": sorted(allowed)}


def check_evidence_traceability(cycles: Sequence[Mapping[str, Any]], *,
                                required_evidence_fields: Sequence[str]) -> dict[str, Any]:
    """479: require unique, non-empty evidence references and SHA-256-shaped digests."""
    errors: list[str] = []
    if not required_evidence_fields or any(not _text(x) for x in required_evidence_fields):
        errors.append("evidence_fields_invalid")
    seen_refs: set[str] = set()
    for i, cycle in enumerate(cycles):
        for field in required_evidence_fields:
            value = cycle.get(field)
            if not _text(value):
                errors.append(f"evidence_reference_missing:{i}:{field}")
            elif value in seen_refs:
                errors.append(f"evidence_reference_duplicate:{field}")
            else:
                seen_refs.add(value)
        digest = cycle.get("evidence_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            errors.append(f"evidence_digest_invalid:{i}")
    return {"stage": 479, "pass": not errors, "errors": errors,
            "unique_reference_count": len(seen_refs), "cycle_count": len(cycles)}


def evaluate_stages_476_480(*, cycles: Sequence[Mapping[str, Any]],
                            expected_cycles: int, cycle_scores: Sequence[float],
                            minimum_cycles: int, minimum_score: float,
                            required_consecutive_passes: int, maximum_drop: float,
                            trend_window_size: int, evaluator_results: Sequence[Mapping[str, Any]],
                            minimum_evaluators: int, maximum_evaluator_spread: float,
                            score_records: Sequence[Mapping[str, Any]],
                            score_minimum: float, score_maximum: float, direction: str,
                            required_states: Sequence[str],
                            required_evidence_fields: Sequence[str],
                            unresolved_holds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """480: integrated longitudinal readiness; unresolved HOLDs always block."""
    checks = [
        check_history_completeness(cycles, expected_cycles=expected_cycles),
        check_sustained_performance(cycle_scores, minimum_cycles=minimum_cycles,
                                    minimum_score=minimum_score,
                                    required_consecutive_passes=required_consecutive_passes),
        check_regression_trend(cycle_scores, maximum_drop=maximum_drop,
                               window_size=trend_window_size),
        check_evaluator_consensus(evaluator_results, minimum_evaluators=minimum_evaluators,
                                  maximum_spread=maximum_evaluator_spread),
        check_protocol_stability(cycles),
        check_score_contract(score_records, minimum_score=score_minimum,
                             maximum_score=score_maximum, direction=direction),
        check_cycle_completion(cycles, required_states=required_states),
        check_evidence_traceability(cycles, required_evidence_fields=required_evidence_fields),
    ]
    hold_errors: list[str] = []
    hold_ids: set[str] = set()
    for i, hold in enumerate(unresolved_holds):
        hid = hold.get("hold_id")
        if not _text(hid) or hid in hold_ids:
            hold_errors.append(f"hold_id_invalid_or_duplicate:{i}")
        else:
            hold_ids.add(hid)
        for field in ("reason", "required_evidence"):
            if not _text(hold.get(field)):
                hold_errors.append(f"hold_{field}_missing:{i}")
    if unresolved_holds:
        hold_errors.append("unresolved_holds_present")
    checks.append({"stage": 480, "pass": not hold_errors, "errors": hold_errors,
                   "unresolved_hold_count": len(unresolved_holds)})
    passed = all(check["pass"] for check in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 480, "status": "READY_FOR_REVIEW" if passed else "HOLD",
            "checks": checks, "seal": _seal(record),
            "improvement_verified": False, "evidence_authenticity_verified": False,
            "hold_release_authorized": False, "execution_authorized": False,
            "promotion_authorized": False, "merge_authorized": False,
            "deployment_authorized": False, "proposal_only": True}
