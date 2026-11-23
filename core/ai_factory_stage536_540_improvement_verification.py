"""Declarative improvement-verification checks for AI Factory stages 536-540."""
from __future__ import annotations

REQUIRED = {
    536: ("before_refs", "after_refs", "pairing_method"),
    537: ("attribution_method", "confounders", "attribution_refs"),
    538: ("guardrails", "regression_results", "regression_refs"),
    539: ("reproduction_steps", "environment_fingerprint", "independent_evaluator_refs"),
}

def _missing(record, keys):
    return [k for k in keys if k not in record or record[k] in (None, "", [], {})]

def validate_improvement_verification(record):
    if not isinstance(record, dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[]
    issues=[]
    for stage, keys in REQUIRED.items():
        missing.extend(f"{stage}:{k}" for k in _missing(record, keys))
    for field in ("before_refs","after_refs","regression_refs","independent_evaluator_refs"):
        refs=record.get(field, [])
        if not isinstance(refs,list) or not refs or len(refs)!=len(set(refs)):
            issues.append(f"{field}_invalid_or_duplicate")
    if record.get("before_refs") and record.get("after_refs") and set(record["before_refs"]) & set(record["after_refs"]):
        issues.append("before_after_refs_overlap")
    if not isinstance(record.get("guardrails"),dict) or not record.get("guardrails"):
        issues.append("guardrails_invalid")
    if not isinstance(record.get("regression_results"),dict) or not record.get("regression_results"):
        issues.append("regression_results_invalid")
    if record.get("regression_results") and any(v not in ("pass","fail","unknown") for v in record["regression_results"].values()):
        issues.append("regression_result_value_invalid")
    if any(v!="pass" for v in record.get("regression_results",{}).values()):
        issues.append("regression_not_clear")
    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":issues}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "improvement_verified":False,"independent_validation_completed":False}

def stage_540_review_gate(record):
    result=validate_improvement_verification(record)
    return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED",
            "automatic_acceptance":False}
