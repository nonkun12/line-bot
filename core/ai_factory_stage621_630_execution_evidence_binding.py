"""Execution evidence binding declarations (Stages 621-630).

All checks validate caller-supplied metadata only. No workload is executed,
artifact bytes are not read, and resource limits are not enforced by this module.
"""
from __future__ import annotations
import math
import re
from datetime import datetime

REQUIRED = ("experiment_ref", "protocol_ref", "execution_envelope", "result_artifacts",
"outcome_records", "failure_records", "abort_records", "output_schema_ref", "schema_validation",
"benchmark_protocol_ref", "sample_coverage", "uncertainty", "baseline_comparison",
"created_at", "automatic_execution")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

def _text(v):
    return isinstance(v, str) and bool(v.strip())

def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def _timestamp(v):
    if not _text(v): return None
    try: d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def _digest(v):
    return _text(v) and bool(SHA256_RE.fullmatch(v))

def _validate_envelope(v):
    issues = []
    if not isinstance(v, dict): return ["execution_envelope_invalid"]
    for k in ("environment_ref", "command_ref", "input_manifest_ref"):
        if not _text(v.get(k)): issues.append(f"envelope_{k}_invalid")
    for k in ("timeout_seconds", "memory_limit_mb", "cpu_limit"):
        if not _number(v.get(k)) or v[k] <= 0: issues.append(f"envelope_{k}_invalid")
    if v.get("network_policy") not in ("DENY_DECLARED", "ALLOWLIST_DECLARED"):
        issues.append("envelope_network_policy_invalid")
    if v.get("enforced") is not False: issues.append("envelope_must_not_claim_enforcement")
    return issues

def _validate_artifacts(v):
    issues, refs = [], []
    if not isinstance(v, list) or not v: return ["result_artifacts_invalid"]
    for x in v:
        if not isinstance(x, dict):
            issues.append("result_artifact_invalid"); continue
        for k in ("artifact_ref", "run_ref", "media_type"):
            if not _text(x.get(k)): issues.append(f"artifact_{k}_invalid")
        if not _digest(x.get("sha256_declared")): issues.append("artifact_sha256_declaration_invalid")
        n = x.get("size_bytes")
        if not isinstance(n, int) or isinstance(n, bool) or n < 0: issues.append("artifact_size_invalid")
        if _text(x.get("artifact_ref")): refs.append(x["artifact_ref"])
    if len(refs) != len(set(refs)): issues.append("artifact_refs_duplicate")
    return issues

def _validate_outcomes(v):
    if not isinstance(v, list) or not v: return ["outcome_records_invalid"]
    issues, refs = [], []
    for x in v:
        if not isinstance(x, dict):
            issues.append("outcome_record_invalid"); continue
        if not _text(x.get("run_ref")): issues.append("outcome_run_ref_invalid")
        else: refs.append(x["run_ref"])
        if x.get("outcome") not in ("SUCCEEDED_DECLARED", "FAILED_DECLARED", "ABORTED_DECLARED"):
            issues.append("outcome_value_invalid")
        a, b = _timestamp(x.get("started_at")), _timestamp(x.get("finished_at"))
        if a is None or b is None or b < a: issues.append("outcome_timestamps_invalid")
    if len(refs) != len(set(refs)): issues.append("outcome_run_refs_duplicate")
    return issues

def _validate_events(v, kind):
    if not isinstance(v, list): return [f"{kind}_records_invalid"]
    issues, refs = [], []
    for x in v:
        if not isinstance(x, dict):
            issues.append(f"{kind}_record_invalid"); continue
        if not _text(x.get("event_ref")) or not _text(x.get("run_ref")):
            issues.append(f"{kind}_identity_invalid")
        else: refs.append(x["event_ref"])
        if not _text(x.get("reason_code")): issues.append(f"{kind}_reason_invalid")
        if _timestamp(x.get("occurred_at")) is None: issues.append(f"{kind}_timestamp_invalid")
    if len(refs) != len(set(refs)): issues.append(f"{kind}_event_refs_duplicate")
    return issues

