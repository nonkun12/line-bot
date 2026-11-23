import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage581",Path(__file__).parents[1]/"core/ai_factory_stage581_585_feedback_quality.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"feedback_source_refs":["source1"],"feedback_scope":"offline evaluation feedback","collection_window":"2026-Q4",
 "labeling_protocol_ref":"label-protocol","label_quality_checks":{"agreement":"reported"},"annotator_separation":True,
 "signal_normalization_method":"fixed rubric mapping","noise_handling_policy":"retain and flag","outlier_policy":"manual review",
 "feedback_to_hypothesis_refs":["hypothesis1"],"traceability_map":{"source1":"hypothesis1"},
 "counterexample_register":{"case1":"retained"},"feedback_consent":True}

def test_complete_feedback_still_needs_review():
 x=m.stage_585_feedback_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["feedback_validated"] is False and x["training_authorized"] is False

def test_missing_consent_blocks():
 x=good();x["feedback_consent"]=False
 assert m.validate_feedback_quality(x)["status"]=="BLOCKED"

def test_missing_counterexamples_and_traceability_block():
 x=good();x["counterexample_register"]={};x["traceability_map"]={}
 assert m.validate_feedback_quality(x)["status"]=="BLOCKED"

def test_annotator_separation_blocks():
 x=good();x["annotator_separation"]=False
 assert m.validate_feedback_quality(x)["status"]=="BLOCKED"
