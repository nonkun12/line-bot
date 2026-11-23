"""Post-recovery observability and learning declarations (Stages 691-700).

Caller-supplied metadata only: no telemetry collection, alert evaluation,
incident detection, remediation, or production changes are performed.
"""
from __future__ import annotations
from datetime import datetime

REQUIRED=("readiness_gate_ref","service_ref","observation_window","telemetry_sources",
          "coverage","alert_rules","baseline","anomaly_review","incident_recurrence",
          "postmortem","action_items","validation_plan","independent_review",
          "audit_ref","created_at","auto_remediate")

def _text(v):
    return isinstance(v,str) and bool(v.strip())

def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def _ref_fields(item, fields, prefix, issues):
    for key in fields:
        if not _text(item.get(key)): issues.append(f"{prefix}_{key}_invalid")

def validate_post_recovery_observability(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("readiness_gate_ref","service_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    if _time(record.get("created_at")) is None: issues.append("created_at_invalid")
    if record.get("auto_remediate") is not False:
        issues.append("automatic_remediation_must_be_false")

    window=record.get("observation_window")
    if not isinstance(window,dict):
        issues.append("observation_window_invalid")
    else:
        _ref_fields(window,("window_ref","start_at","end_at","timezone_ref"),"window",issues)
        start,end=_time(window.get("start_at")),_time(window.get("end_at"))
        if start is None or end is None: issues.append("observation_window_time_invalid")
        elif end<=start: issues.append("observation_window_order_invalid")
        if end is not None and _time(record.get("created_at")) is not None and end>_time(record["created_at"]):
            issues.append("observation_window_after_record_creation")

    for field in ("telemetry_sources","coverage","alert_rules"):
        items=record.get(field)
        if not isinstance(items,list) or not items:
            issues.append(f"{field}_invalid"); continue
        refs=[]
        for item in items:
            if not isinstance(item,dict):
                issues.append(f"{field}_item_invalid"); continue
            ref_key={"telemetry_sources":"source_ref","coverage":"coverage_ref","alert_rules":"rule_ref"}[field]
            _ref_fields(item,(ref_key,"evidence_ref","owner_ref"),field,issues)
            if _text(item.get(ref_key)): refs.append(item[ref_key])
            if item.get("status")!="PASS_DECLARED": issues.append(f"{field}_not_pass_declared")
            if item.get("live_collection_performed") is not False:
                issues.append(f"{field}_live_collection_must_not_be_claimed")
        if len(refs)!=len(set(refs)): issues.append(f"{field}_refs_duplicate")

    for field,keys in (
        ("baseline",("baseline_ref","metric_definition_ref","evidence_ref","owner_ref")),
        ("anomaly_review",("review_ref","thresholds_ref","evidence_ref","owner_ref")),
        ("incident_recurrence",("query_ref","result_evidence_ref","owner_ref")),
        ("postmortem",("postmortem_ref","cause_analysis_ref","evidence_ref","owner_ref")),
        ("validation_plan",("plan_ref","success_criteria_ref","owner_ref")),
    ):
        item=record.get(field)
        if not isinstance(item,dict):
            issues.append(f"{field}_invalid"); continue
        _ref_fields(item,keys,field,issues)
        if item.get("status")!="PASS_DECLARED": issues.append(f"{field}_not_pass_declared")
        if item.get("analysis_executed") is not False: issues.append(f"{field}_execution_must_not_be_claimed")

    actions=record.get("action_items")
    if not isinstance(actions,list) or not actions:
        issues.append("action_items_invalid"); actions=[]
    action_refs=[]
    for item in actions:
        if not isinstance(item,dict):
            issues.append("action_item_invalid"); continue
        _ref_fields(item,("action_ref","owner_ref","due_date_ref","acceptance_criteria_ref"),"action",issues)
        if _text(item.get("action_ref")): action_refs.append(item["action_ref"])
        if item.get("status") not in ("OPEN_DECLARED","IN_PROGRESS_DECLARED","CLOSED_DECLARED"):
            issues.append("action_status_invalid")
        if item.get("status")=="CLOSED_DECLARED" and not _text(item.get("closure_evidence_ref")):
            issues.append("closed_action_evidence_missing")
        if item.get("execution_performed") is not False:
            issues.append("action_execution_must_not_be_claimed")
    if len(action_refs)!=len(set(action_refs)): issues.append("action_refs_duplicate")

    review=record.get("independent_review")
    if not isinstance(review,dict):
        issues.append("independent_review_invalid")
    else:
        _ref_fields(review,("reviewer_ref","decision_ref","evidence_ref","reviewed_at"),"review",issues)
        if review.get("decision")!="ACCEPT_DECLARED": issues.append("independent_review_not_accepted")
        if review.get("independent") is not True: issues.append("independent_review_required")
        if review.get("reviewer_authenticated") is not False:
            issues.append("reviewer_authentication_must_not_be_claimed")
        if _time(review.get("reviewed_at")) is None: issues.append("reviewed_at_invalid")

    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "telemetry_collected":False,"alerts_evaluated":False,
            "incident_queries_executed":False,"actions_executed":False}

def stage_700_observability_gate(record):
    result=validate_post_recovery_observability(record)
    return {**result,
            "gate":"READY_FOR_INDEPENDENT_REVIEW" if result["status"]=="DECLARATIONS_COMPLETE" else "BLOCKED",
            "automatic_remediation_authorized":False,"production_changes_authorized":False}
