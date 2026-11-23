import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage541",Path(__file__).parents[1]/"core/ai_factory_stage541_545_benchmark_validity.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"dataset_id":"ds","dataset_version":"v1","provenance_refs":["p1"],"permission_declaration":"authorized",
 "coverage_matrix":{"capability":["case1"]},"target_capabilities":["capability"],"coverage_refs":["c1"],
 "baseline_id":"base","baseline_version":"v1","baseline_protocol":"same protocol","parity_declaration":"matched",
 "contamination_checks":{"train_test":"clear"},"leakage_checks":{"holdout":"clear"},"holdout_separation_refs":["h1"]}

def test_complete_is_not_validity_proof():
 x=m.stage_545_benchmark_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["benchmark_executed"] is False and x["validity_established"] is False

def test_missing_or_duplicate_refs_block():
 x=good();x["provenance_refs"]=["p","p"]
 assert m.validate_benchmark_validity(x)["status"]=="BLOCKED"

def test_contamination_and_leakage_block():
 x=good();x["contamination_checks"]["train_test"]="detected"
 assert m.validate_benchmark_validity(x)["status"]=="BLOCKED"
 x=good();x["leakage_checks"]["holdout"]="unknown"
 assert m.validate_benchmark_validity(x)["status"]=="BLOCKED"

def test_unmatched_baseline_parity_blocks():
 x=good();x["parity_declaration"]="unknown"
 assert m.validate_benchmark_validity(x)["status"]=="BLOCKED"
