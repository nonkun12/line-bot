"""Post-recovery service readiness declarations (Stages 681-690).

Validates metadata only. It never probes, enables, deploys, routes traffic, or
authorizes production return-to-service.
"""
from __future__ import annotations
from datetime import datetime

REQUIRED=("recovery_gate_ref","service_ref","policy_ref","activation_plan_ref",
          "rollout_plan_ref","canary_evidence_ref","slo_evidence_ref",
          "capacity_evidence_ref","security_evidence_ref","backup_evidence_ref",
          "alerting_evidence_ref","handoff_ref","audit_ref","created_at",
          "activation_executed")
PASS="PASS_DECLARED"

def _text(v):
    return isinstance(v,str) and bool(v.strip())

def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def validate_return_readiness(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in REQUIRED:
        if k.endswith("_ref") and not _text(record.get(k)): issues.append(f"{k}_invalid")
    if _time(record.get("created_at")) is None: issues.append("created_at_invalid")
    if record.get("activation_executed") is not False:
        issues.append("activation_execution_must_not_be_claimed")
    if record.get("traffic_shift_executed") is not False:
        issues.append("traffic_shift_execution_must_not_be_claimed")
    checks=record.get("readiness_checks")
    if not isinstance(checks,list) or not checks:
        issues.append("readiness_checks_invalid"); checks=[]
    refs=[]
    for item in checks:
        if not isinstance(item,dict):
            issues.append("readiness_check_invalid"); continue
        for k in ("check_ref","scope_ref","evidence_ref","owner_ref"):
            if not _text(item.get(k)): issues.append(f"readiness_{k}_invalid")
        if _text(item.get("check_ref")): refs.append(item["check_ref"])
        if item.get("status") != PASS: issues.append("readiness_check_not_pass_declared")
        if item.get("live_probe_executed") is not False:
            issues.append("live_probe_execution_must_not_be_claimed")
    if len(refs)!=len(set(refs)): issues.append("readiness_check_refs_duplicate")
    for field in ("rollout","canary","slo","capacity","security","backup","alerting","handoff"):
        value=record.get(field)
        if not isinstance(value,dict):
            issues.append(f"{field}_record_invalid"); continue
        for k in ("plan_ref","evidence_ref","owner_ref"):
            if not _text(value.get(k)): issues.append(f"{field}_{k}_invalid")
        if value.get("status") != PASS: issues.append(f"{field}_not_pass_declared")
    if record.get("rollback_executed") is not False:
        issues.append("rollback_execution_must_not_be_claimed")
    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "live_probes_performed":False,"traffic_shift_performed":False,
            "service_activation_performed":False}

def stage_690_return_readiness_gate(record):
    result=validate_return_readiness(record)
    return {**result,
            "gate":"READY_FOR_INDEPENDENT_REVIEW" if result["status"]=="DECLARATIONS_COMPLETE" else "BLOCKED",
            "return_to_service_authorized":False,"activation_executed":False,
            "traffic_shift_executed":False}
