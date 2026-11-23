import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage576",Path(__file__).parents[1]/"core/ai_factory_stage576_580_safe_improvement_loop.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"validation_plan_ref":"plan1","acceptance_criteria":["metric improves"],"stop_conditions":["guardrail breach"],
 "risk_register":{"regression":"medium"},"side_effect_guardrails":["no production writes"],"rollback_plan_ref":"rollback1",
 "independent_evaluator_ref":"evaluator1","evaluator_separation":True,"blindness_declaration":"blinded",
 "before_evidence_ref":"before1","after_evidence_ref":"after1","comparison_method":"paired",
 "production_change":False,"model_change":False}

def test_complete_plan_still_requires_review():
 x=m.stage_580_improvement_loop_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["validation_executed"] is False and x["automatic_execution"] is False

def test_missing_rollback_and_risk_block():
 x=good();x["rollback_plan_ref"]="";x["risk_register"]={}
 assert m.validate_safe_improvement_loop(x)["status"]=="BLOCKED"

def test_evaluator_not_separated_blocks():
 x=good();x["evaluator_separation"]=False
 assert m.validate_safe_improvement_loop(x)["status"]=="BLOCKED"

def test_production_or_model_change_blocks():
 for field in ("production_change","model_change"):
  x=good();x[field]=True
  assert m.validate_safe_improvement_loop(x)["status"]=="BLOCKED"

def test_unknown_comparison_method_blocks():
 x=good();x["comparison_method"]="informal"
 assert m.validate_safe_improvement_loop(x)["status"]=="BLOCKED"