def validate_execution_evidence(record):
    if not isinstance(record, dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing = [k for k in REQUIRED if k not in record or record[k] is None]
    issues = []
    for k in ("experiment_ref","protocol_ref","output_schema_ref","benchmark_protocol_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    issues += _validate_envelope(record.get("execution_envelope"))
    issues += _validate_artifacts(record.get("result_artifacts"))
    issues += _validate_outcomes(record.get("outcome_records"))
    issues += _validate_events(record.get("failure_records"), "failure")
    issues += _validate_events(record.get("abort_records"), "abort")
    schema = record.get("schema_validation")
    if not isinstance(schema, dict): issues.append("schema_validation_invalid")
    else:
        if schema.get("status") != "SCHEMA_VALIDATION_DECLARED_PASS": issues.append("schema_validation_not_pass_declared")
        if not _text(schema.get("validator_ref")): issues.append("schema_validator_ref_invalid")
        expected = [x.get("artifact_ref") for x in record.get("result_artifacts", [])
                    if isinstance(x, dict) and _text(x.get("artifact_ref"))]
        if schema.get("checked_artifact_refs") != expected: issues.append("schema_artifact_coverage_mismatch")
    cov = record.get("sample_coverage")
    if not isinstance(cov, dict): issues.append("sample_coverage_invalid")
    else:
        for k in ("population_ref","sample_manifest_ref"):
            if not _text(cov.get(k)): issues.append(f"coverage_{k}_invalid")
        total, sample = cov.get("population_count"), cov.get("sample_count")
        if (not isinstance(total,int) or isinstance(total,bool) or total <= 0 or
            not isinstance(sample,int) or isinstance(sample,bool) or sample <= 0 or sample > total):
            issues.append("sample_counts_invalid")
        if cov.get("sampling_method") not in ("CENSUS_DECLARED","RANDOM_DECLARED","STRATIFIED_DECLARED","PURPOSIVE_DECLARED"):
            issues.append("sampling_method_invalid")
    unc = record.get("uncertainty")
    if not isinstance(unc, dict): issues.append("uncertainty_invalid")
    else:
        lo, hi, level = unc.get("lower_bound"), unc.get("upper_bound"), unc.get("confidence_level")
        if not _number(lo) or not _number(hi) or lo > hi: issues.append("uncertainty_bounds_invalid")
        if not _number(level) or not 0 < level < 1: issues.append("confidence_level_invalid")
        if not _text(unc.get("method_ref")): issues.append("uncertainty_method_ref_invalid")
    comp = record.get("baseline_comparison")
    if not isinstance(comp, dict): issues.append("baseline_comparison_invalid")
    else:
        for k in ("baseline_ref","candidate_ref","metric_name","comparison_protocol_ref"):
            if not _text(comp.get(k)): issues.append(f"comparison_{k}_invalid")
        if not _number(comp.get("delta")): issues.append("comparison_delta_invalid")
        if comp.get("direction") not in ("IMPROVED_DECLARED","REGRESSED_DECLARED","UNCHANGED_DECLARED","INCONCLUSIVE_DECLARED"):
            issues.append("comparison_direction_invalid")
        if comp.get("baseline_ref") == comp.get("candidate_ref"): issues.append("comparison_refs_must_differ")
    if _timestamp(record.get("created_at")) is None: issues.append("created_at_invalid")
    if record.get("automatic_execution") is not False: issues.append("automatic_execution_must_be_false")
    outcomes = {x.get("run_ref") for x in record.get("outcome_records",[]) if isinstance(x,dict)}
    artifacts = {x.get("run_ref") for x in record.get("result_artifacts",[]) if isinstance(x,dict)}
    events = {x.get("run_ref") for k in ("failure_records","abort_records")
              for x in record.get(k,[]) if isinstance(x,dict)}
    if outcomes and not outcomes.issubset(artifacts | events): issues.append("outcome_evidence_unbound")
    if missing or issues: return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "artifact_bytes_inspected":False,"digests_verified":False,
            "resource_limits_enforced":False,"schema_validation_executed":False,
            "sample_representativeness_verified":False,"uncertainty_recomputed":False,
            "baseline_result_recomputed":False}

def stage_630_execution_evidence_gate(record):
    result = validate_execution_evidence(record)
    ready = result["status"] == "DECLARATIONS_COMPLETE"
    return {**result,"gate":"READY_FOR_INDEPENDENT_REVIEW" if ready else "BLOCKED",
            "execution_authorized":False,"automatic_execution":False,
            "release_authorized":False,"capability_gain_verified":False}
