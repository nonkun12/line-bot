import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage546",Path(__file__).parents[1]/"core/ai_factory_stage546_550_capability_evidence.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"capability_id":"reasoning","before_measurement_refs":["b1"],"after_measurement_refs":["a1"],"measurement_protocol":"same",
 "delta_method":"paired","delta_uncertainty":{"interval":[0.1,0.2]},"sample_count":8,"uncertainty_refs":["u1"],
 "regression_guardrails":{"safety":"no worse"},"regression_outcomes":{"safety":"pass"},"regression_evidence_refs":["r1"],
 "replication_protocol":"repeat independently","replication_refs":["rep1"],"independent_reviewer_refs":["rev1"]}

def test_complete_evidence_requires_review():
 x=m.stage_550_evidence_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["capability_gain_proven"] is False and x["automatic_acceptance"] is False

def test_missing_or_overlapping_evidence_blocks():
 x=good();x["before_measurement_refs"]=["same"];x["after_measurement_refs"]=["same"]
 assert m.validate_capability_evidence(x)["status"]=="BLOCKED"
 assert m.stage_550_evidence_gate({})["gate"]=="BLOCKED"

def test_uncertain_regression_blocks():
 x=good();x["regression_outcomes"]["safety"]="unknown"
 assert m.validate_capability_evidence(x)["status"]=="BLOCKED"

def test_invalid_sample_count_blocks():
 x=good();x["sample_count"]=True
 assert m.validate_capability_evidence(x)["status"]=="BLOCKED"
