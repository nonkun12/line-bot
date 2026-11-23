"""Declarative measurement-execution integrity checks for AI Factory stages 551-555."""
from __future__ import annotations

REQUIRED={
 551:("run_id","run_started_at","run_completed_at","execution_status"),
 552:("environment_fingerprint","dependency_lock_ref","runtime_config_ref"),
 553:("input_manifest_refs","output_manifest_refs","artifact_digest_map"),
 554:("retry_history","failure_records","termination_reason"),
}

def _missing(obj,keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",[],{})]

def _refs(value):
 return isinstance(value,list) and bool(value) and all(isinstance(v,str) and v for v in value) and len(value)==len(set(value))

def validate_measurement_execution(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 for field in ("input_manifest_refs","output_manifest_refs"):
  if not _refs(record.get(field)):
   issues.append(f"{field}_invalid_or_duplicate")
 if not isinstance(record.get("artifact_digest_map"),dict) or not record["artifact_digest_map"]:
  issues.append("artifact_digest_map_invalid")
 elif any(not isinstance(v,str) or not v.strip() for v in record["artifact_digest_map"].values()):
  issues.append("artifact_digest_missing")
 if not isinstance(record.get("retry_history"),list):
  issues.append("retry_history_invalid")
 if not isinstance(record.get("failure_records"),list):
  issues.append("failure_records_invalid")
 if record.get("execution_status") not in ("completed","failed","cancelled"):
  issues.append("execution_status_invalid")
 if record.get("execution_status")!="completed":
  issues.append("execution_not_completed")
 if record.get("termination_reason") not in ("normal","declared_failure","cancelled"):
  issues.append("termination_reason_invalid")
 if record.get("run_started_at") and record.get("run_completed_at") and record["run_completed_at"]<record["run_started_at"]:
  issues.append("execution_time_order_invalid")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"execution_performed":False,"artifacts_verified":False}

def stage_555_execution_gate(record):
 result=validate_measurement_execution(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_replay":False}
