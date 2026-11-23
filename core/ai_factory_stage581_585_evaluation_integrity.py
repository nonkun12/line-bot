"""Evaluation provenance and result-integrity declarations (Stages 581-585)."""
from __future__ import annotations

from datetime import datetime
import math

REF_FIELDS = (
    "evaluator_ref", "evaluation_run_ref", "subject_ref",
    "rubric_ref", "result_ref",
)
REQUIRED = REF_FIELDS + (
    "evaluated_at", "metric_results", "limitations",
    "evaluator_independent", "conflict_declaration",
    "production_change", "model_change",
)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    if not _text(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_evaluation_integrity(record):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"],
                "issues": ["invalid_record"]}

    missing = [key for key in REQUIRED if key not in record or record[key] is None]
    issues = []
    for field in REF_FIELDS:
        if not _text(record.get(field)):
            issues.append(f"{field}_invalid")
    if not _timestamp(record.get("evaluated_at")):
        issues.append("evaluated_at_invalid")
    metrics = record.get("metric_results")
    if not isinstance(metrics, list) or not metrics:
        issues.append("metric_results_invalid")
    else:
        seen = set()
        for index, metric in enumerate(metrics):
            if not isinstance(metric, dict):
                issues.append(f"metric_results_{index}_invalid")
                continue
            name, value, unit = metric.get("metric"), metric.get("value"), metric.get("unit")
            if not _text(name) or name in seen:
                issues.append(f"metric_results_{index}_identity_invalid")
            if _text(name):
                seen.add(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                issues.append(f"metric_results_{index}_value_invalid")
            if not _text(unit):
                issues.append(f"metric_results_{index}_unit_invalid")
    limitations = record.get("limitations")
    if not isinstance(limitations, list) or not limitations or any(not _text(x) for x in limitations):
        issues.append("limitations_invalid")
    conflicts = record.get("conflict_declaration")
    if not isinstance(conflicts, list) or any(not _text(x) for x in conflicts):
        issues.append("conflict_declaration_invalid")
    if record.get("evaluator_independent") is not True:
        issues.append("evaluator_independence_not_established")
    if record.get("production_change") is not False:
        issues.append("production_change_must_be_false")
    if record.get("model_change") is not False:
        issues.append("model_change_must_be_false")

    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {
        "status": "EVIDENCE_COMPLETE", "missing": [], "issues": [],
        "result_integrity_verified": False, "independent_reproduction_done": False,
    }


def stage_585_evaluation_integrity_gate(record):
    result = validate_evaluation_integrity(record)
    return {
        **result,
        "gate": "BLOCKED" if result["status"] == "BLOCKED" else "REVIEW_REQUIRED",
        "automatic_acceptance": False,
    }
