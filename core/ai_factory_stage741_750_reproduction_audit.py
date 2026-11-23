"""Reproduction receipt and audit validation (AI Factory Stages 741-750).

Validates externally produced, caller-supplied reproduction receipts. This module
does not launch commands, access filesystems, authenticate people, or verify
digital signatures.
"""
from __future__ import annotations
import hashlib
import json
import math
from datetime import datetime

def _text(v):
    return isinstance(v,str) and bool(v.strip())

def _sha(v):
    if not isinstance(v,str) or len(v)!=64 or v!=v.lower(): return False
    try: bytes.fromhex(v)
    except ValueError: return False
    return True

def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()

def verify_execution_receipt(receipt, artifact_payloads):
    issues=[]
    if not isinstance(receipt,dict):
        return {"status":"BLOCKED","issues":["receipt_invalid"]}
    required=("receipt_ref","plan_ref","attempt_ref","environment_ref","command_ref",
              "input_manifest_ref","output_manifest_ref","stdout_sha256","stderr_sha256",
              "exit_code","started_at","finished_at","executor_ref","audit_ref",
              "execution_performed","signature_verified")
    missing=[k for k in required if k not in receipt or receipt[k] is None]
    for k in ("receipt_ref","plan_ref","attempt_ref","environment_ref","command_ref",
              "input_manifest_ref","output_manifest_ref","executor_ref","audit_ref"):
        if not _text(receipt.get(k)): issues.append(f"{k}_invalid")
    for k in ("stdout_sha256","stderr_sha256"):
        if not _sha(receipt.get(k)): issues.append(f"{k}_invalid")
    if not isinstance(receipt.get("exit_code"),int) or isinstance(receipt.get("exit_code"),bool):
        issues.append("exit_code_invalid")
    start=_time(receipt.get("started_at")); finish=_time(receipt.get("finished_at"))
    if start is None: issues.append("started_at_invalid")
    if finish is None: issues.append("finished_at_invalid")
    if start and finish and finish<start: issues.append("execution_time_order_invalid")
    if receipt.get("execution_performed") is not True: issues.append("execution_receipt_not_confirmed")
    if receipt.get("signature_verified") is not False: issues.append("signature_verification_not_supported")
    if not isinstance(artifact_payloads,dict): issues.append("artifact_payloads_invalid")
    else:
        for name in ("stdout","stderr"):
            data=artifact_payloads.get(name)
            if not isinstance(data,(bytes,bytearray,memoryview)):
                issues.append(f"{name}_bytes_missing")
            elif _sha(receipt.get(f"{name}_sha256")) and hashlib.sha256(bytes(data)).hexdigest()!=receipt[f"{name}_sha256"]:
                issues.append(f"{name}_digest_mismatch")
    if missing: issues.append("receipt_fields_missing")
    return {"status":"PASS" if not issues else "BLOCKED",
            "issues":sorted(set(issues)),"missing":missing,
            "exit_success":receipt.get("exit_code")==0 if isinstance(receipt.get("exit_code"),int) and not isinstance(receipt.get("exit_code"),bool) else False,
            "executor_authenticated":False,"signature_verified":False}

def compare_reproduction_attempts(attempts, required_repeats=2):
    issues=[]
    if not isinstance(required_repeats,int) or isinstance(required_repeats,bool) or required_repeats<2:
        return {"status":"BLOCKED","issues":["required_repeats_invalid"],"matched":False}
    if not isinstance(attempts,list) or len(attempts)<required_repeats:
        return {"status":"BLOCKED","issues":["insufficient_attempts"],"matched":False}
    refs=set(); fingerprints=[]
    for i,item in enumerate(attempts):
        if not isinstance(item,dict):
            issues.append(f"attempt_invalid:{i}"); continue
        for k in ("attempt_ref","plan_ref","environment_ref","command_ref","input_manifest_ref","output_manifest_ref"):
            if not _text(item.get(k)): issues.append(f"{k}_invalid:{i}")
        ref=item.get("attempt_ref")
        if _text(ref):
            if ref in refs: issues.append(f"attempt_ref_duplicate:{ref}")
            refs.add(ref)
        if item.get("status")!="PASS": issues.append(f"attempt_not_pass:{i}")
        if item.get("exit_code")!=0 or isinstance(item.get("exit_code"),bool):
            issues.append(f"attempt_exit_not_zero:{i}")
        for k in ("stdout_sha256","stderr_sha256","output_sha256"):
            if not _sha(item.get(k)): issues.append(f"{k}_invalid:{i}")
        fingerprints.append(tuple(item.get(k) for k in
          ("plan_ref","environment_ref","command_ref","input_manifest_ref","output_manifest_ref","stdout_sha256","stderr_sha256","output_sha256")))
    if len(fingerprints)>=required_repeats and any(x!=fingerprints[0] for x in fingerprints[1:]):
        issues.append("reproduction_outputs_not_identical")
    if len(refs)<required_repeats: issues.append("unique_attempts_insufficient")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues)),
            "matched":not issues,"attempt_count":len(attempts),
            "reproduction_executed_by_validator":False}

