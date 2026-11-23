"""Declarative decision-quality checks for AI Factory stages 531-535.
Caller-supplied evidence is untrusted; this module does not run evaluations.
"""
from __future__ import annotations

REQUIRED = {
    531: ("decision_id", "rationale", "alternatives", "evidence_refs"),
    532: ("rubric_id", "criteria", "score_scale", "mapping_refs"),
    533: ("comparison_protocol", "control_conditions", "blindness_declaration", "protocol_refs"),
    534: ("sample_count", "uncertainty_method", "uncertainty_bounds", "sample_refs"),
}
FORBIDDEN = ("unsupported_claims", "causal_claims_without_design")

def _missing(item, keys):
    return [key for key in keys if key not in item or item[key] in (None, "", [], {})]

def validate_decision_quality(record):
    if not isinstance(record, dict):
        return {"status": "BLOCKED", "missing": ["record_not_object"], "issues": ["invalid_record"]}
    missing = []
    issues = []
    for stage, keys in REQUIRED.items():
        missing.extend(f"{stage}:{key}" for key in _missing(record, keys))
    for key in FORBIDDEN:
        if record.get(key):
            issues.append(f"unsupported:{key}")
    refs = record.get("evidence_refs", [])
    if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
        issues.append("evidence_refs_invalid_or_duplicate")
    sample_count = record.get("sample_count")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count < 1:
        issues.append("sample_count_invalid")
    bounds = record.get("uncertainty_bounds")
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        issues.append("uncertainty_bounds_invalid")
    else:
        try:
            if float(bounds[0]) > float(bounds[1]):
                issues.append("uncertainty_bounds_reversed")
        except (TypeError, ValueError):
            issues.append("uncertainty_bounds_not_numeric")
    if missing or issues:
        return {"status": "BLOCKED", "missing": missing, "issues": issues}
    return {"status": "DECLARATIONS_COMPLETE", "missing": [], "issues": [],
            "evaluation_executed": False, "decision_validated": False}

def stage_535_review_gate(record):
    result = validate_decision_quality(record)
    return {**result, "gate": "BLOCKED" if result["status"] == "BLOCKED" else "REVIEW_REQUIRED",
            "automatic_approval": False}
