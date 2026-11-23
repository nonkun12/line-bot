"""Adaptive governance and bounded policy-refresh declarations (Stages 586-590)."""
from __future__ import annotations

REQUIRED={
 586:("policy_version","policy_owner_ref","policy_change_reason"),
 587:("change_impact_assessment","affected_capability_refs","compatibility_checks"),
 588:("monitoring_signal_refs","review_interval","alert_thresholds"),
 589:("escalation_matrix","pause_conditions","recovery_criteria"),
}

def _missing(obj,keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",{},[])]

def _text(value):
 return isinstance(value,str) and bool(value.strip())

def _text_list(value):
 return isinstance(value,list) and bool(value) and all(_text(x) for x in value)

def validate_adaptive_governance(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{key}" for key in _missing(record,keys))
 for field in ("policy_version","policy_owner_ref","policy_change_reason","review_interval"):
  if not _text(record.get(field)):
   issues.append(f"{field}_invalid")
 for field in ("affected_capability_refs","monitoring_signal_refs"):
  if not _text_list(record.get(field)):
   issues.append(f"{field}_invalid")
 for field in ("change_impact_assessment","compatibility_checks","alert_thresholds","escalation_matrix"):
  if not isinstance(record.get(field),dict) or not record[field]:
   issues.append(f"{field}_invalid")
 for field in ("pause_conditions","recovery_criteria"):
  if not _text_list(record.get(field)):
   issues.append(f"{field}_invalid")
 if record.get("policy_approval_ref") in (None,""):
  issues.append("policy_approval_ref_missing")
 if record.get("automatic_policy_activation") is not False:
  issues.append("automatic_policy_activation_must_be_false")
 if record.get("production_policy_write") is not False:
  issues.append("production_policy_write_must_be_false")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"policy_change_executed":False,"monitoring_active":False}

def stage_590_governance_gate(record):
 result=validate_adaptive_governance(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_activation":False,"production_write":False}
