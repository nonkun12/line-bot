"""Evaluation integrity and reproducibility declarations (AI Factory Stages 721-730).

Metadata-only validation. No files are fetched, hashes recomputed, signatures
verified, experiments reproduced, or statistical conclusions recalculated.
"""
from __future__ import annotations
import math
import re
from datetime import datetime

SHA256=re.compile(r"^[0-9a-f]{64}$")
REQUIRED=("integrity_ref","evaluation_ref","manifest","artifacts","environment",
          "attestation","evaluator","statistics","reproduction","provenance",
          "limitations","audit_ref","created_at")

def _text(v):
    return isinstance(v,str) and bool(v.strip())

def _time(v):
    if not _text(v): return False
    try: d=datetime.fromisoformat(v.replace("Z","+00:00"))
    except ValueError: return False
    return d.tzinfo is not None

def _refs(obj,keys,prefix,issues):
    for k in keys:
        if not _text(obj.get(k)): issues.append(f"{prefix}_{k}_invalid")

def validate_evaluation_integrity(record):
    if not isinstance(record,dict):
        return {"status":"BLOCKED","missing":["record_not_object"],"issues":["invalid_record"]}
    missing=[k for k in REQUIRED if k not in record or record[k] is None]
    issues=[]
    for k in ("integrity_ref","evaluation_ref","audit_ref"):
        if not _text(record.get(k)): issues.append(f"{k}_invalid")
    if not _time(record.get("created_at")): issues.append("created_at_invalid")

    manifest=record.get("manifest")
    if not isinstance(manifest,dict):
        issues.append("manifest_invalid")
    else:
        _refs(manifest,("manifest_ref","schema_ref","canonicalization_ref","root_digest"),"manifest",issues)
        if not SHA256.fullmatch(manifest.get("root_digest","")): issues.append("manifest_root_digest_invalid")
        if manifest.get("status")!="PASS_DECLARED": issues.append("manifest_not_pass_declared")
        if manifest.get("canonicalized") is not False: issues.append("canonicalization_must_not_be_claimed")
        if manifest.get("digest_recomputed") is not False: issues.append("digest_recomputation_must_not_be_claimed")

    artifacts=record.get("artifacts")
    if not isinstance(artifacts,list) or not artifacts:
        issues.append("artifacts_invalid"); artifacts=[]
    refs=[]
    for item in artifacts:
        if not isinstance(item,dict):
            issues.append("artifact_record_invalid"); continue
        _refs(item,("artifact_ref","role_ref","source_ref","media_type_ref","digest_ref"),"artifact",issues)
        if _text(item.get("artifact_ref")): refs.append(item["artifact_ref"])
        if not SHA256.fullmatch(item.get("sha256","")): issues.append("artifact_sha256_invalid")
        if item.get("status")!="PASS_DECLARED": issues.append("artifact_not_pass_declared")
        if item.get("retrieved") is not False: issues.append("artifact_retrieval_must_not_be_claimed")
        if item.get("digest_recomputed") is not False: issues.append("artifact_digest_recomputation_must_not_be_claimed")
    if len(refs)!=len(set(refs)): issues.append("artifact_refs_duplicate")

    environment=record.get("environment")
    if not isinstance(environment,dict):
        issues.append("environment_invalid")
    else:
        _refs(environment,("environment_ref","runtime_ref","dependency_lock_ref","hardware_ref","configuration_ref"),"environment",issues)
        if not SHA256.fullmatch(environment.get("fingerprint_sha256","")): issues.append("environment_fingerprint_invalid")
        if environment.get("status")!="PASS_DECLARED": issues.append("environment_not_pass_declared")
        if environment.get("fingerprint_recomputed") is not False: issues.append("environment_fingerprint_recomputation_must_not_be_claimed")

    attestation=record.get("attestation")
    if not isinstance(attestation,dict):
        issues.append("attestation_invalid")
    else:
        _refs(attestation,("attestation_ref","issuer_ref","subject_ref","key_ref","signature_ref","policy_ref"),"attestation",issues)
        if attestation.get("status")!="PASS_DECLARED": issues.append("attestation_not_pass_declared")
        if attestation.get("signature_verified") is not False: issues.append("signature_verification_must_not_be_claimed")
        if attestation.get("issuer_authenticated") is not False: issues.append("issuer_authentication_must_not_be_claimed")
        if not _time(attestation.get("issued_at")): issues.append("attestation_time_invalid")

    evaluator=record.get("evaluator")
    if not isinstance(evaluator,dict):
        issues.append("evaluator_invalid")
    else:
        _refs(evaluator,("evaluator_ref","independence_basis_ref","conflict_check_ref","assessment_ref"),"evaluator",issues)
        if evaluator.get("independent") is not True: issues.append("independent_evaluator_required")
        if evaluator.get("conflicts_disclosed") is not True: issues.append("conflict_disclosure_required")
        if evaluator.get("identity_authenticated") is not False: issues.append("evaluator_authentication_must_not_be_claimed")
        if evaluator.get("assessment_executed") is not False: issues.append("assessment_execution_must_not_be_claimed")

    statistics=record.get("statistics")
    if not isinstance(statistics,dict):
        issues.append("statistics_invalid")
    else:
        _refs(statistics,("analysis_plan_ref","method_ref","hypothesis_ref","threshold_ref","result_ref","uncertainty_ref"),"statistics",issues)
        if statistics.get("status")!="PASS_DECLARED": issues.append("statistics_not_pass_declared")
        if statistics.get("preregistered") is not True: issues.append("preregistration_required")
        if statistics.get("recomputed") is not False: issues.append("statistical_recomputation_must_not_be_claimed")
        for k in ("effect_size","confidence_level","p_value","minimum_effect"):
            v=statistics.get(k)
            if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v):
                issues.append(f"statistics_{k}_invalid")
        if isinstance(statistics.get("confidence_level"),(int,float)) and not isinstance(statistics.get("confidence_level"),bool) and not 0 < statistics["confidence_level"] < 1:
            issues.append("statistics_confidence_level_out_of_range")
        if isinstance(statistics.get("p_value"),(int,float)) and not isinstance(statistics.get("p_value"),bool) and not 0 <= statistics["p_value"] <= 1:
            issues.append("statistics_p_value_out_of_range")
        if isinstance(statistics.get("minimum_effect"),(int,float)) and not isinstance(statistics.get("minimum_effect"),bool) and statistics["minimum_effect"] < 0:
            issues.append("statistics_minimum_effect_negative")
        if statistics.get("decision")!="ACCEPT_DECLARED": issues.append("statistics_decision_not_accepted")

    reproduction=record.get("reproduction")
    if not isinstance(reproduction,dict):
        issues.append("reproduction_invalid")
    else:
        _refs(reproduction,("package_ref","instructions_ref","dependency_lock_ref","seed_ref","expected_output_ref","attempt_log_ref"),"reproduction",issues)
        if reproduction.get("status")!="PASS_DECLARED": issues.append("reproduction_not_pass_declared")
        if reproduction.get("attempted") is not False: issues.append("reproduction_attempt_must_not_be_claimed")
        if reproduction.get("outputs_compared") is not False: issues.append("output_comparison_must_not_be_claimed")
        if reproduction.get("independent_reproducer") is not True: issues.append("independent_reproducer_required")
        if reproduction.get("reproducer_authenticated") is not False: issues.append("reproducer_authentication_must_not_be_claimed")

    provenance=record.get("provenance")
    if not isinstance(provenance,list) or not provenance:
        issues.append("provenance_invalid"); provenance=[]
    provenance_refs=[]
    for item in provenance:
        if not isinstance(item,dict):
            issues.append("provenance_record_invalid"); continue
        _refs(item,("event_ref","actor_ref","input_ref","output_ref","previous_event_ref","evidence_ref"),"provenance",issues)
        if _text(item.get("event_ref")): provenance_refs.append(item["event_ref"])
        if item.get("status")!="PASS_DECLARED": issues.append("provenance_not_pass_declared")
        if item.get("chain_verified") is not False: issues.append("provenance_chain_verification_must_not_be_claimed")
    if len(provenance_refs)!=len(set(provenance_refs)): issues.append("provenance_refs_duplicate")

    limitations=record.get("limitations")
    if not isinstance(limitations,list) or not limitations:
        issues.append("limitations_required"); limitations=[]
    for item in limitations:
        if not isinstance(item,dict):
            issues.append("limitation_record_invalid"); continue
        _refs(item,("limitation_ref","impact_ref","owner_ref"),"limitation",issues)
        if item.get("disposition") not in ("ACCEPTED_DECLARED","MITIGATION_PLANNED"): issues.append("limitation_not_accepted")

    if missing or issues:
        return {"status":"BLOCKED","missing":missing,"issues":sorted(set(issues))}
    return {"status":"DECLARATIONS_COMPLETE","missing":[],"issues":[],
            "artifacts_retrieved":False,"hashes_recomputed":False,
            "signatures_verified":False,"statistics_recomputed":False,
            "reproduction_executed":False,"provenance_chain_verified":False}

def stage_730_evaluation_integrity_gate(record):
    result=validate_evaluation_integrity(record)
    return {**result,
            "gate":"READY_FOR_EXTERNAL_VERIFICATION" if result["status"]=="DECLARATIONS_COMPLETE" else "BLOCKED",
            "evaluation_integrity_verified":False,"capability_improvement_verified":False,
            "model_change_authorized":False}
