import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage536",Path(__file__).parents[1]/"core/ai_factory_stage536_540_improvement_verification.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
    return {"before_refs":["b1"],"after_refs":["a1"],"pairing_method":"paired",
    "attribution_method":"declared","confounders":["hardware"],"attribution_refs":["ar1"],
    "guardrails":{"latency":"limit"},"regression_results":{"safety":"pass"},
    "regression_refs":["rr1"],"reproduction_steps":["repeat"],"environment_fingerprint":"env",
    "independent_evaluator_refs":["ie1"]}

def test_complete_is_review_only():
    x=m.stage_540_review_gate(good())
    assert x["status"]=="DECLARATIONS_COMPLETE"
    assert x["gate"]=="REVIEW_REQUIRED"
    assert x["improvement_verified"] is False
    assert x["automatic_acceptance"] is False

def test_missing_fields_fail_closed():
    assert m.stage_540_review_gate({})["gate"]=="BLOCKED"

def test_overlap_and_regression_fail():
    x=good();x["before_refs"]=["same"];x["after_refs"]=["same"];x["regression_results"]={"safety":"fail"}
    assert m.validate_improvement_verification(x)["status"]=="BLOCKED"

def test_unknown_regression_is_not_pass():
    x=good();x["regression_results"]={"safety":"unknown"}
    assert m.validate_improvement_verification(x)["status"]=="BLOCKED"
