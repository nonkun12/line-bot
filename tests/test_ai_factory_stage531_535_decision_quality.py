import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage531",Path(__file__).parents[1]/"core/ai_factory_stage531_535_decision_quality.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
    return {"decision_id":"d1","rationale":"reason","alternatives":["x"],"evidence_refs":["e1","e2"],
    "rubric_id":"r1","criteria":["c"],"score_scale":"1-5","mapping_refs":["m1"],
    "comparison_protocol":"p","control_conditions":["same"],"blindness_declaration":"blind","protocol_refs":["p1"],
    "sample_count":5,"uncertainty_method":"interval","uncertainty_bounds":[0.1,0.8],"sample_refs":["s1"]}

def test_complete_record_still_requires_review():
    result=m.stage_535_review_gate(good())
    assert result["status"]=="DECLARATIONS_COMPLETE"
    assert result["gate"]=="REVIEW_REQUIRED"
    assert result["automatic_approval"] is False
    assert result["evaluation_executed"] is False

def test_missing_fields_block():
    result=m.stage_535_review_gate({})
    assert result["gate"]=="BLOCKED" and result["missing"]

def test_duplicates_and_unsupported_claim_block():
    x=good();x["evidence_refs"]=["same","same"];x["causal_claims_without_design"]=True
    assert m.validate_decision_quality(x)["status"]=="BLOCKED"

def test_invalid_bounds_and_sample_count_block():
    x=good();x["sample_count"]=0;x["uncertainty_bounds"]=[3,1]
    assert m.validate_decision_quality(x)["status"]=="BLOCKED"
