"""Governance feedback-loop declarations (AI Factory Stages 701-710).

This module validates caller-supplied governance and improvement metadata only.
It does not change policies, permissions, deployments, models, or production state.
"""
from __future__ import annotations
from datetime import datetime

REQUIRED=("observability_gate_ref","scope_ref","policy_snapshot_ref","change_proposal",
          "impact_assessment","risk_assessment","approval_record","rollout_constraints",
          "verification_plan","rollback_plan","decision_log","audit_ref","created_at",
          "policy_mutation_executed")

def _text(v):
    return isinstance(v,str) and bool(v.strip())

def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def _refs(obj, keys, prefix, issues):
    for k in keys:
        if not _text(obj.get(k)): issues.append(f"{prefix}_{k}_invalid")

def validate_governance_feedback(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("observability_gate_ref","scope_ref","policy_snapshot_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    if _time(record.get("created_at")) is None: issues.append("created_at_invalid")
    if record.get("policy_mutation_executed") is not False:
        issues.append("policy_mutation_must_not_be_claimed")

    proposal=record.get("change_proposal")
    if not isinstance(proposal,dict):
        issues.append("change_proposal_invalid")
    else:
        _refs(proposal,("proposal_ref","rationale_ref","target_policy_ref","diff_ref","owner_ref"),"proposal",issues)
        if proposal.get("status") not in ("PROPOSED","DEFERRED","REJECTED"):
            issues.append("proposal_status_invalid")
        if proposal.get("applied") is not False: issues.append("proposal_application_must_not_be_claimed")

    impact=record.get("impact_assessment")
    if not isinstance(impact,dict):
        issues.append("impact_assessment_invalid")
    else:
        _refs(impact,("assessment_ref","affected_scope_ref","evidence_ref","owner_ref"),"impact",issues)
        if impact.get("status")!="PASS_DECLARED": issues.append("impact_assessment_not_pass_declared")
        if impact.get("assessment_executed") is not False: issues.append("impact_execution_must_not_be_claimed")

    risk=record.get("risk_assessment")
    if not isinstance(risk,dict):
        issues.append("risk_assessment_invalid")
    else:
        _refs(risk,("assessment_ref","threat_model_ref","evidence_ref","owner_ref"),"risk",issues)
        if risk.get("status")!="PASS_DECLARED": issues.append("risk_assessment_not_pass_declared")
        if risk.get("unmitigated_critical") is not False: issues.append("unmitigated_critical_risk")
        if risk.get("assessment_executed") is not False: issues.append("risk_assessment_execution_must_not_be_claimed")

    approval=record.get("approval_record")
    if not isinstance(approval,dict):
        issues.append("approval_record_invalid")
    else:
        _refs(approval,("approval_ref","approver_ref","decision_evidence_ref","decided_at"),"approval",issues)
        if approval.get("decision") not in ("APPROVE_DECLARED","REJECT_DECLARED","PENDING"):
            issues.append("approval_decision_invalid")
        elif approval.get("decision")!="APPROVE_DECLARED": issues.append("approval_not_approved")
        if approval.get("approver_authenticated") is not False:
            issues.append("approver_authentication_must_not_be_claimed")
        if approval.get("authorization_granted") is not False:
            issues.append("authorization_grant_must_not_be_claimed")
        if _time(approval.get("decided_at")) is None: issues.append("approval_decided_at_invalid")

    for field in ("rollout_constraints","verification_plan","rollback_plan"):
        obj=record.get(field)
        if not isinstance(obj,dict):
            issues.append(f"{field}_invalid"); continue
        _refs(obj,("plan_ref","evidence_ref","owner_ref"),field,issues)
        if obj.get("status")!="PASS_DECLARED": issues.append(f"{field}_not_pass_declared")
        if obj.get("executed") is not False: issues.append(f"{field}_execution_must_not_be_claimed")
    constraints=record.get("rollout_constraints")
    if isinstance(constraints,dict) and constraints.get("max_scope_ref") is None:
        issues.append("rollout_max_scope_ref_missing")

    decisions=record.get("decision_log")
    if not isinstance(decisions,list) or not decisions:
        issues.append("decision_log_invalid"); decisions=[]
    refs=[]
    for item in decisions:
        if not isinstance(item,dict):
            issues.append("decision_entry_invalid"); continue
        _refs(item,("decision_ref","basis_ref","owner_ref","recorded_at"),"decision",issues)
        if _text(item.get("decision_ref")): refs.append(item["decision_ref"])
        if item.get("outcome") not in ("ACCEPTED","DEFERRED","REJECTED"):
            issues.append("decision_outcome_invalid")
        if _time(item.get("recorded_at")) is None: issues.append("decision_recorded_at_invalid")
    if len(refs)!=len(set(refs)): issues.append("decision_refs_duplicate")

    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "policy_changed":False,"approval_authenticated":False,
            "authorization_granted":False,"plans_executed":False}

def stage_710_governance_gate(record):
    result=validate_governance_feedback(record)
    return {**result,
            "gate":"READY_FOR_INDEPENDENT_REVIEW" if result["status"]=="DECLARATIONS_COMPLETE" else "BLOCKED",
            "policy_mutation_authorized":False,"production_change_authorized":False}
