import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location("stage551",Path(__file__).parents[1]/"core/ai_factory_stage551_555_measurement_execution.py")
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def good():
 return {"run_id":"run1","run_started_at":"2026-01-01T00:00:00Z","run_completed_at":"2026-01-01T00:01:00Z","execution_status":"completed",
 "environment_fingerprint":"env","dependency_lock_ref":"lock1","runtime_config_ref":"cfg1",
 "input_manifest_refs":["in1"],"output_manifest_refs":["out1"],"artifact_digest_map":{"out1":"sha256:abc"},
 "retry_history":[],"failure_records":[],"termination_reason":"normal"}

def test_complete_declarations_still_need_review():
 x=m.stage_555_execution_gate(good())
 assert x["status"]=="DECLARATIONS_COMPLETE" and x["gate"]=="REVIEW_REQUIRED"
 assert x["execution_performed"] is False and x["artifacts_verified"] is False

def test_missing_or_duplicate_manifest_blocks():
 x=good();x["input_manifest_refs"]=["same","same"]
 assert m.validate_measurement_execution(x)["status"]=="BLOCKED"

def test_incomplete_execution_blocks():
 x=good();x["execution_status"]="failed"
 assert m.validate_measurement_execution(x)["status"]=="BLOCKED"

def test_time_order_and_digest_block():
 x=good();x["run_started_at"]="2026-02-01T00:00:00Z"
 assert m.validate_measurement_execution(x)["status"]=="BLOCKED"
 x=good();x["artifact_digest_map"]={"out1":""}
 assert m.validate_measurement_execution(x)["status"]=="BLOCKED"
