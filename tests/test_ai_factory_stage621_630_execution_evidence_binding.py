import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("stage621", Path(__file__).parents[1] / "core/ai_factory_stage621_630_execution_evidence_binding.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def good():
    return {
      "experiment_ref":"exp-1","protocol_ref":"protocol-1",
      "execution_envelope":{"environment_ref":"env-1","command_ref":"cmd-1","input_manifest_ref":"inputs-1",
        "timeout_seconds":60,"memory_limit_mb":1024,"cpu_limit":2,"network_policy":"DENY_DECLARED","enforced":False},
      "result_artifacts":[{"artifact_ref":"artifact-1","run_ref":"run-1","media_type":"application/json","sha256_declared":"a"*64,"size_bytes":128}],
      "outcome_records":[{"run_ref":"run-1","outcome":"SUCCEEDED_DECLARED","started_at":"2026-11-23T10:00:00Z","finished_at":"2026-11-23T10:01:00Z"}],
      "failure_records":[],"abort_records":[],"output_schema_ref":"schema-1",
      "schema_validation":{"status":"SCHEMA_VALIDATION_DECLARED_PASS","validator_ref":"validator-1","checked_artifact_refs":["artifact-1"]},
      "benchmark_protocol_ref":"benchmark-1",
      "sample_coverage":{"population_ref":"population-1","sample_manifest_ref":"sample-1","population_count":100,"sample_count":20,"sampling_method":"RANDOM_DECLARED"},
      "uncertainty":{"lower_bound":0.8,"upper_bound":0.9,"confidence_level":0.95,"method_ref":"interval-1"},
      "baseline_comparison":{"baseline_ref":"baseline-1","candidate_ref":"candidate-1","metric_name":"score","comparison_protocol_ref":"comparison-1","delta":0.05,"direction":"IMPROVED_DECLARED"},
      "created_at":"2026-11-23T10:05:00Z","automatic_execution":False}

def test_complete_declarations_are_review_only():
    r=m.stage_630_execution_evidence_gate(good())
    assert r["status"]=="DECLARATIONS_COMPLETE" and r["gate"]=="READY_FOR_INDEPENDENT_REVIEW"
    assert r["artifact_bytes_inspected"] is False and r["digests_verified"] is False
    assert r["resource_limits_enforced"] is False and r["capability_gain_verified"] is False
    assert r["execution_authorized"] is False

def test_missing_and_invalid_envelope_block():
    x=good(); del x["benchmark_protocol_ref"]
    assert "benchmark_protocol_ref" in m.validate_execution_evidence(x)["missing"]
    x=good(); x["execution_envelope"]["timeout_seconds"]=0
    assert "envelope_timeout_seconds_invalid" in m.validate_execution_evidence(x)["issues"]

def test_digest_and_outcome_binding_block():
    x=good(); x["result_artifacts"][0]["sha256_declared"]="bad"
    assert "artifact_sha256_declaration_invalid" in m.validate_execution_evidence(x)["issues"]
    x=good(); x["outcome_records"][0]["run_ref"]="unbound"
    assert "outcome_evidence_unbound" in m.validate_execution_evidence(x)["issues"]

def test_schema_must_cover_artifacts():
    x=good(); x["schema_validation"]["checked_artifact_refs"]=[]
    assert "schema_artifact_coverage_mismatch" in m.validate_execution_evidence(x)["issues"]

def test_sampling_uncertainty_and_comparison_validate():
    cases=[("sample_coverage","sample_count",0,"sample_counts_invalid"),
           ("uncertainty","confidence_level",1.0,"confidence_level_invalid"),
           ("baseline_comparison","direction","BETTER","comparison_direction_invalid")]
    for section,key,value,issue in cases:
        x=good(); x[section][key]=value
        assert issue in m.validate_execution_evidence(x)["issues"]

def test_failure_events_need_reason_and_timestamp():
    x=good(); x["failure_records"]=[{"event_ref":"f1","run_ref":"run-1","reason_code":"","occurred_at":"bad"}]
    r=m.validate_execution_evidence(x)
    assert "failure_reason_invalid" in r["issues"] and "failure_timestamp_invalid" in r["issues"]

def test_enforcement_and_automatic_execution_claims_block():
    x=good(); x["execution_envelope"]["enforced"]=True
    assert "envelope_must_not_claim_enforcement" in m.validate_execution_evidence(x)["issues"]
    x=good(); x["automatic_execution"]=True
    assert "automatic_execution_must_be_false" in m.validate_execution_evidence(x)["issues"]

def test_non_object_fails_closed():
    assert m.validate_execution_evidence(None)["status"]=="BLOCKED"
