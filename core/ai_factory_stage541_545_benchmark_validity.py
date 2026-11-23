"""Declarative benchmark-validity checks for AI Factory stages 541-545.
No benchmark is executed; submitted declarations remain untrusted.
"""
from __future__ import annotations

REQUIRED = {
    541: ("dataset_id", "dataset_version", "provenance_refs", "permission_declaration"),
    542: ("coverage_matrix", "target_capabilities", "coverage_refs"),
    543: ("baseline_id", "baseline_version", "baseline_protocol", "parity_declaration"),
    544: ("contamination_checks", "leakage_checks", "holdout_separation_refs"),
}

def _missing(record, keys):
    return [k for k in keys if k not in record or record[k] in (None, "", [], {})]

def _unique_refs(record, field):
    refs=record.get(field)
    return isinstance(refs,list) and bool(refs) and all(isinstance(x,str) and x for x in refs) and len(refs)==len(set(refs))

def validate_benchmark_validity(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[]
    issues=[]
    for stage,keys in REQUIRED.items():
        missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
    for field in ("provenance_refs","coverage_refs","holdout_separation_refs"):
        if not _unique_refs(record,field):
            issues.append(f"{field}_invalid_or_duplicate")
    for field in ("coverage_matrix","contamination_checks","leakage_checks"):
        if not isinstance(record.get(field),dict) or not record[field]:
            issues.append(f"{field}_invalid")
    if record.get("parity_declaration") not in ("matched","documented_deviation"):
        issues.append("baseline_parity_not_declared")
    if record.get("contamination_checks") and any(v!="clear" for v in record["contamination_checks"].values()):
        issues.append("contamination_not_clear")
    if record.get("leakage_checks") and any(v!="clear" for v in record["leakage_checks"].values()):
        issues.append("leakage_not_clear")
    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":issues}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"benchmark_executed":False,"validity_established":False}

def stage_545_benchmark_gate(record):
    result=validate_benchmark_validity(record)
    return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_approval":False}
