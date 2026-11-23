"""Capability diagnostics and improvement-candidate declarations (Stages 571-575)."""
from __future__ import annotations

REQUIRED={
 571:("capability_profile_ref","capability_dimensions","evaluation_scope"),
 572:("baseline_ref","task_cohorts","baseline_method"),
 573:("weakness_findings","uncertainty_register","known_limitations"),
 574:("improvement_hypotheses","causal_rationale","falsification_criteria"),
}

def _missing(obj, keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",[],{})]

def _string_list(value, minimum=1):
 return isinstance(value,list) and len(value)>=minimum and all(isinstance(x,str) and x.strip() for x in value)

def validate_capability_diagnostics(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 for field in ("capability_dimensions","task_cohorts","weakness_findings","known_limitations","improvement_hypotheses","falsification_criteria"):
  if not _string_list(record.get(field)):
   issues.append(f"{field}_invalid")
 for field in ("capability_profile_ref","baseline_ref"):
  if not isinstance(record.get(field),str) or not record[field].strip():
   issues.append(f"{field}_invalid")
 if not isinstance(record.get("uncertainty_register"),dict) or not record["uncertainty_register"]:
  issues.append("uncertainty_register_invalid")
 if record.get("baseline_method") not in ("fixed_suite","stratified_suite","external_reference"):
  issues.append("baseline_method_invalid")
 if not isinstance(record.get("causal_rationale"),str) or len(record["causal_rationale"].strip())<12:
  issues.append("causal_rationale_invalid")
 scope=record.get("evaluation_scope")
 if not isinstance(scope,str) or not scope.strip():
  issues.append("evaluation_scope_invalid")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"capability_measured":False,"improvement_demonstrated":False}

def stage_575_candidate_gate(record):
 result=validate_capability_diagnostics(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","candidate_authorized":False}
