"""Failure analysis and bounded repair proposal screens (Stages 491-495). No repair is executed."""
from __future__ import annotations
import hashlib, json, math
from typing import Any, Mapping, Sequence

def _seal(v: Any) -> str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _s(v: Any) -> bool: return isinstance(v,str) and bool(v.strip())
def _n(v: Any) -> bool: return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def check_failure_taxonomy(records: Sequence[Mapping[str,Any]], required_categories: Sequence[str]) -> dict:
    errors=[]; allowed=set(required_categories); seen=set()
    if not allowed: errors.append("failure_taxonomy_empty")
    if not records: errors.append("failure_records_empty")
    for i,r in enumerate(records):
        rid,cat=r.get("failure_id"),r.get("category")
        if not _s(rid) or rid in seen: errors.append(f"failure_id_invalid_or_duplicate:{i}")
        else: seen.add(rid)
        if cat not in allowed: errors.append(f"failure_category_unknown:{i}")
        for f in ("symptom","evidence_ref","impact"): 
            if not _s(r.get(f)): errors.append(f"failure_field_missing:{i}:{f}")
    return {"stage":491,"pass":not errors,"errors":errors,"failure_count":len(records)}

def check_root_cause_evidence(analyses: Sequence[Mapping[str,Any]]) -> dict:
    errors=[]; ids=set()
    for i,a in enumerate(analyses):
        fid=a.get("failure_id")
        if not _s(fid) or fid in ids: errors.append(f"root_cause_id_invalid_or_duplicate:{i}")
        else: ids.add(fid)
        for f in ("hypothesis","supporting_evidence","counter_evidence","confidence"):
            if f=="confidence":
                if not _n(a.get(f)) or not 0<=a[f]<=1: errors.append(f"root_cause_confidence_invalid:{i}")
            elif not _s(a.get(f)): errors.append(f"root_cause_field_missing:{i}:{f}")
        if a.get("causal_claim") is True and not _s(a.get("causal_validation_ref")):
            errors.append(f"causal_validation_reference_missing:{i}")
    return {"stage":492,"pass":not errors,"errors":errors,"analysis_count":len(analyses)}

def check_repair_proposal_bounds(proposals: Sequence[Mapping[str,Any]], *, max_scope_files:int, allowed_types:Sequence[str]) -> dict:
    errors=[]; seen=set()
    if not isinstance(max_scope_files,int) or isinstance(max_scope_files,bool) or max_scope_files<1: errors.append("repair_max_scope_invalid"); limit=1
    else: limit=max_scope_files
    for i,p in enumerate(proposals):
        pid=p.get("proposal_id")
        if not _s(pid) or pid in seen: errors.append(f"repair_proposal_id_invalid_or_duplicate:{i}")
        else: seen.add(pid)
        typ=p.get("change_type")
        if typ not in allowed_types: errors.append(f"repair_change_type_disallowed:{i}")
        files=p.get("target_files")
        if not isinstance(files,list) or not files or len(files)>limit or any(not _s(x) for x in files): errors.append(f"repair_scope_invalid:{i}")
        if len(files) != len(set(files)) if isinstance(files,list) else False: errors.append(f"repair_scope_duplicate:{i}")
        for f in ("rationale","rollback_plan","test_plan","review_required"):
            if f=="review_required":
                if p.get(f) is not True: errors.append(f"repair_review_not_required:{i}")
            elif not _s(p.get(f)): errors.append(f"repair_field_missing:{i}:{f}")
    return {"stage":493,"pass":not errors,"errors":errors,"proposal_count":len(proposals),"scope_limit":limit}

def check_repair_validation(proposals: Sequence[Mapping[str,Any]], validation: Mapping[str,Any]) -> dict:
    errors=[]
    if len(proposals)==0: errors.append("repair_validation_no_proposals")
    for f in ("baseline_ref","test_suite_ref","review_ref"):
        if not _s(validation.get(f)): errors.append(f"repair_validation_reference_missing:{f}")
    if validation.get("tests_passed") is not True: errors.append("repair_tests_not_passed")
    if validation.get("regression_check_passed") is not True: errors.append("repair_regression_check_not_passed")
    if validation.get("human_approval") is True: errors.append("human_approval_flag_not_consumed")
    return {"stage":494,"pass":not errors,"errors":errors,"validation_declarations_checked":True}

def evaluate_stages_491_495(*, failures, required_categories, root_causes, proposals, max_scope_files, allowed_types, validation, unresolved_holds):
    checks=[check_failure_taxonomy(failures,required_categories),check_root_cause_evidence(root_causes),check_repair_proposal_bounds(proposals,max_scope_files=max_scope_files,allowed_types=allowed_types),check_repair_validation(proposals,validation)]
    hold_errors=[]
    if unresolved_holds: hold_errors.append("unresolved_holds_present")
    checks.append({"stage":495,"pass":not hold_errors,"errors":hold_errors,"hold_count":len(unresolved_holds)})
    passed=all(c["pass"] for c in checks); record={"checks":checks,"pass":passed}
    return {"stage":495,"status":"READY_FOR_REVIEW" if passed else "HOLD","checks":checks,"seal":_seal(record),"repairs_executed":False,"causality_verified":False,"approval_granted":False,"hold_release_authorized":False,"merge_authorized":False,"deployment_authorized":False,"proposal_only":True}