def validate_reproduction_plan(plan):
    if not isinstance(plan,dict):
        return {"status":"BLOCKED","issues":["plan_invalid"]}
    issues=[]
    for k in ("plan_ref","protocol_ref","command_ref","environment_ref","input_manifest_ref",
              "expected_output_ref","dependency_lock_ref","seed_ref","timeout_policy_ref",
              "resource_limit_ref","rollback_policy_ref","owner_ref"):
        if not _text(plan.get(k)): issues.append(f"{k}_invalid")
    if plan.get("network_access") is not False: issues.append("network_access_must_be_disabled")
    if plan.get("write_scope")!="TEMPORARY_SANDBOX": issues.append("write_scope_not_bounded")
    if plan.get("secret_access") is not False: issues.append("secret_access_must_be_disabled")
    if plan.get("production_target") is not False: issues.append("production_target_must_be_disabled")
    if plan.get("human_review_required") is not True: issues.append("human_review_boundary_missing")
    if plan.get("max_duration_seconds") not in range(1,3601): issues.append("duration_limit_invalid")
    if plan.get("max_output_bytes") not in range(1,104857601): issues.append("output_limit_invalid")
    return {"status":"PASS" if not issues else "BLOCKED","issues":sorted(set(issues)),
            "plan_authorized":False,"execution_started":False}

def verify_audit_events(events):
    if not isinstance(events,list) or not events:
        return {"status":"BLOCKED","issues":["audit_events_invalid"],"verified_count":0}
    issues=[]; previous=None; refs=set(); count=0
    for i,event in enumerate(events):
        if not isinstance(event,dict):
            issues.append(f"audit_event_invalid:{i}"); continue
        ref=event.get("event_ref")
        if not _text(ref): issues.append(f"audit_event_ref_invalid:{i}")
        elif ref in refs: issues.append(f"audit_event_ref_duplicate:{ref}")
        else: refs.add(ref)
        if event.get("previous_digest")!=previous: issues.append(f"audit_previous_digest_mismatch:{i}")
        digest=event.get("event_digest")
        body={k:v for k,v in event.items() if k!="event_digest"}
        if not _sha(digest): issues.append(f"audit_event_digest_invalid:{i}")
        else:
            try: actual=_digest(body)
            except (TypeError,ValueError,OverflowError):
                issues.append(f"audit_event_not_canonicalizable:{i}"); continue
            if actual!=digest: issues.append(f"audit_event_digest_mismatch:{i}")
            else: previous=digest; count+=1
    return {"status":"PASS" if not issues and count==len(events) else "BLOCKED",
            "issues":sorted(set(issues)),"verified_count":count,
            "chain_tip":previous if not issues else None}

def stage_750_reproduction_audit_gate(plan,receipts,attempts,audit_events,stdout_stderr_payloads):
    plan_result=validate_reproduction_plan(plan)
    receipt_results=[verify_execution_receipt(x,stdout_stderr_payloads.get(x.get("attempt_ref"),{}))
                     if isinstance(x,dict) else verify_execution_receipt(x,{}) for x in receipts] if isinstance(receipts,list) else []
    attempt_result=compare_reproduction_attempts(attempts)
    audit_result=verify_audit_events(audit_events)
    issues=list(plan_result["issues"])+list(attempt_result["issues"])+list(audit_result["issues"])
    for i,r in enumerate(receipt_results): issues.extend(f"receipt_{i}:{x}" for x in r["issues"])
    if not isinstance(receipts,list) or not receipts: issues.append("receipts_required")
    if any(not r["exit_success"] for r in receipt_results): issues.append("execution_receipt_nonzero_exit")
    passed=not issues and all(r["status"]=="PASS" for r in receipt_results)
    return {"status":"REPRODUCTION_EVIDENCE_VALIDATED" if passed else "BLOCKED",
            "gate":"READY_FOR_HUMAN_REVIEW" if passed else "BLOCKED",
            "issues":sorted(set(issues)),"plan":plan_result,"receipts":receipt_results,
            "attempt_comparison":attempt_result,"audit":audit_result,
            "reproduction_verified_by_validator":False,
            "executor_identity_authenticated":False,"model_change_authorized":False}
