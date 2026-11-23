"""Incident response evidence declarations (AI Factory Stages 661-670).

Caller-supplied metadata validation only. No incident detection, authorization,
containment, remediation, rollback, or verification is executed here.
"""
from __future__ import annotations
from datetime import datetime

REQUIRED = (
    "incident_ref", "subject_ref", "trigger_event_refs", "classification",
    "timeline", "decision_record", "response_plan", "approvals",
    "execution_records", "rollback_plan", "verification_plan",
    "closure_record", "audit_ref", "automatic_execution", "created_at",
)
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"}
STATUSES = {"OPEN", "TRIAGED", "CONTAINMENT_PROPOSED", "REMEDIATION_PROPOSED",
            "VERIFYING_DECLARED", "CLOSED_DECLARED"}
ACTION_TYPES = {"NOTIFY", "RESTRICT_ACCESS", "ROTATE_CREDENTIAL", "REVOKE_KEY",
                "ISOLATE_RESOURCE", "RESTORE_VERSION", "PATCH", "OTHER"}
APPROVAL_STATES = {"PENDING", "APPROVED_DECLARED", "REJECTED_DECLARED"}
EXEC_STATES = {"NOT_STARTED", "PROPOSED", "EXECUTED_DECLARED", "FAILED_DECLARED", "UNKNOWN"}
def _text(v):
    return isinstance(v, str) and bool(v.strip())
def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None
def _texts(v, allow_empty=False):
    return isinstance(v,list) and (allow_empty or bool(v)) and all(_text(x) for x in v) and len(v)==len(set(v))

