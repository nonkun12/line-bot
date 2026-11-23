"""Evaluator independence and audit checks for AI Factory stages 556-560."""
from __future__ import annotations

REQUIRED={
 556:("evaluator_id","evaluator_role","evaluator_method_ref"),
 557:("conflict_declarations","access_scope","blindness_record"),
 558:("evaluator_input_refs","evaluator_output_refs","evaluation_trace_refs"),
 559:("reviewer_identity_ref","review_scope","review_findings_ref"),
}

def _missing(obj,keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",[],{})]

def _refs(value):
 return isinstance(value,list) and bool(value) and all(isinstance(v,str) and v for v in value) and len(value)==len(set(value))

def validate_evaluator_independence(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 for field in ("evaluator_input_refs","evaluator_output_refs","evaluation_trace_refs"):
  if not _refs(record.get(field)):
   issues.append(f"{field}_invalid_or_duplicate")
 for field in ("conflict_declarations","access_scope"):
  if not isinstance(record.get(field),dict) or not record[field]:
   issues.append(f"{field}_invalid")
 if record.get("conflict_declarations") and any(v!="none_declared" for v in record["conflict_declarations"].values()):
  issues.append("conflict_requires_resolution")
 if record.get("blindness_record") not in ("blinded","not_applicable_with_reason"):
  issues.append("blindness_not_documented")
 if record.get("review_scope") not in ("independent","limited_with_reason"):
  issues.append("review_scope_not_qualified")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"independence_established":False,"audit_performed":False}

def stage_560_independence_gate(record):
 result=validate_evaluator_independence(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","self_certification_sufficient":False}
