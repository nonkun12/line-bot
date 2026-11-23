"""Independent recovery evidence and safe restart gates (Stages 781-790).

Validates supplied evidence and recovery drill receipts. It does not contact
external systems, execute failover, restore production, or resume workloads.
"""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone

def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def _parse_time(value):
    if not isinstance(value,str): return None
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError: return None

def validate_evidence_manifest(manifest,allowed_artifact_types=None):
    issues=[]
    if not isinstance(manifest,dict):
        return {"status":"BLOCKED","issues":["manifest_invalid"],"verified_artifacts":[]}
    if manifest.get("schema")!="recovery-evidence-v1": issues.append("manifest_schema_unsupported")
    artifacts=manifest.get("artifacts")
    if not isinstance(artifacts,list) or not artifacts: issues.append("artifacts_missing")
    verified=[]; seen=set()
    allowed=set(allowed_artifact_types or ["backup","restore_drill","audit_checkpoint","health_probe"])
    for i,item in enumerate(artifacts if isinstance(artifacts,list) else []):
        if not isinstance(item,dict):
            issues.append(f"artifact_{i}_invalid"); continue
        ref=item.get("artifact_ref"); kind=item.get("artifact_type"); digest=item.get("sha256")
        if not isinstance(ref,str) or not ref.strip(): issues.append(f"artifact_{i}_ref_invalid")
        elif ref in seen: issues.append(f"artifact_{i}_duplicate_ref")
        else: seen.add(ref)
        if kind not in allowed: issues.append(f"artifact_{i}_type_not_allowed")
        if not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest):
            issues.append(f"artifact_{i}_digest_invalid")
        else: verified.append({"artifact_ref":ref,"artifact_type":kind,"sha256":digest})
        if item.get("independent_source") is not True:
            issues.append(f"artifact_{i}_independent_source_not_attested")
        if item.get("collected_at") is None or _parse_time(item.get("collected_at")) is None:
            issues.append(f"artifact_{i}_timestamp_invalid")
    return {"status":"PASS" if not issues else "BLOCKED",
            "issues":sorted(set(issues)),"verified_artifacts":verified,
            "independence_cryptographically_proven":False}

def verify_recovery_drill_receipt(receipt,expected_manifest_digest,now,
                                  maximum_age_seconds=604800):
    issues=[]
    if not isinstance(receipt,dict):
        return {"status":"BLOCKED","issues":["drill_receipt_invalid"]}
    required=("drill_ref","environment_ref","started_at","completed_at",
              "result","observed_rto_seconds","observed_rpo_seconds",
              "manifest_sha256","operator_ref")
    for field in required:
        if field not in receipt: issues.append(f"{field}_missing")
    start=_parse_time(receipt.get("started_at")); end=_parse_time(receipt.get("completed_at"))
    current=_parse_time(now)
    if not start: issues.append("drill_start_time_invalid")
    if not end: issues.append("drill_end_time_invalid")
    if not current: issues.append("verification_time_invalid")
    if start and end and end<=start: issues.append("drill_time_order_invalid")
    if end and current:
        age=(current-end).total_seconds()
        if age<0: issues.append("drill_completion_in_future")
        elif age>maximum_age_seconds: issues.append("drill_receipt_stale")
    if receipt.get("result")!="PASS": issues.append("drill_not_passed")
    for field in ("observed_rto_seconds","observed_rpo_seconds"):
        v=receipt.get(field)
        if not isinstance(v,(int,float)) or isinstance(v,bool) or v<0:
            issues.append(f"{field}_invalid")
    if receipt.get("manifest_sha256")!=expected_manifest_digest:
        issues.append("drill_manifest_binding_mismatch")
    if not isinstance(receipt.get("operator_ref"),str) or not receipt["operator_ref"].strip():
        issues.append("operator_ref_invalid")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues)),
            "execution_independently_confirmed":False}

def evaluate_recovery_objectives(drill_receipt,objectives):
    issues=[]
    if not isinstance(drill_receipt,dict) or not isinstance(objectives,dict):
        return {"status":"BLOCKED","issues":["objective_inputs_invalid"]}
    for observed,limit in (("observed_rto_seconds","rto_seconds"),
                           ("observed_rpo_seconds","rpo_seconds")):
        actual=drill_receipt.get(observed); target=objectives.get(limit)
        if not isinstance(actual,(int,float)) or isinstance(actual,bool) or actual<0:
            issues.append(f"{observed}_invalid")
        if not isinstance(target,(int,float)) or isinstance(target,bool) or target<0:
            issues.append(f"{limit}_invalid")
        elif isinstance(actual,(int,float)) and not isinstance(actual,bool) and actual>target:
            issues.append(f"{observed}_objective_breached")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues)),
            "objectives_measured_from_supplied_receipt":True}

def validate_dependency_readiness(dependencies):
    if not isinstance(dependencies,list) or not dependencies:
        return {"status":"BLOCKED","issues":["dependencies_missing"]}
    issues=[]; refs=set()
    for i,d in enumerate(dependencies):
        if not isinstance(d,dict):
            issues.append(f"dependency_{i}_invalid"); continue
        ref=d.get("dependency_ref")
        if not isinstance(ref,str) or not ref.strip(): issues.append(f"dependency_{i}_ref_invalid")
        elif ref in refs: issues.append(f"dependency_{i}_duplicate")
        refs.add(ref)
        if d.get("status")!="READY": issues.append(f"dependency_{i}_not_ready")
        if d.get("evidence_ref") is None: issues.append(f"dependency_{i}_evidence_missing")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues))}

def build_recovery_decision(evidence_result,drill_result,objective_result,
                            dependency_result,incident_state,hold_state):
    checks={
      "evidence":isinstance(evidence_result,dict) and evidence_result.get("status")=="PASS",
      "drill":isinstance(drill_result,dict) and drill_result.get("status")=="PASS",
      "objectives":isinstance(objective_result,dict) and objective_result.get("status")=="PASS",
      "dependencies":isinstance(dependency_result,dict) and dependency_result.get("status")=="PASS",
      "incident_closed":incident_state=="CLOSED",
      "hold_cleared":hold_state=="CLEARED"}
    issues=[f"{k}_not_satisfied" for k,v in checks.items() if not v]
    return {"status":"READY_FOR_AUTHORIZED_REVIEW" if not issues else "BLOCKED",
            "checks":checks,"issues":issues,"workload_resumed":False,
            "production_failover_executed":False,"authorization_granted":False}

def stage_790_recovery_gate(decision,approval_record=None):
    if not isinstance(decision,dict) or decision.get("status")!="READY_FOR_AUTHORIZED_REVIEW":
        return {"status":"BLOCKED","issues":["recovery_prerequisites_not_met"],
                "restart_authorized":False,"workload_resumed":False}
    # Approval record is deliberately not treated as authentication or permission.
    if not isinstance(approval_record,dict) or approval_record.get("authenticated") is not True:
        return {"status":"READY_FOR_AUTHORIZED_REVIEW",
                "issues":["independent_authenticated_authorization_required"],
                "restart_authorized":False,"workload_resumed":False}
    return {"status":"READY_FOR_AUTHORIZED_REVIEW",
            "issues":["authorization_must_be_enforced_by_external_control_plane"],
            "restart_authorized":False,"workload_resumed":False,
            "approval_claim_recorded":True}
