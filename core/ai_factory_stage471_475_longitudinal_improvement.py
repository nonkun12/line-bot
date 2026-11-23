"""Longitudinal improvement evidence checks for AI Factory stages 471-475."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_history_completeness(history: Sequence[Mapping[str, Any]], *,
                               expected_cycles: int) -> dict[str, Any]:
    """471: require a complete, ordered, unique improvement-cycle history."""
    errors: list[str] = []
    if not isinstance(expected_cycles, int) or isinstance(expected_cycles, bool) or expected_cycles < 1:
        errors.append("history_expected_cycles_invalid")
        expected = 1
    else:
        expected = expected_cycles
    seen: set[str] = set()
    previous = 0
    for i, item in enumerate(history):
        cycle_id, sequence = item.get("cycle_id"), item.get("sequence")
        if not isinstance(cycle_id, str) or not cycle_id.strip():
            errors.append(f"history_cycle_id_invalid:{i}")
        elif cycle_id in seen:
            errors.append(f"history_cycle_duplicate:{cycle_id}")
        else:
            seen.add(cycle_id)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence != previous + 1:
            errors.append(f"history_sequence_invalid:{i}")
        else:
            previous = sequence
        for field in ("baseline_ref", "candidate_ref", "evaluation_ref"):
            if not isinstance(item.get(field), str) or not item.get(field).strip():
                errors.append(f"history_{field}_missing:{i}")
    if len(history) != expected:
        errors.append("history_cycle_count_mismatch")
    return {"stage": 471, "pass": not errors, "errors": errors,
            "observed_cycles": len(history), "expected_cycles": expected}


def check_sustained_performance(cycle_scores: Sequence[float], *,
                                minimum_cycles: int, minimum_score: float,
                                required_consecutive_passes: int) -> dict[str, Any]:
    """472: require sufficient repeated scores and a trailing consecutive pass window."""
    errors: list[str] = []
    if not isinstance(minimum_cycles, int) or isinstance(minimum_cycles, bool) or minimum_cycles < 1:
        errors.append("sustained_minimum_cycles_invalid")
        minimum = 1
    else:
        minimum = minimum_cycles
    if not isinstance(required_consecutive_passes, int) or isinstance(required_consecutive_passes, bool) or required_consecutive_passes < 1:
        errors.append("sustained_consecutive_count_invalid")
        consecutive = 1
    else:
        consecutive = required_consecutive_passes
    if not _finite(minimum_score):
        errors.append("sustained_minimum_score_invalid")
        threshold = 0.0
    else:
        threshold = float(minimum_score)
    if len(cycle_scores) < minimum:
        errors.append("sustained_cycle_count_below_minimum")
    if len(cycle_scores) < consecutive:
        errors.append("sustained_consecutive_window_missing")
    if any(not _finite(score) for score in cycle_scores):
        errors.append("sustained_score_invalid")
    trailing = cycle_scores[-consecutive:] if len(cycle_scores) >= consecutive else cycle_scores
    if trailing and all(_finite(score) for score in trailing):
        if any(score < threshold - 1e-12 for score in trailing):
            errors.append("sustained_consecutive_threshold_failed")
    return {"stage": 472, "pass": not errors, "errors": errors,
            "cycle_count": len(cycle_scores), "trailing_scores": list(trailing),
            "minimum_score": threshold, "required_consecutive_passes": consecutive}


def check_regression_trend(cycle_scores: Sequence[float], *,
                           maximum_drop: float, window_size: int) -> dict[str, Any]:
    """473: detect a decline between the first and last score in the trailing window."""
    errors: list[str] = []
    if not _finite(maximum_drop) or maximum_drop < 0:
        errors.append("trend_maximum_drop_invalid")
        limit = 0.0
    else:
        limit = float(maximum_drop)
    if not isinstance(window_size, int) or isinstance(window_size, bool) or window_size < 2:
        errors.append("trend_window_size_invalid")
        window = 2
    else:
        window = window_size
    if len(cycle_scores) < window:
        errors.append("trend_window_insufficient")
        selected = list(cycle_scores)
    else:
        selected = list(cycle_scores[-window:])
    if any(not _finite(score) for score in selected):
        errors.append("trend_score_invalid")
        drop = None
    elif len(selected) < 2:
        drop = None
    else:
        drop = float(selected[0] - selected[-1])
        if drop > limit + 1e-12:
            errors.append("trend_regression_exceeded")
    return {"stage": 473, "pass": not errors, "errors": errors,
            "window_scores": selected, "observed_drop": drop, "maximum_drop": limit}


def check_evaluator_consensus(results: Sequence[Mapping[str, Any]], *,
                              minimum_evaluators: int, maximum_spread: float) -> dict[str, Any]:
    """474: require distinct evaluator declarations and bounded score spread."""
    errors: list[str] = []
    if not isinstance(minimum_evaluators, int) or isinstance(minimum_evaluators, bool) or minimum_evaluators < 2:
        errors.append("consensus_minimum_evaluators_invalid")
        minimum = 2
    else:
        minimum = minimum_evaluators
    if not _finite(maximum_spread) or maximum_spread < 0:
        errors.append("consensus_maximum_spread_invalid")
        spread_limit = 0.0
    else:
        spread_limit = float(maximum_spread)
    by_id: dict[str, float] = {}
    for i, result in enumerate(results):
        evaluator = result.get("evaluator_id")
        score = result.get("score")
        if not isinstance(evaluator, str) or not evaluator.strip():
            errors.append(f"consensus_evaluator_id_invalid:{i}")
        elif evaluator in by_id:
            errors.append(f"consensus_evaluator_duplicate:{evaluator}")
        elif not _finite(score):
            errors.append(f"consensus_score_invalid:{evaluator}")
        else:
            by_id[evaluator] = float(score)
    if len(by_id) < minimum:
        errors.append("consensus_evaluator_count_below_minimum")
    spread = max(by_id.values()) - min(by_id.values()) if by_id else None
    if spread is not None and spread > spread_limit + 1e-12:
        errors.append("consensus_score_spread_exceeded")
    return {"stage": 474, "pass": not errors, "errors": errors,
            "evaluator_count": len(by_id), "score_spread": spread,
            "maximum_spread": spread_limit}


def evaluate_stages_471_475(*, history: Sequence[Mapping[str, Any]],
                            expected_cycles: int, cycle_scores: Sequence[float],
                            minimum_cycles: int, minimum_score: float,
                            required_consecutive_passes: int, maximum_drop: float,
                            trend_window_size: int, evaluator_results: Sequence[Mapping[str, Any]],
                            minimum_evaluators: int, maximum_evaluator_spread: float) -> dict[str, Any]:
    """475: aggregate longitudinal evidence; any failed declaration yields HOLD."""
    checks = [
        check_history_completeness(history, expected_cycles=expected_cycles),
        check_sustained_performance(cycle_scores, minimum_cycles=minimum_cycles,
                                   minimum_score=minimum_score,
                                   required_consecutive_passes=required_consecutive_passes),
        check_regression_trend(cycle_scores, maximum_drop=maximum_drop,
                               window_size=trend_window_size),
        check_evaluator_consensus(evaluator_results, minimum_evaluators=minimum_evaluators,
                                  maximum_spread=maximum_evaluator_spread),
    ]
    passed = all(check["pass"] for check in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 475, "status": "READY_FOR_REVIEW" if passed else "HOLD",
            "checks": checks, "seal": _seal(record), "longitudinal_improvement_verified": False,
            "evaluator_independence_verified": False, "execution_authorized": False,
            "promotion_authorized": False, "proposal_only": True}
