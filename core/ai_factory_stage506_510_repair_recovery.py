"""Repair failure recovery and recurrence safeguards (Stages 506-510)."""
from __future__ import annotations
import hashlib,json
from typing import Any,Mapping,Sequence

def _seal(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def _str(x):return isinstance(x,str) and bool(x.strip())

def check_failed_repair_records(records:Sequence[Mapping[str,Any]])->dict:
 errors=[]
 if not records:errors.append("failed_repair_records_empty")
 ids=set()
 for i,r in enumerate(records):
  rid=r.get("repair_id")
  if not _str(rid) or rid in ids:errors.append(f"repair_id_invalid_duplicate:{i}")
  else:ids.add(rid)
  for k in ("failure_reason","evidence_ref","rollback_status","containment_ref"):
   if not _str(r.get(k)):errors.append(f"repair_failure_field_missing:{i}:{k}")
  if r.get("containment_confirmed") is not True:errors.append(f"containment_unconfirmed:{i}")
 return {"stage":506,"pass":not errors,"errors":errors}

def check_recovery_protocol(protocol:Mapping[str,Any])->dict:
 errors=[]
 for k in ("recovery_steps_ref","rollback_ref","revalidation_ref","owner_or_system_ref"):
  if not _str(protocol.get(k)):errors.append(f"recovery_protocol_missing:{k}")
 if protocol.get("rollback_required") is not True:errors.append("rollback_requirement_missing")
 if protocol.get("restart_allowed") is not False:errors.append("restart_not_disabled_by_default")
 return {"stage":507,"pass":not errors,"errors":errors,"automatic_restart_authorized":False}

def check_recurrence_monitoring(records:Sequence[Mapping[str,Any]],window_ref:str)->dict:
 errors=[]
 if not _str(window_ref):errors.append("recurrence_window_ref_missing")
 if not records:errors.append("recurrence_records_empty")
 for i,r in enumerate(records):
  for k in ("failure_signature","observed_ref","window_id"):
   if not _str(r.get(k)):errors.append(f"recurrence_field_missing:{i}:{k}")
 return {"stage":508,"pass":not errors,"errors":errors,"recurrence_claim_verified":False}

def check_preventive_action(action:Mapping[str,Any])->dict:
 errors=[]
 for k in ("action_id","scope","evidence_ref","test_ref","rollback_ref"):
  if not _str(action.get(k)):errors.append(f"prevention_field_missing:{k}")
 if action.get("applied") is not False:errors.append("prevention_action_execution_not_allowed")
 if action.get("review_required") is not True:errors.append("prevention_review_required")
 return {"stage":509,"pass":not errors,"errors":errors,"action_applied":False}

def evaluate_506_510(*,failed_repairs,recovery_protocol,recurrence_records,recurrence_window,preventive_action,unresolved_holds):
 checks=[check_failed_repair_records(failed_repairs),check_recovery_protocol(recovery_protocol),check_recurrence_monitoring(recurrence_records,recurrence_window),check_preventive_action(preventive_action)]
 hold_err=["unresolved_holds_present"] if unresolved_holds else []
 checks.append({"stage":510,"pass":not hold_err,"errors":hold_err})
 good=all(c.get("pass",False) for c in checks);payload={"checks":checks,"pass":good}
 return {"stage":510,"status":"READY_FOR_REVIEW" if good else "HOLD","checks":checks,"seal":_seal(payload),"rollback_executed":False,"restart_authorized":False,"preventive_action_applied":False,"hold_release_authorized":False,"merge_authorized":False,"deployment_authorized":False,"proposal_only":True}
