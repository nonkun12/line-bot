"""Feedback quality and learning-signal declarations for AI Factory stages 581-585."""
from __future__ import annotations

REQUIRED={
 581:("feedback_source_refs","feedback_scope","collection_window"),
 582:("labeling_protocol_ref","label_quality_checks","annotator_separation"),
 583:("signal_normalization_method","noise_handling_policy","outlier_policy"),
 584:("feedback_to_hypothesis_refs","traceability_map","counterexample_register"),
}

def _missing(obj, keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",{},[])]

def _text(value):
 return isinstance(value,str) and bool(value.strip())

def _text_list(value):
 return isinstance(value,list) and bool(value) and all(_text(x) for x in value)

def validate_feedback_quality(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{key}" for key in _missing(record,keys))
 for field in ("feedback_source_refs","feedback_to_hypothesis_refs"):
  if not _text_list(record.get(field)):
   issues.append(f"{field}_invalid")
 for field in ("feedback_scope","collection_window","labeling_protocol_ref","signal_normalization_method","noise_handling_policy","outlier_policy"):
  if not _text(record.get(field)):
   issues.append(f"{field}_invalid")
 for field in ("label_quality_checks","traceability_map","counterexample_register"):
  if not isinstance(record.get(field),dict) or not record[field]:
   issues.append(f"{field}_invalid")
 if record.get("annotator_separation") is not True:
  issues.append("annotator_separation_not_declared")
 if record.get("feedback_consent") is not True:
  issues.append("feedback_consent_not_declared")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"feedback_validated":False,"learning_signal_established":False}

def stage_585_feedback_gate(record):
 result=validate_feedback_quality(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","training_authorized":False}
