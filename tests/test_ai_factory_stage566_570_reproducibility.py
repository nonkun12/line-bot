import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage566",Path(__file__).parents[1]/"core/ai_factory_stage566_570_reproducibility.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"protocol_id":"proto","repeat_run_refs":["run1","run2"],"minimum_repeats":2,
 "environment_fingerprints":["env1","env2"],"configuration_fingerprints":["cfg1","cfg2"],"drift_policy":"documented_and_bounded",
 "metric_observations":{"score":[1,1.1]},"variance_method":"range","variance_limit":0.2,
 "cross_run_guardrails":{"safety":"limit"},"cross_run_outcomes":{"safety":"pass"},"cross_run_evidence_refs":["e1","e2"]}

def test_complete_metadata_is_not_reproducibility_proof():
 x=m.stage_570_reproducibility_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["reproducibility_established"] is False and x["runs_executed"] is False

def test_single_repeat_and_missing_environment_block():
 x=good();x["minimum_repeats"]=1;x["environment_fingerprints"]=["env"]
 assert m.validate_reproducibility(x)["status"]=="BLOCKED"

def test_failed_guardrail_blocks():
 x=good();x["cross_run_outcomes"]["safety"]="unknown"
 assert m.validate_reproducibility(x)["status"]=="BLOCKED"

def test_invalid_variance_limit_blocks():
 x=good();x["variance_limit"]=-1
 assert m.validate_reproducibility(x)["status"]=="BLOCKED"
