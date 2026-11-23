"""Reproducibility and cross-evaluator governance for AI Factory stages 486-490."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from core.ai_factory_stage481_485_evaluation_independence import (
    check_calibration_evidence, check_dataset_lineage, check_external_reference,
    check_split_disjointness,
)


def _seal(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_reproduction_alignment(runs: Sequence[Mapping[str, Any]], *,
                                 required_fields: Sequence[str]) -> dict[str, Any]:
    """486: require repeat runs to declare identical protocol/config/data fingerprints."""
    errors: list[str] = []
    if len(runs) < 2:
        errors.append("reproduction_runs_insufficient")
    if not required_fields or any(not _text(field) for field in required_fields):
        errors.append("reproduction_required_fields_invalid")
    seen: set[str] = set()
    reference: dict[str, Any] | None = None
    for i, run in enumerate(runs):
        run_id = run.get("run_id")
        if not _text(run_id) or run_id in seen:
            errors.append(f"reproduction_run_id_invalid_or_duplicate:{i}")
        else:
            seen.add(run_id)
        current = {field: run.get(field) for field in required_fields}
        for field, value in current.items():
            if not _text(value):
                errors.append(f"reproduction_field_missing:{i}:{field}")
        if reference is None:
            reference = current
        elif current != reference:
            errors.append(f"reproduction_fingerprint_mismatch:{i}")
    return {"stage": 486, "pass": not errors, "errors": errors,
            "run_count": len(runs), "fingerprint_fields": list(required_fields)}


def check_repeated_run_variance(runs: Sequence[Mapping[str, Any]], *,
                                score_field: str, maximum_spread: float,
                                minimum_runs: int) -> dict[str, Any]:
    """487: require enough repeated scores and enforce a maximum observed spread."""
    errors: list[str] = []
    if not _text(score_field):
        errors.append("variance_score_field_invalid")
        field = "score"
    else:
        field = score_field
    if not isinstance(minimum_runs, int) or isinstance(minimum_runs, bool) or minimum_runs < 2:
        errors.append("variance_minimum_runs_invalid")
        minimum = 2
    else:
        minimum = minimum_runs
    if not _finite(maximum_spread) or maximum_spread < 0:
        errors.append("variance_maximum_spread_invalid")
        limit = 0.0
    else:
        limit = float(maximum_spread)
    values = [run.get(field) for run in runs]
    if len(values) < minimum:
        errors.append("variance_run_count_below_minimum")
    if any(not _finite(value) for value in values):
        errors.append("variance_score_invalid")
        spread = None
    else:
        spread = max(values) - min(values) if values else None
        if spread is not None and spread > limit + 1e-12:
            errors.append("variance_spread_exceeded")
    return {"stage": 487, "pass": not errors, "errors": errors,
            "run_count": len(runs), "score_spread": spread, "maximum_spread": limit}


def check_environment_stability(runs: Sequence[Mapping[str, Any]], *,
                                required_fields: Sequence[str]) -> dict[str, Any]:
    """488: reject environment fingerprint drift across repeated runs."""
    errors: list[str] = []
    if not runs:
        errors.append("environment_runs_empty")
    if not required_fields or any(not _text(field) for field in required_fields):
        errors.append("environment_required_fields_invalid")
    baseline: dict[str, Any] | None = None
    for i, run in enumerate(runs):
        current = {field: run.get(field) for field in required_fields}
        for field, value in current.items():
            if not _text(value):
                errors.append(f"environment_field_missing:{i}:{field}")
        if baseline is None:
            baseline = current
        elif current != baseline:
            errors.append(f"environment_fingerprint_drift:{i}")
    return {"stage": 488, "pass": not errors, "errors": errors,
            "environment_fields": list(required_fields), "run_count": len(runs)}


def check_evaluator_disagreement(results: Sequence[Mapping[str, Any]], *,
                                 minimum_evaluators: int) -> dict[str, Any]:
    """489: detect conflicting verdicts and score-threshold contradictions."""
    errors: list[str] = []
    if not isinstance(minimum_evaluators, int) or isinstance(minimum_evaluators, bool) or minimum_evaluators < 2:
        errors.append("disagreement_minimum_evaluators_invalid")
        minimum = 2
    else:
        minimum = minimum_evaluators
    seen: set[str] = set()
    verdicts: set[str] = set()
    for i, result in enumerate(results):
        evaluator_id, verdict = result.get("evaluator_id"), result.get("verdict")
        score, threshold, direction = result.get("score"), result.get("threshold"), result.get("direction")
        if not _text(evaluator_id) or evaluator_id in seen:
            errors.append(f"disagreement_evaluator_invalid_or_duplicate:{i}")
        else:
            seen.add(evaluator_id)
        if verdict not in ("PASS", "FAIL", "HOLD"):
            errors.append(f"disagreement_verdict_invalid:{i}")
        else:
            verdicts.add(verdict)
        if not _finite(score) or not _finite(threshold):
            errors.append(f"disagreement_score_or_threshold_invalid:{i}")
        elif direction == "higher_is_better" and ((score >= threshold) != (verdict == "PASS")):
            errors.append(f"disagreement_score_verdict_conflict:{i}")
        elif direction == "lower_is_better" and ((score <= threshold) != (verdict == "PASS")):
            errors.append(f"disagreement_score_verdict_conflict:{i}")
        elif direction not in ("higher_is_better", "lower_is_better"):
            errors.append(f"disagreement_direction_invalid:{i}")
    if len(seen) < minimum:
        errors.append("disagreement_evaluator_count_below_minimum")
    if len(verdicts) > 1:
        errors.append("evaluator_verdicts_conflict")
    return {"stage": 489, "pass": not errors, "errors": errors,
            "evaluator_count": len(seen), "verdicts": sorted(verdicts)}


def evaluate_stages_486_490(*, reproduction_runs: Sequence[Mapping[str, Any]],
                            reproduction_fields: Sequence[str],
                            maximum_score_spread: float, minimum_runs: int,
                            environment_fields: Sequence[str],
                            evaluator_results: Sequence[Mapping[str, Any]],
                            minimum_evaluators: int,
                            splits: Mapping[str, Sequence[str]], required_splits: Sequence[str],
                            lineage_records: Sequence[Mapping[str, Any]],
                            required_lineage_fields: Sequence[str],
                            calibration: Mapping[str, Any], minimum_calibration_samples: int,
                            maximum_calibration_error: float,
                            external_reference: Mapping[str, Any],
                            expected_protocol_id: str, expected_metric_id: str,
                            unresolved_holds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """490: integrated reproducibility/evaluation gate; unresolved HOLD always blocks."""
    checks = [
        check_reproduction_alignment(reproduction_runs, required_fields=reproduction_fields),
        check_repeated_run_variance(reproduction_runs, score_field="score",
                                    maximum_spread=maximum_score_spread,
                                    minimum_runs=minimum_runs),
        check_environment_stability(reproduction_runs, required_fields=environment_fields),
        check_evaluator_disagreement(evaluator_results, minimum_evaluators=minimum_evaluators),
        check_split_disjointness(splits, required_splits=required_splits),
        check_dataset_lineage(lineage_records, required_fields=required_lineage_fields),
        check_calibration_evidence(calibration, minimum_samples=minimum_calibration_samples,
                                   maximum_error=maximum_calibration_error),
        check_external_reference(external_reference, expected_protocol_id=expected_protocol_id,
                                 expected_metric_id=expected_metric_id),
    ]
    hold_errors: list[str] = []
    for i, hold in enumerate(unresolved_holds):
        if not _text(hold.get("hold_id")) or not _text(hold.get("reason")):
            hold_errors.append(f"hold_declaration_invalid:{i}")
    if unresolved_holds:
        hold_errors.append("unresolved_holds_present")
    checks.append({"stage": 490, "pass": not hold_errors, "errors": hold_errors,
                   "unresolved_hold_count": len(unresolved_holds)})
    passed = all(check["pass"] for check in checks)
    record = {"checks": checks, "pass": passed, "proposal_only": True}
    return {"stage": 490, "status": "READY_FOR_REVIEW" if passed else "HOLD",
            "checks": checks, "seal": _seal(record),
            "reproducibility_verified": False, "environment_authenticity_verified": False,
            "evaluator_independence_verified": False, "improvement_verified": False,
            "hold_release_authorized": False, "execution_authorized": False,
            "promotion_authorized": False, "merge_authorized": False,
            "deployment_authorized": False, "proposal_only": True}
