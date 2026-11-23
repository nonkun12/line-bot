"""Repeatability and reproducibility declarations for AI Factory stages 566-570."""
from __future__ import annotations

REQUIRED={
 566:("protocol_id","repeat_run_refs","minimum_repeats"),
 567:("environment_fingerprints","configuration_fingerprints","drift_policy"),
 568:("metric_observations","variance_method","variance_limit"),
 569:("cross_run_guardrails","cross_run_outcomes","cross_run_evidence_refs"),
}

def _missing(obj,keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",[],{})]

def _refs(v):
 return isinstance(v,list) and bool(v) and all(isinstance(x,str) and x for x in v) and len(v)==len(set(v))

def validate_reproducibility(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 if not _refs(record.get("repeat_run_refs")):
  issues.append("repeat_run_refs_invalid")
 repeats=record.get("minimum_repeats")
 if not isinstance(repeats,int) or isinstance(repeats,bool) or repeats<2:
  issues.append("minimum_repeats_invalid")
 for field in ("environment_fingerprints","configuration_fingerprints"):
  values=record.get(field)
  if not isinstance(values,list) or len(values)<2 or any(not isinstance(x,str) or not x for x in values):
   issues.append(f"{field}_invalid")
 if record.get("drift_policy") not in ("identical_required","documented_and_bounded"):
  issues.append("drift_policy_invalid")
 if not isinstance(record.get("metric_observations"),dict) or not record["metric_observations"]:
  issues.append("metric_observations_invalid")
 if record.get("variance_method") not in ("range","standard_deviation","declared_interval"):
  issues.append("variance_method_invalid")
 limit=record.get("variance_limit")
 if not isinstance(limit,(int,float)) or isinstance(limit,bool) or limit<0:
  issues.append("variance_limit_invalid")
 if not isinstance(record.get("cross_run_guardrails"),dict) or not record["cross_run_guardrails"]:
  issues.append("cross_run_guardrails_invalid")
 outcomes=record.get("cross_run_outcomes")
 if not isinstance(outcomes,dict) or not outcomes or any(v!="pass" for v in outcomes.values()):
  issues.append("cross_run_guardrail_not_clear")
 if not _refs(record.get("cross_run_evidence_refs")):
  issues.append("cross_run_evidence_refs_invalid")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"reproducibility_established":False,"runs_executed":False}

def stage_570_reproducibility_gate(record):
 result=validate_reproducibility(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_acceptance":False}
