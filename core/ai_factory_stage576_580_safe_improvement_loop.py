"""Safe improvement-loop planning declarations (Stages 576-580)."""
from __future__ import annotations

REQUIRED={
 576:("validation_plan_ref","acceptance_criteria","stop_conditions"),
 577:("risk_register","side_effect_guardrails","rollback_plan_ref"),
 578:("independent_evaluator_ref","evaluator_separation","blindness_declaration"),
 579:("before_evidence_ref","after_evidence_ref","comparison_method"),
}

def _missing(obj,keys):
 return [k for k in keys if k not in obj or obj[k] in (None,"",[],{})]

def _nonempty_text(value):
 return isinstance(value,str) and bool(value.strip())

def validate_safe_improvement_loop(record):
 if not isinstance(record,dict):
  return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
 missing=[]
 issues=[]
 for stage,keys in REQUIRED.items():
  missing.extend(f"{stage}:{k}" for k in _missing(record,keys))
 for field in ("validation_plan_ref","rollback_plan_ref","independent_evaluator_ref","before_evidence_ref","after_evidence_ref"):
  if not _nonempty_text(record.get(field)):
   issues.append(f"{field}_invalid")
 for field in ("acceptance_criteria","stop_conditions","side_effect_guardrails"):
  v=record.get(field)
  if not isinstance(v,list) or not v or any(not _nonempty_text(x) for x in v):
   issues.append(f"{field}_invalid")
 if not isinstance(record.get("risk_register"),dict) or not record["risk_register"]:
  issues.append("risk_register_invalid")
 if record.get("evaluator_separation") is not True:
  issues.append("evaluator_separation_not_declared")
 if record.get("blindness_declaration") not in ("blinded","not_blinded_with_rationale"):
  issues.append("blindness_declaration_invalid")
 if record.get("comparison_method") not in ("paired","controlled","pre_registered"):
  issues.append("comparison_method_invalid")
 if record.get("production_change") is not False:
  issues.append("production_change_must_be_false")
 if record.get("model_change") is not False:
  issues.append("model_change_must_be_false")
 if missing or issues:
  return {"status":"BLOCKED","missing":missing,"issues":issues}
 return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],"validation_executed":False,"improvement_verified":False}

def stage_580_improvement_loop_gate(record):
 result=validate_safe_improvement_loop(record)
 return {**result,"gate":"BLOCKED" if result["status"]=="BLOCKED" else "REVIEW_REQUIRED","automatic_execution":False,"automatic_acceptance":False}
