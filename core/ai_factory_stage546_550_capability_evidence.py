"""Declarative capability-evidence checks for AI Factory stages 546-550."""
from __future__ import annotations

REQUIRED={
 546:("capability_id","before_measurement_refs","after_measurement_refs","measurement_protocol"),
 547:("delta_method","delta_uncertainty","sample_count","uncertainty_refs"),
 548:("regression_guardrails","regression_outcomes","regression_evidence_refs"),
 549:("replication_protocol","replication_refs","independent_reviewer_refs"),
}

def _missing(record,keys):
 return [k for k in keys if k not in record or record[k] in (None,"",[],{})]

def _refs_ok(value):
 return isinstance(value,list) and bool(value) and all(isinstance(x,str) and x for x in value) and len(value)==len(set(value))

def validate_capability_evidence(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 for field in ("before_measurement_refs","after_measurement_refs","uncertainty_refs","regression_evidence_refs","replication_refs","independent_reviewer_refs"):
  if not _refs_ok(record.get(field)):
   issues.append(f"{field}_invalid_or_duplicate")
 before,after=record.get("before_measurement_refs",[]),record.get("after_measurement_refs",[])
 if _refs_ok(before) and _refs_ok(after) and set(before)&set(after):
  issues.append("before_after_evidence_overlap")
 count=record.get("sample_count")
 if not isinstance(count,int) or isinstance(count,bool) or count<1:
  issues.append("sample_count_invalid")
 uncertainty=record.get("delta_uncertainty")
 if not isinstance(uncertainty,dict) or not uncertainty:
  issues.append("delta_uncertainty_invalid")
 if record.get("regression_outcomes") and (not isinstance(record["regression_outcomes"],dict) or any(v!="pass" for v in record["regression_outcomes"].values())):
  issues.append("regression_guardrail_not_clear")
 if not isinstance(record.get("regression_guardrails"),dict) or not record["regression_guardrails"]:
  issues.append("regression_guardrails_invalid")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"capability_gain_proven":False,"replication_executed":False}

def stage_550_evidence_gate(record):
 result=validate_capability_evidence(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_acceptance":False}
