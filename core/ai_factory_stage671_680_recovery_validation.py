"""Recovery validation declarations (AI Factory Stages 671-680).

This module checks caller-supplied recovery evidence metadata only. It does not
restore data/services, measure live RTO/RPO, verify artifact bytes, or authorize
return to service.
"""
from __future__ import annotations
import math
import re
from datetime import datetime

REQUIRED = (
    "recovery_ref", "incident_ref", "subject_ref", "recovery_policy_ref",
    "recovery_point", "objectives", "dependencies", "integrity_checks",
    "reconciliation", "service_checks", "regression_checks",
    "fallback_plan", "independent_signoff", "residual_risks",
    "audit_ref", "automatic_restore", "created_at",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CHECK_STATES = {"PASS_DECLARED", "FAIL_DECLARED", "UNKNOWN"}
def _text(v):
    return isinstance(v,str) and bool(v.strip())
def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None
def _texts(v, allow_empty=False):
    return isinstance(v,list) and (allow_empty or bool(v)) and all(_text(x) for x in v) and len(v)==len(set(v))
def _finite_nonnegative(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>=0

def validate_recovery_record(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("recovery_ref","incident_ref","subject_ref","recovery_policy_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    created=_time(record.get("created_at"))
    if created is None: issues.append("created_at_invalid")

    point=record.get("recovery_point")
    if not isinstance(point,dict):
        issues.append("recovery_point_invalid")
    else:
        for k in ("snapshot_ref","source_ref","captured_at","restore_manifest_ref"):
            if not _text(point.get(k)): issues.append(f"recovery_point_{k}_invalid")
        captured=_time(point.get("captured_at"))
        if captured is None: issues.append("recovery_point_captured_at_invalid")
        if created is not None and captured is not None and captured>created:
            issues.append("recovery_point_after_record_creation")
        digest=point.get("manifest_digest")
        if not _text(digest) or not HEX64.fullmatch(digest):
            issues.append("recovery_manifest_digest_invalid")
        if point.get("restore_test_executed") is not False:
            issues.append("restore_execution_must_not_be_claimed")

    objectives=record.get("objectives")
    if not isinstance(objectives,dict):
        issues.append("objectives_invalid")
    else:
        for k in ("rto_target_seconds","rpo_target_seconds","measured_rto_seconds","measured_rpo_seconds"):
            if not _finite_nonnegative(objectives.get(k)): issues.append(f"{k}_invalid")
        if objectives.get("measurement_source_ref") is not None and not _text(objectives.get("measurement_source_ref")):
            issues.append("measurement_source_ref_invalid")
        if objectives.get("measured_rto_seconds") is not None and objectives.get("rto_target_seconds") is not None:
            if _finite_nonnegative(objectives.get("measured_rto_seconds")) and _finite_nonnegative(objectives.get("rto_target_seconds")) and objectives["measured_rto_seconds"]>objectives["rto_target_seconds"]:
                issues.append("rto_target_exceeded_declared")
        if objectives.get("measured_rpo_seconds") is not None and objectives.get("rpo_target_seconds") is not None:
            if _finite_nonnegative(objectives.get("measured_rpo_seconds")) and _finite_nonnegative(objectives.get("rpo_target_seconds")) and objectives["measured_rpo_seconds"]>objectives["rpo_target_seconds"]:
                issues.append("rpo_target_exceeded_declared")
        if objectives.get("measurements_verified") is not False:
            issues.append("objective_measurement_verification_must_not_be_claimed")

    dependencies=record.get("dependencies")
    if not isinstance(dependencies,list) or not dependencies:
        issues.append("dependencies_invalid"); dependencies=[]
    dep_ids=[]
    for dep in dependencies:
        if not isinstance(dep,dict):
            issues.append("dependency_record_invalid"); continue
        for k in ("dependency_ref","owner_ref","readiness_evidence_ref"):
            if not _text(dep.get(k)): issues.append(f"dependency_{k}_invalid")
        if _text(dep.get("dependency_ref")): dep_ids.append(dep["dependency_ref"])
        if dep.get("status") not in CHECK_STATES: issues.append("dependency_status_invalid")
        elif dep.get("status") != "PASS_DECLARED": issues.append("dependency_not_pass_declared")
    if len(dep_ids)!=len(set(dep_ids)): issues.append("dependency_refs_duplicate")

    checks=record.get("integrity_checks")
    if not isinstance(checks,list) or not checks:
        issues.append("integrity_checks_invalid"); checks=[]
    check_ids=[]
    for item in checks:
        if not isinstance(item,dict):
            issues.append("integrity_check_invalid"); continue
        for k in ("check_ref","artifact_ref","expected_digest_ref","result_evidence_ref"):
            if not _text(item.get(k)): issues.append(f"integrity_{k}_invalid")
        if _text(item.get("check_ref")): check_ids.append(item["check_ref"])
        if item.get("status") not in CHECK_STATES: issues.append("integrity_status_invalid")
        elif item.get("status") != "PASS_DECLARED": issues.append("integrity_check_not_pass_declared")
        if item.get("bytes_verified") is not False: issues.append("artifact_byte_verification_must_not_be_claimed")
    if len(check_ids)!=len(set(check_ids)): issues.append("integrity_check_refs_duplicate")

    reconciliation=record.get("reconciliation")
    if not isinstance(reconciliation,dict):
        issues.append("reconciliation_invalid")
    else:
        for k in ("procedure_ref","result_evidence_ref","owner_ref"):
            if not _text(reconciliation.get(k)): issues.append(f"reconciliation_{k}_invalid")
        if reconciliation.get("status") not in CHECK_STATES: issues.append("reconciliation_status_invalid")
        elif reconciliation.get("status") != "PASS_DECLARED": issues.append("reconciliation_not_pass_declared")
        if reconciliation.get("data_mutated_by_validator") is not False:
            issues.append("validator_data_mutation_must_be_false")

    for field in ("service_checks","regression_checks"):
        items=record.get(field)
        if not isinstance(items,list) or not items:
            issues.append(f"{field}_invalid"); continue
        refs=[]
        for item in items:
            if not isinstance(item,dict):
                issues.append(f"{field}_item_invalid"); continue
            for k in ("check_ref","procedure_ref","result_evidence_ref"):
                if not _text(item.get(k)): issues.append(f"{field}_{k}_invalid")
            if _text(item.get("check_ref")): refs.append(item["check_ref"])
            if item.get("status") not in CHECK_STATES: issues.append(f"{field}_status_invalid")
            elif item.get("status") != "PASS_DECLARED": issues.append(f"{field}_not_pass_declared")
        if len(refs)!=len(set(refs)): issues.append(f"{field}_refs_duplicate")

    fallback=record.get("fallback_plan")
    if not isinstance(fallback,dict):
        issues.append("fallback_plan_invalid")
    else:
        for k in ("trigger_conditions_ref","procedure_ref","owner_ref","recovery_point_ref"):
            if not _text(fallback.get(k)): issues.append(f"fallback_{k}_invalid")
        if fallback.get("executed") is not False: issues.append("fallback_execution_must_not_be_claimed")

    signoff=record.get("independent_signoff")
    if not isinstance(signoff,dict):
        issues.append("independent_signoff_invalid")
    else:
        for k in ("reviewer_ref","decision_ref","evidence_ref","decided_at"):
            if not _text(signoff.get(k)): issues.append(f"signoff_{k}_invalid")
        if signoff.get("decision") not in ("ACCEPT_DECLARED","REJECT_DECLARED","CONDITIONAL_DECLARED","PENDING"):
            issues.append("signoff_decision_invalid")
        elif signoff.get("decision") != "ACCEPT_DECLARED":
            issues.append("independent_signoff_not_accepted")
        if signoff.get("independent") is not True: issues.append("independent_signoff_required")
        if signoff.get("reviewer_authenticated") is not False:
            issues.append("reviewer_authentication_must_not_be_claimed")
        if _time(signoff.get("decided_at")) is None: issues.append("signoff_decided_at_invalid")

    risks=record.get("residual_risks")
    if not isinstance(risks,list):
        issues.append("residual_risks_invalid"); risks=[]
    risk_refs=[]
    for risk in risks:
        if not isinstance(risk,dict):
            issues.append("residual_risk_invalid"); continue
        for k in ("risk_ref","description_ref","owner_ref","disposition"):
            if not _text(risk.get(k)): issues.append(f"residual_risk_{k}_invalid")
        if _text(risk.get("risk_ref")): risk_refs.append(risk["risk_ref"])
        if risk.get("disposition") not in ("ACCEPTED_DECLARED","MITIGATION_PLANNED","UNRESOLVED"):
            issues.append("residual_risk_disposition_invalid")
        elif risk.get("disposition") == "UNRESOLVED":
            issues.append("residual_risk_unresolved")
    if len(risk_refs)!=len(set(risk_refs)): issues.append("residual_risk_refs_duplicate")

    if record.get("automatic_restore") is not False:
        issues.append("automatic_restore_must_be_false")

    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "restore_executed":False,"artifact_bytes_verified":False,
            "rto_rpo_independently_measured":False,"service_health_probed":False,
            "independent_reviewer_authenticated":False}

def stage_680_recovery_gate(record):
    result=validate_recovery_record(record)
    ready=result["status"]=="DECLARATIONS_COMPLETE"
    return {**result,"gate":"READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
            "return_to_service_authorized":False,"automatic_restore":False,
            "rollback_executed":False}