def validate_incident_response(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("incident_ref","subject_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    if not _texts(record.get("trigger_event_refs")): issues.append("trigger_event_refs_invalid")
    created=_time(record.get("created_at"))
    if created is None: issues.append("created_at_invalid")

    classification=record.get("classification")
    if not isinstance(classification,dict):
        issues.append("classification_invalid")
    else:
        if classification.get("severity") not in SEVERITIES: issues.append("severity_invalid")
        if classification.get("status") not in STATUSES: issues.append("incident_status_invalid")
        if not _text(classification.get("rationale_ref")): issues.append("classification_rationale_invalid")
        if classification.get("scope_confirmed") is not True: issues.append("incident_scope_not_confirmed")

    timeline=record.get("timeline")
    timeline_ids=[]
    if not isinstance(timeline,list) or not timeline:
        issues.append("timeline_invalid"); timeline=[]
    last=None
    for item in timeline:
        if not isinstance(item,dict):
            issues.append("timeline_item_invalid"); continue
        for k in ("entry_ref","event_ref","occurred_at","recorded_at","description_ref"):
            if not _text(item.get(k)): issues.append(f"timeline_{k}_invalid")
        if _text(item.get("entry_ref")): timeline_ids.append(item["entry_ref"])
        occurred,recorded=_time(item.get("occurred_at")),_time(item.get("recorded_at"))
        if occurred is None: issues.append("timeline_occurred_at_invalid")
        if recorded is None: issues.append("timeline_recorded_at_invalid")
        if occurred is not None and recorded is not None and recorded<occurred:
            issues.append("timeline_recorded_before_occurrence")
        if occurred is not None and last is not None and occurred<last:
            issues.append("timeline_order_invalid")
        if occurred is not None: last=occurred
    if len(timeline_ids)!=len(set(timeline_ids)): issues.append("timeline_entry_refs_duplicate")

    decision=record.get("decision_record")
    if not isinstance(decision,dict):
        issues.append("decision_record_invalid")
    else:
        if decision.get("decision") not in ("NO_ACTION_DECLARED","CONTAINMENT_RECOMMENDED","REMEDIATION_RECOMMENDED","ESCALATE"):
            issues.append("response_decision_invalid")
        for k in ("decision_ref","decision_owner_ref","rationale_ref"):
            if not _text(decision.get(k)): issues.append(f"decision_{k}_invalid")
        if decision.get("authority_verified") is not False:
            issues.append("authority_verification_must_not_be_claimed")
        if decision.get("human_approval_required") is not True:
            issues.append("human_approval_requirement_missing")

    plan=record.get("response_plan")
    plan_ids=[]
    if not isinstance(plan,list) or not plan:
        issues.append("response_plan_invalid"); plan=[]
    for action in plan:
        if not isinstance(action,dict):
            issues.append("response_action_invalid"); continue
        for k in ("action_ref","owner_ref","target_ref","rationale_ref"):
            if not _text(action.get(k)): issues.append(f"action_{k}_invalid")
        if _text(action.get("action_ref")): plan_ids.append(action["action_ref"])
        if action.get("action_type") not in ACTION_TYPES: issues.append("action_type_invalid")
        if action.get("execution_state") not in EXEC_STATES: issues.append("action_execution_state_invalid")
        if action.get("execution_state")=="EXECUTED_DECLARED":
            if not _text(action.get("execution_evidence_ref")):
                issues.append("action_execution_evidence_missing")
            if action.get("executed_by_system") is not False:
                issues.append("automated_execution_must_not_be_claimed")
        if action.get("authorized") is not False:
            issues.append("authorization_must_not_be_claimed")
    if len(plan_ids)!=len(set(plan_ids)): issues.append("action_refs_duplicate")

    approvals=record.get("approvals")
    if not isinstance(approvals,list) or not approvals:
        issues.append("approvals_invalid"); approvals=[]
    approver_refs=[]
    for approval in approvals:
        if not isinstance(approval,dict):
            issues.append("approval_record_invalid"); continue
        for k in ("approval_ref","approver_ref","action_ref","decided_at"):
            if not _text(approval.get(k)): issues.append(f"approval_{k}_invalid")
        if _text(approval.get("approver_ref")): approver_refs.append(approval["approver_ref"])
        if approval.get("state") not in APPROVAL_STATES: issues.append("approval_state_invalid")
        if approval.get("approver_ref") and approval.get("action_owner_ref")==approval.get("approver_ref"):
            issues.append("approver_must_differ_from_action_owner")
        if _time(approval.get("decided_at")) is None: issues.append("approval_decided_at_invalid")
        if approval.get("authority_verified") is not False:
            issues.append("approval_authority_verification_must_not_be_claimed")
    if len(approver_refs)!=len(set(approver_refs)): issues.append("approver_refs_duplicate")

    executions=record.get("execution_records")
    if not isinstance(executions,list): issues.append("execution_records_invalid"); executions=[]
    seen_exec=[]
    for item in executions:
        if not isinstance(item,dict):
            issues.append("execution_record_invalid"); continue
        for k in ("execution_ref","action_ref","state","evidence_ref"):
            if not _text(item.get(k)): issues.append(f"execution_{k}_invalid")
        if _text(item.get("execution_ref")): seen_exec.append(item["execution_ref"])
        if item.get("state") not in EXEC_STATES: issues.append("execution_state_invalid")
        if item.get("state")=="EXECUTED_DECLARED" and item.get("executor_authenticated") is not False:
            issues.append("executor_authentication_must_not_be_claimed")
    if len(seen_exec)!=len(set(seen_exec)): issues.append("execution_refs_duplicate")

    rollback=record.get("rollback_plan")
    if not isinstance(rollback,dict):
        issues.append("rollback_plan_invalid")
    else:
        if rollback.get("required") is not True: issues.append("rollback_requirement_missing")
        for k in ("trigger_conditions_ref","procedure_ref","recovery_point_ref","owner_ref"):
            if not _text(rollback.get(k)): issues.append(f"rollback_{k}_invalid")
        if rollback.get("executed") is not False: issues.append("rollback_execution_must_be_false")

    verify=record.get("verification_plan")
    if not isinstance(verify,dict):
        issues.append("verification_plan_invalid")
    else:
        for k in ("test_plan_ref","expected_result_ref","independent_verifier_ref"):
            if not _text(verify.get(k)): issues.append(f"verification_{k}_invalid")
        if verify.get("independent") is not True: issues.append("independent_verification_required")
        if verify.get("verification_executed") is not False:
            issues.append("verification_execution_must_not_be_claimed")

    closure=record.get("closure_record")
    if not isinstance(closure,dict):
        issues.append("closure_record_invalid")
    else:
        if closure.get("status") not in ("OPEN","CLOSED_DECLARED","REOPENED_DECLARED"):
            issues.append("closure_status_invalid")
        if closure.get("status")=="CLOSED_DECLARED":
            for k in ("closure_evidence_ref","verifier_ref","lessons_ref"):
                if not _text(closure.get(k)): issues.append(f"closure_{k}_missing")
            if closure.get("independent_verification_passed") is not True:
                issues.append("closure_independent_verification_not_declared")
            if any(isinstance(a,dict) and a.get("execution_state") in ("FAILED_DECLARED","UNKNOWN") for a in plan):
                issues.append("closure_with_failed_or_unknown_action")

    if record.get("automatic_execution") is not False:
        issues.append("automatic_execution_must_be_false")
    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "incident_detected_by_system":False,"actions_executed":False,
            "approvals_authenticated":False,"rollback_executed":False,
            "verification_performed":False}

def stage_670_incident_response_gate(record):
    result=validate_incident_response(record)
    ready=result["status"]=="DECLARATIONS_COMPLETE"
    return {**result,"gate":"READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
            "containment_executed":False,"remediation_executed":False,
            "incident_closed_by_system":False,"automatic_execution":False}
