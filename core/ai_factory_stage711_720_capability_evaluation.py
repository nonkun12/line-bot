"""Capability evaluation evidence declarations (AI Factory Stages 711-720).

This module validates supplied evaluation metadata. It does not execute models,
benchmarks, statistical tests, or authenticate evaluators.
"""
from __future__ import annotations
import math
from datetime import datetime

REQUIRED=("evaluation_ref","subject_ref","candidate_ref","baseline_ref","protocol",
          "metrics","datasets","runs","replications","regression_checks",
          "uncertainty","independent_assessment","limitations","audit_ref",
          "created_at","evaluation_executed")

def _text(v):
    return isinstance(v,str) and bool(v.strip())

def _time(v):
    if not _text(v): return None
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return None
    return d if d.tzinfo is not None else None

def _finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def _refs(obj,keys,prefix,issues):
    for k in keys:
        if not _text(obj.get(k)): issues.append(f"{prefix}_{k}_invalid")

def validate_capability_evaluation(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("evaluation_ref","subject_ref","candidate_ref","baseline_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    if _time(record.get("created_at")) is None: issues.append("created_at_invalid")
    if record.get("evaluation_executed") is not False:
        issues.append("evaluation_execution_must_not_be_claimed")

    protocol=record.get("protocol")
    if not isinstance(protocol,dict):
        issues.append("protocol_invalid")
    else:
        _refs(protocol,("protocol_ref","version_ref","environment_ref","command_ref","owner_ref"),"protocol",issues)
        if protocol.get("status")!="PASS_DECLARED": issues.append("protocol_not_pass_declared")
        if protocol.get("frozen") is not True: issues.append("protocol_not_frozen")
        if protocol.get("execution_performed") is not False: issues.append("protocol_execution_must_not_be_claimed")

    metrics=record.get("metrics")
    if not isinstance(metrics,list) or not metrics:
        issues.append("metrics_invalid"); metrics=[]
    metric_refs=[]
    for item in metrics:
        if not isinstance(item,dict):
            issues.append("metric_record_invalid"); continue
        _refs(item,("metric_ref","definition_ref","unit_ref","baseline_value_ref","candidate_value_ref","acceptance_rule_ref","evidence_ref"),"metric",issues)
        if _text(item.get("metric_ref")): metric_refs.append(item["metric_ref"])
        if item.get("direction") not in ("HIGHER_IS_BETTER","LOWER_IS_BETTER","TARGET_RANGE"):
            issues.append("metric_direction_invalid")
        if item.get("status")!="PASS_DECLARED": issues.append("metric_not_pass_declared")
        for k in ("baseline_value","candidate_value","minimum_improvement","maximum_regression"):
            if not _finite(item.get(k)): issues.append(f"metric_{k}_invalid")
        if item.get("measurement_executed") is not False: issues.append("metric_measurement_must_not_be_claimed")
    if len(metric_refs)!=len(set(metric_refs)): issues.append("metric_refs_duplicate")

    datasets=record.get("datasets")
    if not isinstance(datasets,list) or not datasets:
        issues.append("datasets_invalid"); datasets=[]
    dataset_refs=[]
    for item in datasets:
        if not isinstance(item,dict):
            issues.append("dataset_record_invalid"); continue
        _refs(item,("dataset_ref","version_ref","provenance_ref","split_ref","license_ref"),"dataset",issues)
        if _text(item.get("dataset_ref")): dataset_refs.append(item["dataset_ref"])
        if item.get("status")!="PASS_DECLARED": issues.append("dataset_not_pass_declared")
        if item.get("data_accessed") is not False: issues.append("dataset_access_must_not_be_claimed")
    if len(dataset_refs)!=len(set(dataset_refs)): issues.append("dataset_refs_duplicate")

    runs=record.get("runs")
    if not isinstance(runs,list) or not runs:
        issues.append("runs_invalid"); runs=[]
    run_refs=[]
    for item in runs:
        if not isinstance(item,dict):
            issues.append("run_record_invalid"); continue
        _refs(item,("run_ref","input_manifest_ref","output_manifest_ref","environment_ref","result_evidence_ref"),"run",issues)
        if _text(item.get("run_ref")): run_refs.append(item["run_ref"])
        if item.get("status") not in ("PASS_DECLARED","FAIL_DECLARED","INCOMPLETE"):
            issues.append("run_status_invalid")
        elif item.get("status")!="PASS_DECLARED": issues.append("run_not_pass_declared")
        if item.get("executed") is not False: issues.append("run_execution_must_not_be_claimed")
    if len(run_refs)!=len(set(run_refs)): issues.append("run_refs_duplicate")

    replications=record.get("replications")
    if not isinstance(replications,list) or not replications:
        issues.append("replications_invalid"); replications=[]
    replication_refs=[]
    for item in replications:
        if not isinstance(item,dict):
            issues.append("replication_record_invalid"); continue
        _refs(item,("replication_ref","replicator_ref","protocol_ref","result_evidence_ref"),"replication",issues)
        if _text(item.get("replication_ref")): replication_refs.append(item["replication_ref"])
        if item.get("status")!="PASS_DECLARED": issues.append("replication_not_pass_declared")
        if item.get("replication_executed") is not False: issues.append("replication_execution_must_not_be_claimed")
        if item.get("replicator_independent") is not True: issues.append("independent_replication_required")
        if item.get("replicator_authenticated") is not False: issues.append("replicator_authentication_must_not_be_claimed")
    if len(replication_refs)!=len(set(replication_refs)): issues.append("replication_refs_duplicate")

    regressions=record.get("regression_checks")
    if not isinstance(regressions,list) or not regressions:
        issues.append("regression_checks_invalid"); regressions=[]
    regression_refs=[]
    for item in regressions:
        if not isinstance(item,dict):
            issues.append("regression_record_invalid"); continue
        _refs(item,("check_ref","metric_ref","threshold_ref","evidence_ref"),"regression",issues)
        if _text(item.get("check_ref")): regression_refs.append(item["check_ref"])
        if item.get("status")!="PASS_DECLARED": issues.append("regression_not_pass_declared")
        if item.get("check_executed") is not False: issues.append("regression_execution_must_not_be_claimed")
    if len(regression_refs)!=len(set(regression_refs)): issues.append("regression_refs_duplicate")

    uncertainty=record.get("uncertainty")
    if not isinstance(uncertainty,dict):
        issues.append("uncertainty_invalid")
    else:
        _refs(uncertainty,("method_ref","interval_ref","assumptions_ref","evidence_ref"),"uncertainty",issues)
        if uncertainty.get("status")!="PASS_DECLARED": issues.append("uncertainty_not_pass_declared")
        if uncertainty.get("computed") is not False: issues.append("uncertainty_computation_must_not_be_claimed")

    assessment=record.get("independent_assessment")
    if not isinstance(assessment,dict):
        issues.append("independent_assessment_invalid")
    else:
        _refs(assessment,("assessor_ref","decision_ref","evidence_ref","assessed_at"),"assessment",issues)
        if assessment.get("decision")!="ACCEPT_DECLARED": issues.append("independent_assessment_not_accepted")
        if assessment.get("independent") is not True: issues.append("independent_assessor_required")
        if assessment.get("assessor_authenticated") is not False: issues.append("assessor_authentication_must_not_be_claimed")
        if _time(assessment.get("assessed_at")) is None: issues.append("assessment_time_invalid")

    limitations=record.get("limitations")
    if not isinstance(limitations,list) or not limitations:
        issues.append("limitations_required"); limitations=[]
    limitation_refs=[]
    for item in limitations:
        if not isinstance(item,dict):
            issues.append("limitation_record_invalid"); continue
        _refs(item,("limitation_ref","description_ref","impact_ref","owner_ref"),"limitation",issues)
        if _text(item.get("limitation_ref")): limitation_refs.append(item["limitation_ref"])
        if item.get("disposition") not in ("ACCEPTED_DECLARED","MITIGATION_PLANNED","BLOCKING"):
            issues.append("limitation_disposition_invalid")
        elif item.get("disposition")=="BLOCKING": issues.append("blocking_limitation_present")
    if len(limitation_refs)!=len(set(limitation_refs)): issues.append("limitation_refs_duplicate")

    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "benchmark_executed":False,"measurements_recomputed":False,
            "replications_executed":False,"assessor_authenticated":False,
            "general_intelligence_proven":False}

def stage_720_capability_evaluation_gate(record):
    result=validate_capability_evaluation(record)
    return {**result,
            "gate":"READY_FOR_INDEPENDENT_REVIEW" if result["status"]=="DECLARATIONS_COMPLETE" else "BLOCKED",
            "capability_improvement_verified":False,"model_change_authorized":False}
